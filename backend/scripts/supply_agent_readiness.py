"""只读检查本地上线数据；不输出凭据、客户信息、不补造业务资料。"""
import json
import sys
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select, func, text
from app.db import build_engine, sessions
from app import models as m
from app.supplier_quotes import SupplierQuote
from app.fba import FbaPlan
from app.supply_agent import SupplyProfile
from app.supply_agent_llm import llm_config


def report():
    with sessions(build_engine())() as db:
        base, key, model = llm_config()
        value = {'checked_at_utc': m.now().isoformat(), 'database_revision': db.execute(text('select version_num from alembic_version')).scalar(),
            'model_configured': bool(base and key and model), 'model_name': model or None,
            'active_skus': db.scalar(select(func.count()).select_from(m.SKU).where(m.SKU.is_active.is_(True))),
            'orders_by_status': [[s, n] for s, n in db.execute(select(m.SalesOrder.status, func.count()).group_by(m.SalesOrder.status))],
            'order_created_range': [str(x) if x else None for x in db.execute(select(func.min(m.SalesOrder.created_at), func.max(m.SalesOrder.created_at))).one()],
            'orders_missing_ordered_at': db.scalar(select(func.count()).select_from(m.SalesOrder).where(m.SalesOrder.ordered_at.is_(None))),
            'accepted_valid_quotes': db.scalar(select(func.count()).select_from(SupplierQuote).where(SupplierQuote.status == 'accepted', SupplierQuote.valid_until >= m.now().date())),
            'fba_without_eta': db.scalar(select(func.count()).select_from(FbaPlan).where(FbaPlan.status.in_(['submitted', 'approved', 'shipped']), FbaPlan.expected_available_at.is_(None))),
            'supply_profile_count': db.scalar(select(func.count()).select_from(SupplyProfile))}
        return value


if __name__ == '__main__':
    result = report()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    out = Path(__file__).resolve().parents[2] / 'outputs' / 'purchase-agent-readiness.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
