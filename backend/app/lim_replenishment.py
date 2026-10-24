"""Read-only adapter for the existing deterministic replenishment evidence service."""
from datetime import date

from .security import role_for
from .supply_agent import calculate_supply, collect_evidence, profile_get, public_evidence


def read_replenishment_evidence(db, user, arguments: dict) -> dict:
    role = role_for(db, user)
    if role is None or (role.code != 'admin' and 'purchase_agent:read' not in role.permissions):
        # The LIM surface requires assistant:read. The adapter also enforces the
        # purchase-domain permission, so that general AI access cannot widen ERP access.
        raise ValueError('当前账号无补货证据读取权限')
    business_date = date.fromisoformat(arguments['business_date'])
    profile = profile_get(db, user, arguments['profile_id'])
    evidence = collect_evidence(db, user, profile, business_date)
    calculation = calculate_supply(evidence) if not evidence.get('issues') else {
        'status': 'NOT_RUN', 'reason': 'evidence_blocked',
    }
    return {
        'source': 'purchase_agent_profiles',
        'profile_id': profile.id,
        'business_date': business_date.isoformat(),
        'evidence_hash': evidence['evidence_hash'],
        'blockers': evidence.get('issues', []),
        'evidence': public_evidence(evidence),
        'calculation': calculation,
    }
