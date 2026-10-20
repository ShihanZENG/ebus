"""ERP evidence based supply planning and model trace."""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def records():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def fk(name, target, nullable=False, delete='RESTRICT'):
    return sa.Column(name, sa.String(36), sa.ForeignKey(target, ondelete=delete), nullable=nullable)


def upgrade():
    op.add_column('sales_orders', sa.Column('ordered_at', sa.DateTime(), nullable=True))
    op.add_column('fba_plans', sa.Column('expected_available_at', sa.DateTime(), nullable=True))
    op.create_table('purchase_agent_profiles', *records(), sa.Column('name', sa.String(120), nullable=False),
        fk('sku_id', 'skus.id'), fk('shop_id', 'shops.id'), fk('warehouse_id', 'warehouses.id'),
        fk('destination_id', 'warehouses.id'), fk('supplier_id', 'suppliers.id'), sa.Column('config', sa.JSON(), nullable=False))
    for field in ['sku_id', 'shop_id']:
        op.create_index('ix_purchase_agent_profiles_' + field, 'purchase_agent_profiles', [field])
    op.create_table('purchase_agent_supply_drafts', *records(),
        sa.Column('draft_no', sa.String(64), nullable=False, unique=True),
        fk('profile_id', 'purchase_agent_profiles.id'), fk('run_id', 'agent_runs.id'),
        sa.Column('status', sa.String(24), nullable=False), sa.Column('business_date', sa.Date(), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False), sa.Column('calculation', sa.JSON(), nullable=False),
        sa.Column('evidence_hash', sa.String(64), nullable=False), sa.Column('idempotency_key', sa.String(64), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False), fk('requested_by', 'users.id'),
        fk('approved_by', 'users.id', nullable=True, delete='SET NULL'), sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('generated_records', sa.JSON(), nullable=False), sa.Column('reason', sa.String(500), nullable=False))
    for field in ['profile_id', 'status']:
        op.create_index('ix_purchase_agent_supply_drafts_' + field, 'purchase_agent_supply_drafts', [field])
    op.create_table('purchase_agent_chats', *records(), fk('actor_id', 'users.id'),
        sa.Column('profile_ids', sa.JSON(), nullable=False), sa.Column('message', sa.String(4000), nullable=False),
        sa.Column('model', sa.String(120), nullable=False), sa.Column('status', sa.String(24), nullable=False),
        sa.Column('trace', sa.JSON(), nullable=False), sa.Column('result', sa.JSON(), nullable=False))
    op.create_index('ix_purchase_agent_chats_actor_id', 'purchase_agent_chats', ['actor_id'])


def downgrade():
    op.drop_table('purchase_agent_chats')
    op.drop_table('purchase_agent_supply_drafts')
    op.drop_table('purchase_agent_profiles')
    op.drop_column('fba_plans', 'expected_available_at')
    op.drop_column('sales_orders', 'ordered_at')
