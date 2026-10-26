from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from . import models as m
from .lim_errors import LimRuntimeError
from .lim_models import (
    LimAgent, LimEvalCase, LimEvalCaseResult, LimEvalDataset, LimEvalRun, LimRun, LimToolInvocation,
)
from .lim_runtime import create_run, invoke_read_tool, sanitize_trace_value, transition_run


class EvalCaseInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    case_id: str = Field(min_length=1, max_length=64)
    scenario: str = Field(min_length=1, max_length=500)
    input_payload: dict
    scope: dict = Field(default_factory=dict)
    ground_truth: dict | None = None
    acceptable_outputs: list = Field(default_factory=list, max_length=50)
    required_evidence: list[str] = Field(default_factory=list, max_length=50)
    forbidden_actions: list[str] = Field(default_factory=list, max_length=50)
    risk_tier: Literal['low', 'medium', 'high', 'critical']
    tags: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode='after')
    def require_expected_result(self):
        if self.ground_truth is None and not self.acceptable_outputs:
            raise ValueError('每个可评测用例必须提供 ground_truth 或 acceptable_outputs')
        return self


class DatasetCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    dataset_id: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=1000)
    cases: list[EvalCaseInput] = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def require_unique_case_ids(self):
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError('case_id 在同一数据集版本中必须唯一')
        return self


class EvalRunInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    dataset_id: str = Field(min_length=1, max_length=64)
    dataset_version: str = Field(min_length=1, max_length=32)
    agent_id: str = Field(min_length=1, max_length=64)
    agent_version: str = Field(min_length=1, max_length=32)
    environment: Literal['DEV', 'STAGING'] = 'DEV'


def dataset_result(dataset: LimEvalDataset, cases: list[LimEvalCase] | None = None) -> dict:
    value = {
        'dataset_id': dataset.dataset_id, 'version': dataset.version, 'name': dataset.name,
        'description': dataset.description, 'status': dataset.status,
        'owner_id': dataset.owner_id, 'created_at': dataset.created_at,
    }
    if cases is not None:
        value['cases'] = [{
            'case_id': case.case_id, 'scenario': case.scenario, 'input_payload': case.input_payload,
            'scope': case.scope, 'ground_truth': case.ground_truth,
            'acceptable_outputs': case.acceptable_outputs, 'required_evidence': case.required_evidence,
            'forbidden_actions': case.forbidden_actions, 'risk_tier': case.risk_tier, 'tags': case.tags,
        } for case in cases]
    return value


