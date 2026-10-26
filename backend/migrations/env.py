from alembic import context
from app.config import database_url
from app.db import build_engine
from app.models import Base
from app.storefront import models as storefront_models  # noqa: F401
from app import ads_reports, business_analysis  # noqa: F401
from app import agent_generation  # noqa: F401
from app import lim_models  # noqa: F401 - register LIM tables
from app import decision_models  # noqa: F401 - register business risk and strategy tables
from app import sales_coverage_evidence  # noqa: F401
from app import listing_agent  # noqa: F401
from app import purchase_plans, purchase_amendments, supplier_quotes, fba, listings, customer_tickets, purchase_agent, supply_agent  # noqa: F401 - 注册业务表到 metadata

if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = build_engine()
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
