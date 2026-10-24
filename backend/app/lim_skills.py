"""Governed LIM Skill metadata; definitions are inert and never executed here."""

import re
import math
from datetime import datetime, timezone

from sqlalchemy import select

from . import models as m
from .lim_errors import LimRuntimeError
from .lim_models import LimSkill, LimSkillVersion
from .lim_safety import sanitize_trace_value
from .security import record_audit


MEMORY_LEVELS = {'short_term', 'episodic', 'semantic', 'procedural'}
SKILL_TEMPLATES = {'catalog_review.v1', 'inventory_review.v1', 'order_review.v1'}
CAPABILITY_TAGS = {'listing_quality', 'inventory_health', 'order_health'}
BUSINESS_DOMAINS = {'catalog', 'inventory', 'orders'}
_SAFE_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')
_HASH = re.compile(r'^[a-f0-9]{64}$')
TRANSITIONS = {
    'CANDIDATE': {'UNDER_REVIEW'},
    'UNDER_REVIEW': {'VERIFIED', 'CANDIDATE', 'REVOKED'},
    'VERIFIED': {'ACTIVE', 'REVOKED'},
    'ACTIVE': {'DEGRADED', 'FROZEN', 'REVOKED'},
    'DEGRADED': {'UNDER_REVIEW', 'FROZEN', 'REVOKED'},
    'FROZEN': {'UNDER_REVIEW', 'REVOKED'},
    'REVOKED': set(),
}


def _parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _safe_id(value, field):
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise LimRuntimeError('SKILL_METADATA_INVALID', f'{field} 必须是稳定引用 ID，不接受自由文本', status_code=422)
    return value


def _validate_candidate_metadata(payload):
    definition = payload.get('definition')
    if (not isinstance(definition, dict) or set(definition) != {'template_id', 'capability_tags'}
            or not isinstance(definition.get('template_id'), str)
            or definition.get('template_id') not in SKILL_TEMPLATES
            or not isinstance(definition.get('capability_tags'), list)
            or not definition['capability_tags']
            or len(definition['capability_tags']) > 8
            or any(not isinstance(tag, str) or tag not in CAPABILITY_TAGS
                   for tag in definition['capability_tags'])):
        raise LimRuntimeError('SKILL_DEFINITION_INVALID', 'definition 仅接受已登记模板 ID 和能力标签', status_code=422)
    source_event = _safe_id(payload.get('source_event'), 'source_event')
    refs = payload.get('evidence_refs')
    if not isinstance(refs, list) or len(refs) > 100:
        raise LimRuntimeError('SKILL_METADATA_INVALID', 'evidence_refs 必须是有限列表', status_code=422)
    safe_refs = []
    for ref in refs:
        if (not isinstance(ref, dict) or set(ref) != {'ref_id', 'source_version', 'content_hash'}
                or not _SAFE_ID.fullmatch(str(ref.get('ref_id', '')))
                or not _SAFE_ID.fullmatch(str(ref.get('source_version', '')))
                or not _HASH.fullmatch(str(ref.get('content_hash', '')))):
            raise LimRuntimeError('SKILL_METADATA_INVALID', '证据仅接受 ID、版本和 SHA-256 摘要，不接受正文或自由字段', status_code=422)
        safe_refs.append(dict(ref))
    scope = payload.get('business_scope')
    if (not isinstance(scope, dict) or set(scope) != {'domain', 'market_codes'}
            or not isinstance(scope.get('domain'), str) or scope.get('domain') not in BUSINESS_DOMAINS
            or not isinstance(scope.get('market_codes'), list) or not scope['market_codes']
            or len(scope['market_codes']) > 20
            or any(not isinstance(code, str) or not re.fullmatch(r'[A-Z]{2}', code) for code in scope['market_codes'])):
        raise LimRuntimeError('SKILL_METADATA_INVALID', 'business_scope 仅接受受控业务域和国家代码', status_code=422)
    calibration = payload.get('confidence_calibration')
    if (not isinstance(calibration, dict) or set(calibration) - {'method', 'sample_size', 'score', 'dataset_id', 'dataset_version'}
            or ('method' in calibration and (not isinstance(calibration['method'], str)
                or calibration['method'] not in {'human_review', 'golden_dataset'}))):
        raise LimRuntimeError('SKILL_METADATA_INVALID', 'confidence_calibration 字段或方法无效', status_code=422)
    score, sample_size = calibration.get('score'), calibration.get('sample_size')
    if ('score' in calibration and (isinstance(score, bool) or not isinstance(score, (int, float))
            or not math.isfinite(score) or not 0 <= score <= 1)):
        raise LimRuntimeError('SKILL_METADATA_INVALID', '校准分数必须为有限的 0..1 数值', status_code=422)
    if ('sample_size' in calibration and (isinstance(sample_size, bool)
            or not isinstance(sample_size, int) or sample_size < 1)):
        raise LimRuntimeError('SKILL_METADATA_INVALID', '校准样本数必须为正整数', status_code=422)
    for key in ('dataset_id', 'dataset_version'):
        if key in calibration:
            _safe_id(calibration[key], f'confidence_calibration.{key}')
    expiry = payload.get('expiry_policy')
    if not isinstance(expiry, dict) or set(expiry) - {'expires_at', 'no_expiry'}:
        raise LimRuntimeError('SKILL_EXPIRY_POLICY_INVALID', 'expiry_policy 仅接受 expires_at 或 no_expiry', status_code=422)
    if ('no_expiry' in expiry and not isinstance(expiry['no_expiry'], bool)) or (
            'expires_at' in expiry and not isinstance(expiry['expires_at'], str)):
        raise LimRuntimeError('SKILL_EXPIRY_POLICY_INVALID', '失效策略值类型无效', status_code=422)
    display_name = payload.get('display_name')
    if display_name != definition['template_id']:
        raise LimRuntimeError('SKILL_NAME_REQUIRED', 'display_name 必须使用已登记模板 ID', status_code=422)
    return definition, source_event, safe_refs, scope, calibration, expiry


