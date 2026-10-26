import hashlib
import json
from uuid import uuid4

from sqlalchemy import select

from . import models as m
from .lim_errors import LimRuntimeError
from .lim_models import LimEvalCase, LimEvalCaseResult, LimEvalComparison, LimEvalRun


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _diff(before, after, path='$'):
    if isinstance(before, dict) and isinstance(after, dict):
        out = []
        for key in sorted(set(before) | set(after)):
            if key in {'run_id', 'trace_id'} and path == '$':
                continue
            if key not in before or key not in after:
                out.append({'path': f'{path}.{key}', 'baseline': before.get(key), 'candidate': after.get(key)})
            else:
                out.extend(_diff(before[key], after[key], f'{path}.{key}'))
        return out
    if isinstance(before, list) and isinstance(after, list):
        out = []
        for index in range(max(len(before), len(after))):
            item_path = f'{path}[{index}]'
            if index >= len(before) or index >= len(after):
                out.append({'path': item_path,
                            'baseline': before[index] if index < len(before) else None,
                            'candidate': after[index] if index < len(after) else None})
            else:
                out.extend(_diff(before[index], after[index], item_path))
        return out
    return [] if before == after else [{'path': path, 'baseline': before, 'candidate': after}]


def _report_hash(payload: dict) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _case_rows(db, run):
    return db.scalars(select(LimEvalCaseResult).where(
        LimEvalCaseResult.eval_run_id == run.eval_run_id,
    ).order_by(LimEvalCaseResult.case_id)).all()