def _matches(actual: object, expected: object) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and _matches(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and actual == expected
    return actual == expected


def _strings(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(_strings(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_strings(item) for item in value)) if value else set()
    return set()


def _case_result(db, actor, eval_run: LimEvalRun, case: LimEvalCase, agent_version: str) -> LimEvalCaseResult:
    started = m.now()
    payload = case.input_payload or {}
    tool_id = payload.get('tool_id')
    tool_version = payload.get('tool_version')
    arguments = payload.get('arguments', {})
    goal = payload.get('goal') or case.scenario
    actual = {}
    failures: list[str] = []
    outcome = 'NOT_EVALUATED'
    run: LimRun | None = None
    try:
        if not isinstance(tool_id, str) or not isinstance(arguments, dict):
            raise LimRuntimeError('EVAL_INPUT_INVALID', '评测输入必须包含 tool_id 和 arguments 对象', status_code=422)
        run = create_run(
            db, actor, eval_run.agent_id, str(goal), case.scope, agent_version=agent_version,
            selected_tool_id=tool_id, selected_tool_version=tool_version,
        )
        transition_run(db, run, 'RUNNING')
        actual = invoke_read_tool(db, actor, run, tool_id, arguments)
        invocations = db.scalars(select(LimToolInvocation).where(LimToolInvocation.run_id == run.run_id)).all()
        transition_run(db, run, 'VERIFYING')
        if case.ground_truth is None and not case.acceptable_outputs:
            outcome = 'NOT_EVALUATED'
            failures.append('EXPECTED_OUTPUT_MISSING')
        else:
            expectations = [case.ground_truth] if case.ground_truth is not None else case.acceptable_outputs
            if not any(_matches(actual, expected) for expected in expectations):
                failures.append('ACCEPTABLE_OUTPUT_NOT_MATCHED')
            evidence = _strings(actual) | {reference for invocation in invocations for reference in (invocation.evidence_refs or [])}
            for required in case.required_evidence:
                if required not in evidence:
                    failures.append('REQUIRED_EVIDENCE_MISSING')
            for forbidden in case.forbidden_actions:
                if forbidden.casefold() in {'write', 'external_write', 'side_effect'} and any(
                    not invocation.read_only or invocation.status != 'SUCCEEDED' for invocation in invocations
                ):
                    failures.append('FORBIDDEN_ACTION_ATTEMPTED')
            outcome = 'FAIL' if failures else 'PASS'
        transition_run(db, run, 'COMPLETED' if outcome != 'FAIL' else 'REVIEW_REQUIRED')
    except LimRuntimeError as exc:
        if run is not None and run.status == 'RUNNING':
            transition_run(db, run, 'FAILED', error_code=exc.code)
        failures.append(exc.code)
        actual = {'error_code': exc.code}
        outcome = 'FAIL'
    result = LimEvalCaseResult(
        eval_run_id=eval_run.eval_run_id, dataset_id=case.dataset_id,
        dataset_version=case.dataset_version, case_id=case.case_id, outcome=outcome,
        actual_output=sanitize_trace_value({**actual, **({'run_id': run.run_id, 'trace_id': run.trace_id} if run else {})}),
        failures=list(dict.fromkeys(failures)), elapsed_ms=max(0, int((m.now() - started).total_seconds() * 1000)),
    )
    db.add(result)
    db.flush()
    return result


def run_evaluation(db, actor, request: EvalRunInput) -> LimEvalRun:
    dataset = db.scalar(select(LimEvalDataset).where(
        LimEvalDataset.dataset_id == request.dataset_id, LimEvalDataset.version == request.dataset_version,
    ))
    if dataset is None or dataset.status == 'archived':
        raise LimRuntimeError('EVAL_DATASET_NOT_FOUND', '评测数据集版本不存在或已归档', status_code=404)
    agent = db.scalar(select(LimAgent).where(
        LimAgent.agent_id == request.agent_id, LimAgent.version == request.agent_version,
        LimAgent.status == 'validated',
    ))
    if agent is None:
        raise LimRuntimeError('EVAL_AGENT_VERSION_NOT_FOUND', '指定 Agent 版本未验证或不存在', status_code=404)
    cases = db.scalars(select(LimEvalCase).where(
        LimEvalCase.dataset_id == dataset.dataset_id, LimEvalCase.dataset_version == dataset.version,
    ).order_by(LimEvalCase.case_id)).all()
    if not cases:
        raise LimRuntimeError('EVAL_DATASET_EMPTY', '空数据集不可运行', status_code=422)
    dataset.status = 'frozen'
    eval_run = LimEvalRun(
        eval_run_id=str(uuid4()), dataset_id=dataset.dataset_id, dataset_version=dataset.version,
        agent_id=agent.agent_id, agent_version=agent.version, actor_id=actor.id,
        environment=request.environment, status='RUNNING', metrics={}, started_at=m.now(),
    )
    db.add(eval_run)
    db.flush()
    results = [_case_result(db, actor, eval_run, case, agent.version) for case in cases]
    passed = sum(result.outcome == 'PASS' for result in results)
    failed = sum(result.outcome == 'FAIL' for result in results)
    not_evaluated = sum(result.outcome == 'NOT_EVALUATED' for result in results)
    scored = passed + failed
    eval_run.metrics = {
        'total': len(results), 'passed': passed, 'failed': failed, 'not_evaluated': not_evaluated,
        'pass_rate': passed / scored if scored else None,
        'semantic_quality': 'NOT_EVALUATED',
    }
    eval_run.status = 'COMPLETED'
    eval_run.finished_at = m.now()
    db.flush()
    return eval_run


def eval_run_result(db, eval_run: LimEvalRun) -> dict:
    results = db.scalars(select(LimEvalCaseResult).where(
        LimEvalCaseResult.eval_run_id == eval_run.eval_run_id,
    ).order_by(LimEvalCaseResult.case_id)).all()
    return {
        'eval_run_id': eval_run.eval_run_id, 'dataset_id': eval_run.dataset_id,
        'dataset_version': eval_run.dataset_version, 'agent_id': eval_run.agent_id,
        'agent_version': eval_run.agent_version, 'actor_id': eval_run.actor_id,
        'environment': eval_run.environment, 'status': eval_run.status,
        'metrics': eval_run.metrics, 'error_code': eval_run.error_code,
        'started_at': eval_run.started_at, 'finished_at': eval_run.finished_at,
        'cases': [{
            'case_id': result.case_id, 'outcome': result.outcome,
            'actual_output': result.actual_output, 'failures': result.failures,
            'elapsed_ms': result.elapsed_ms,
        } for result in results],
    }