def create_skill_candidate(db, actor, payload: dict) -> LimSkillVersion:
    definition, source_event, evidence_refs, business_scope, calibration, expiry_policy = _validate_candidate_metadata(payload)
    skill_id = payload.get('skill_id')
    version = payload.get('version')
    if not isinstance(skill_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', skill_id):
        raise LimRuntimeError('SKILL_ID_INVALID', 'skill_id 格式无效', status_code=422)
    if not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,31}', version):
        raise LimRuntimeError('SKILL_VERSION_INVALID', 'Skill version 格式无效', status_code=422)
    if not isinstance(payload.get('memory_level'), str) or payload.get('memory_level') not in MEMORY_LEVELS:
        raise LimRuntimeError('SKILL_MEMORY_LEVEL_INVALID', 'memory_level 无效', status_code=422)
    expiry_policy = dict(expiry_policy)
    if 'expires_at' in expiry_policy:
        expires_at = _parse_time(expiry_policy.get('expires_at'))
        if expires_at is None:
            raise LimRuntimeError('SKILL_EXPIRY_POLICY_INVALID', 'expires_at 必须是 ISO 日期时间', status_code=422)
        expiry_policy['expires_at'] = expires_at.replace(tzinfo=timezone.utc).isoformat()
    elif expiry_policy.get('no_expiry') is not True and payload.get('status') == 'ACTIVE':
        raise LimRuntimeError('SKILL_EXPIRY_UNCONFIRMED', '必须设置 expires_at 或显式确认 no_expiry', status_code=422)
    skill = db.scalar(select(LimSkill).where(LimSkill.skill_id == skill_id))
    if skill is None:
        display_name = payload['display_name']
        skill = LimSkill(skill_id=skill_id, display_name=display_name, owner_id=actor.id)
        if not skill.display_name.strip():
            raise LimRuntimeError('SKILL_NAME_REQUIRED', 'Skill 显示名必填', status_code=422)
        db.add(skill)
        db.flush()
    elif skill.owner_id != actor.id:
        raise LimRuntimeError('SKILL_OWNER_MISMATCH', '只有 Skill owner 可以提交新版本', status_code=403)
    if db.scalar(select(LimSkillVersion.id).where(
        LimSkillVersion.skill_id == skill_id, LimSkillVersion.version == version,
    )) is not None:
        raise LimRuntimeError('SKILL_VERSION_IMMUTABLE', '版本已存在；内容变更必须创建新版本', status_code=409)
    row = LimSkillVersion(
        skill_id=skill_id, version=version, memory_level=payload['memory_level'],
        definition=definition,
        source_event=source_event,
        evidence_refs=evidence_refs,
        business_scope=business_scope,
        last_verified_at=None,
        confidence_calibration=calibration,
        expiry_policy=expiry_policy,
        usage_count=0, correction_count=0, status='CANDIDATE', created_by=actor.id,
    )
    db.add(row)
    db.flush()
    record_audit(db, actor, 'lim_skills', skill_id, 'create_candidate',
                 after={'version': version, 'status': 'CANDIDATE', 'runtime_enabled': False})
    return row