def create_comparison(db, actor, baseline_id: str, candidate_id: str, thresholds: dict, can_view_others=False) -> LimEvalComparison:
    baseline = db.scalar(select(LimEvalRun).where(LimEvalRun.eval_run_id == baseline_id))
    candidate = db.scalar(select(LimEvalRun).where(LimEvalRun.eval_run_id == candidate_id))
    if baseline is None or candidate is None:
        raise LimRuntimeError('EVAL_RUN_NOT_FOUND', '评测运行不存在或不可访问', status_code=404)
    if not can_view_others and (baseline.actor_id != actor.id or candidate.actor_id != actor.id):
        raise LimRuntimeError('EVAL_RUN_NOT_FOUND', '评测运行不存在或不可访问', status_code=404)
    if (baseline.eval_run_id == candidate.eval_run_id or baseline.status != 'COMPLETED' or candidate.status != 'COMPLETED'
        or baseline.dataset_id != candidate.dataset_id or baseline.dataset_version != candidate.dataset_version
        or baseline.environment != candidate.environment or baseline.agent_id != candidate.agent_id
        or baseline.agent_version == candidate.agent_version):
        raise LimRuntimeError('EVAL_COMPARISON_INCOMPATIBLE', '两次评测运行不满足版本比较条件', status_code=422)

    before_rows, after_rows = _case_rows(db, baseline), _case_rows(db, candidate)
    before = {row.case_id: row for row in before_rows}
    after = {row.case_id: row for row in after_rows}
    expected = set(db.scalars(select(LimEvalCase.case_id).where(
        LimEvalCase.dataset_id == baseline.dataset_id, LimEvalCase.dataset_version == baseline.dataset_version,
    )).all())
    if not expected or set(before) != expected or set(after) != expected:
        raise LimRuntimeError('EVAL_RESULTS_INCOMPLETE', '评测结果不完整，无法比较', status_code=422)

    cases = []
    regressions = improvements = critical_regressions = 0
    case_by_id = {row.case_id: row for row in db.scalars(select(LimEvalCase).where(
        LimEvalCase.dataset_id == baseline.dataset_id, LimEvalCase.dataset_version == baseline.dataset_version,
    )).all()}
    for case_id in sorted(expected):
        left, right = before[case_id], after[case_id]
        if 'NOT_EVALUATED' in (left.outcome, right.outcome):
            classification = 'UNCOMPARABLE'
        elif left.outcome == 'PASS' and right.outcome == 'FAIL':
            classification = 'REGRESSION'
            regressions += 1
            critical_regressions += case_by_id[case_id].risk_tier == 'critical'
        elif left.outcome == 'FAIL' and right.outcome == 'PASS':
            classification = 'IMPROVED'
            improvements += 1
        else:
            classification = 'UNCHANGED'
        left_output, right_output = left.actual_output or {}, right.actual_output or {}
        cases.append({
            'case_id': case_id, 'risk_tier': case_by_id[case_id].risk_tier,
            'baseline_outcome': left.outcome, 'candidate_outcome': right.outcome,
            'classification': classification, 'baseline_failures': left.failures or [],
            'candidate_failures': right.failures or [], 'output_changes': _diff(left_output, right_output),
            'baseline_run_id': left_output.get('run_id'), 'baseline_trace_id': left_output.get('trace_id'),
            'candidate_run_id': right_output.get('run_id'), 'candidate_trace_id': right_output.get('trace_id'),
            'baseline_elapsed_ms': left.elapsed_ms, 'candidate_elapsed_ms': right.elapsed_ms,
        })

    def counts(rows):
        passed = sum(row.outcome == 'PASS' for row in rows)
        failed = sum(row.outcome == 'FAIL' for row in rows)
        unscored = sum(row.outcome == 'NOT_EVALUATED' for row in rows)
        denominator = passed + failed
        return {'passed': passed, 'failed': failed, 'not_evaluated': unscored,
                'pass_rate': passed / denominator if denominator else None}

    left_counts, right_counts = counts(before_rows), counts(after_rows)
    drop = None if left_counts['pass_rate'] is None or right_counts['pass_rate'] is None else left_counts['pass_rate'] - right_counts['pass_rate']
    checks = {
        'pass_rate_drop_within_threshold': drop is not None and drop <= thresholds['max_pass_rate_drop'],
        'case_regressions_within_threshold': regressions <= thresholds['max_case_regressions'],
        'critical_regressions_within_threshold': critical_regressions <= thresholds['max_critical_case_regressions'],
    }
    status = 'NOT_EVALUATED' if not left_counts['passed'] + left_counts['failed'] + right_counts['passed'] + right_counts['failed'] else ('PASS' if all(checks.values()) else 'FAIL')
    payload = {
        'comparison_id': str(uuid4()), 'baseline': {'eval_run_id': baseline.eval_run_id, 'dataset_id': baseline.dataset_id,
            'dataset_version': baseline.dataset_version, 'agent_id': baseline.agent_id, 'agent_version': baseline.agent_version,
            'environment': baseline.environment, 'metrics': left_counts},
        'candidate': {'eval_run_id': candidate.eval_run_id, 'dataset_id': candidate.dataset_id,
            'dataset_version': candidate.dataset_version, 'agent_id': candidate.agent_id, 'agent_version': candidate.agent_version,
            'environment': candidate.environment, 'metrics': right_counts},
        'thresholds': thresholds,
        'summary': {'pass_rate_drop': drop, 'regressions': regressions, 'improvements': improvements,
            'critical_case_regressions': critical_regressions,
            'baseline_average_elapsed_ms': _avg(before_rows), 'candidate_average_elapsed_ms': _avg(after_rows),
            'threshold_checks': checks},
        'status': status, 'cases': cases,
    }
    digest = _report_hash(payload)
    record = LimEvalComparison(comparison_id=payload['comparison_id'], actor_id=actor.id,
        baseline_eval_run_id=baseline.eval_run_id, candidate_eval_run_id=candidate.eval_run_id,
        report=payload, report_hash=digest, status=status)
    db.add(record)
    db.flush()
    return record


def _avg(rows):
    values = [row.elapsed_ms for row in rows if row.elapsed_ms is not None]
    return sum(values) / len(values) if values else None


def comparison_result(record: LimEvalComparison) -> dict:
    payload = record.report or {}
    valid = _report_hash(payload) == record.report_hash
    return {**payload, 'report_hash': record.report_hash, 'integrity_valid': valid}
