"""Small helpers duplicated across several modules.

Centralised here so the same permission check and money formatting live in
exactly one place (previously copied into assistant.py, assistant_catalog.py,
business_evidence_tools.py, agent_generation.py, profit_reconciliation.py and
purchase_amendments.py).
"""
from decimal import Decimal, ROUND_HALF_UP

from .security import role_for

CENT = Decimal('0.01')


def allowed(db, user, permission) -> bool:
    """True if the user's role is admin or grants ``permission``.

    None-safe: a missing role yields False rather than raising.
    """
    role = role_for(db, user)
    return bool(role and (role.code == 'admin' or permission in (role.permissions or [])))


def money(value) -> str:
    """Format a number/Decimal as a fixed 2-decimal string (half-up rounding)."""
    return str(Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP))