def update_skill_candidate(db, actor, row: LimSkillVersion, payload: dict) -> LimSkillVersion:
    row = db.scalar(select(LimSkillVersion).where(LimSkillVersion.id == row.id).with_for_update()
                     .execution_options(populate_existing=True))
    if row is None:
        raise LimRuntimeError('SKILL_VERSION_NOT_FOUND', 'Skill 版本不存在', status_code=404)
    skill = db.scalar(select(LimSkill).where(LimSkill.skill_id == row.skill_id))
    if skill is None or skill.owner_id != actor.id:
        raise LimRuntimeError('SKILL_OWNER_MISMATCH', '只有 Skill owner 可以修改候选版本', status_code=403)
    if row.status != 'CANDIDATE':
        raise LimRuntimeError('SKILL_VERSION_IMMUTABLE', '进入审核后版本内容不可修改；请创建新版本', status_code=409)
    if payload.get('skill_id') != row.skill_id or payload.get('version') != row.version:
        raise LimRuntimeError('SKILL_VERSION_IMMUTABLE', '更新时 skill_id 和 version 必须保持不变', status_code=409)
    if payload.get('memory_level') not in MEMORY_LEVELS:
        raise LimRuntimeError('SKILL_MEMORY_LEVEL_INVALID', 'memory_level 无效', status_code=422)
    definition, source_event, evidence_refs, business_scope, calibration, expiry_policy = _validate_candidate_metadata(payload)
    if 'expires_at' in expiry_policy:
        expires_at = _parse_time(expiry_policy['expires_at'])
        if expires_at is None:
            raise LimRuntimeError('SKILL_EXPIRY_POLICY_INVALID', 'expires_at 必须是 ISO 日期时间', status_code=422)
        expiry_policy['expires_at'] = expires_at.replace(tzinfo=timezone.utc).isoformat()
    before = {'status': row.status, 'version': row.version}
    row.memory_level = payload['memory_level']
    row.definition = definition
    row.source_event = source_event
    row.evidence_refs = evidence_refs
    row.business_scope = business_scope
    row.confidence_calibration = calibration
    row.expiry_policy = expiry_policy
    record_audit(db, actor, 'lim_skills', row.skill_id, 'update_candidate', before=before,
                 after={'status': row.status, 'version': row.version, 'fields': [
                     'memory_level', 'definition', 'source_event', 'evidence_refs', 'business_scope',
                     'confidence_calibration', 'expiry_policy'], 'runtime_enabled': False})
    db.flush()
    return row


def _validate_verified_material(row):
    if not row.source_event.strip() or not row.evidence_refs:
        raise LimRuntimeError('SKILL_VERIFICATION_INCOMPLETE', '验证需要来源事件和至少一条证据引用')
    if not row.business_scope or not row.confidence_calibration:
        raise LimRuntimeError('SKILL_VERIFICATION_INCOMPLETE', '验证需要业务范围和置信校准记录')
    if any(not isinstance(ref, dict) or any(not ref.get(key) for key in ('ref_id', 'source_version', 'content_hash'))
           for ref in row.evidence_refs):
        raise LimRuntimeError('SKILL_VERIFICATION_INCOMPLETE', '证据引用必须包含 ref_id、source_version 和 content_hash')
    calibration = row.confidence_calibration
    score, sample_size = calibration.get('score'), calibration.get('sample_size')
    if (calibration.get('method') not in {'human_review', 'golden_dataset'}
            or isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1
            or isinstance(sample_size, bool) or not isinstance(sample_size, int) or sample_size < 1):
        raise LimRuntimeError('SKILL_VERIFICATION_INCOMPLETE', '置信校准需要 method、有效 score 和正数 sample_size')


def _validate_expiry(row):
    expiry = row.expiry_policy or {}
    expires_at = _parse_time(expiry.get('expires_at'))
    if expires_at is not None:
        if expires_at <= datetime.now(timezone.utc).replace(tzinfo=None):
            raise LimRuntimeError('SKILL_EXPIRED', '已过期的 Skill 版本不能激活')
        return
    if expiry.get('no_expiry') is not True:
        raise LimRuntimeError('SKILL_EXPIRY_UNCONFIRMED', '必须设置 expires_at 或显式确认 no_expiry')


def transition_skill_version(db, actor, row: LimSkillVersion, target: str, *, rationale: str):
    row = db.scalar(select(LimSkillVersion).where(LimSkillVersion.id == row.id).with_for_update()
                     .execution_options(populate_existing=True))
    if row is None:
        raise LimRuntimeError('SKILL_VERSION_NOT_FOUND', 'Skill 版本不存在', status_code=404)
    target = str(target).upper()
    if not isinstance(rationale, str) or not rationale.strip():
        raise LimRuntimeError('SKILL_TRANSITION_RATIONALE_REQUIRED', '生命周期变更必须填写审核理由', status_code=422)
    if target not in TRANSITIONS.get(row.status, set()):
        raise LimRuntimeError('SKILL_TRANSITION_INVALID', f'不允许从 {row.status} 迁移到 {target}')
    if target == 'VERIFIED':
        _validate_verified_material(row)
    if target == 'ACTIVE':
        _validate_expiry(row)
        db.scalar(select(LimSkill).where(LimSkill.skill_id == row.skill_id).with_for_update())
        active = db.scalar(select(LimSkillVersion).where(
            LimSkillVersion.skill_id == row.skill_id, LimSkillVersion.status == 'ACTIVE',
        ).with_for_update())
        if active is not None and active.id != row.id:
            previous = active.status
            active.status = 'DEGRADED'
            active.transitioned_at = m.now()
            record_audit(db, actor, 'lim_skills', active.skill_id, 'supersede_active_version',
                         before={'version': active.version, 'status': previous},
                         after={'version': active.version, 'status': 'DEGRADED',
                                'superseded_by': row.version, 'runtime_enabled': False})
            db.flush([active])
    before = row.status
    row.status = target
    row.transitioned_at = m.now()
    if target in {'UNDER_REVIEW', 'VERIFIED'}:
        row.reviewed_by = actor.id
    if target == 'VERIFIED':
        row.last_verified_at = m.now()
    if target == 'ACTIVE':
        row.activated_by = actor.id
    safe_rationale = str(sanitize_trace_value(rationale.strip()))[:500]
    record_audit(db, actor, 'lim_skills', row.skill_id, 'transition',
                 before={'version': row.version, 'status': before},
                 after={'version': row.version, 'status': target, 'rationale': safe_rationale,
                        'runtime_enabled': False})
    db.flush()
    return row


def skill_version_json(row: LimSkillVersion, skill: LimSkill | None = None) -> dict:
    return {
        'skill_id': row.skill_id, 'version': row.version,
        'display_name': skill.display_name if skill else row.skill_id,
        'owner_id': skill.owner_id if skill else None,
        'memory_level': row.memory_level, 'definition': row.definition,
        'source_event': row.source_event, 'evidence_refs': row.evidence_refs,
        'business_scope': row.business_scope, 'last_verified_at': row.last_verified_at,
        'confidence_calibration': row.confidence_calibration,
        'usage_count': row.usage_count, 'correction_count': row.correction_count,
        'expiry_policy': row.expiry_policy, 'status': row.status,
        'created_by': row.created_by, 'reviewed_by': row.reviewed_by,
        'activated_by': row.activated_by, 'created_at': row.created_at,
        'transitioned_at': row.transitioned_at, 'runtime_enabled': False,
    }
