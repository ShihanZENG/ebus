"""purchase agent runs tool calls drafts"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('purchase_agent_drafts',
    sa.Column('draft_no', sa.String(length=40), nullable=False),
    sa.Column('sku_id', sa.String(length=36), nullable=False),
    sa.Column('sku_code_snapshot', sa.String(length=64), nullable=False),
    sa.Column('sku_name_snapshot', sa.String(length=120), nullable=False),
    sa.Column('supplier_id', sa.String(length=36), nullable=False),
    sa.Column('shop_id', sa.String(length=36), nullable=True),
    sa.Column('warehouse_id', sa.String(length=36), nullable=False),
    sa.Column('suggested_qty', sa.Integer(), nullable=False),
    sa.Column('target_stock', sa.Integer(), nullable=False),
    sa.Column('net_gap', sa.Integer(), nullable=False),
    sa.Column('moq', sa.Integer(), nullable=False),
    sa.Column('case_pack', sa.Integer(), nullable=False),
    sa.Column('unit_price', sa.Numeric(12, 2), nullable=False),
    sa.Column('total_amount', sa.Numeric(12, 2), nullable=False),
    sa.Column('currency_id', sa.String(length=36), nullable=True),
    sa.Column('expected_arrival_date', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.Column('calculation', sa.JSON(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=255), nullable=False),
    sa.Column('rule_version', sa.String(length=20), nullable=False),
    sa.Column('requested_by', sa.String(length=36), nullable=False),
    sa.Column('approved_by', sa.String(length=36), nullable=True),
    sa.Column('approved_at', sa.DateTime(), nullable=True),
    sa.Column('plan_id', sa.String(length=36), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['currency_id'], ['dictionaries.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['plan_id'], ['purchase_plans.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['sku_id'], ['skus.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('draft_no')
    )
    op.create_index(op.f('ix_purchase_agent_drafts_idempotency_key'), 'purchase_agent_drafts', ['idempotency_key'], unique=True)
    op.create_index(op.f('ix_purchase_agent_drafts_shop_id'), 'purchase_agent_drafts', ['shop_id'], unique=False)
    op.create_index(op.f('ix_purchase_agent_drafts_sku_id'), 'purchase_agent_drafts', ['sku_id'], unique=False)
    op.create_index(op.f('ix_purchase_agent_drafts_status'), 'purchase_agent_drafts', ['status'], unique=False)
    op.create_index(op.f('ix_purchase_agent_drafts_supplier_id'), 'purchase_agent_drafts', ['supplier_id'], unique=False)
    op.create_index(op.f('ix_purchase_agent_drafts_warehouse_id'), 'purchase_agent_drafts', ['warehouse_id'], unique=False)
    op.create_table('agent_runs',
    sa.Column('case_id', sa.String(length=64), nullable=False),
    sa.Column('sku_id', sa.String(length=36), nullable=False),
    sa.Column('shop_id', sa.String(length=36), nullable=True),
    sa.Column('warehouse_id', sa.String(length=36), nullable=False),
    sa.Column('as_of', sa.DateTime(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('request_payload', sa.JSON(), nullable=False),
    sa.Column('result_payload', sa.JSON(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=255), nullable=False),
    sa.Column('draft_id', sa.String(length=36), nullable=True),
    sa.Column('error_message', sa.String(length=500), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['draft_id'], ['purchase_agent_drafts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['sku_id'], ['skus.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_runs_case_id'), 'agent_runs', ['case_id'], unique=False)
    op.create_index(op.f('ix_agent_runs_shop_id'), 'agent_runs', ['shop_id'], unique=False)
    op.create_index(op.f('ix_agent_runs_sku_id'), 'agent_runs', ['sku_id'], unique=False)
    op.create_index(op.f('ix_agent_runs_status'), 'agent_runs', ['status'], unique=False)
    op.create_index(op.f('ix_agent_runs_warehouse_id'), 'agent_runs', ['warehouse_id'], unique=False)
    op.create_table('agent_tool_calls',
    sa.Column('run_id', sa.String(length=36), nullable=False),
    sa.Column('tool', sa.String(length=64), nullable=False),
    sa.Column('params', sa.JSON(), nullable=False),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.Column('snapshot_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('elapsed_ms', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_tool_calls_run_id'), 'agent_tool_calls', ['run_id'], unique=False)
    op.create_index(op.f('ix_agent_tool_calls_tool'), 'agent_tool_calls', ['tool'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_agent_tool_calls_tool'), table_name='agent_tool_calls')
    op.drop_index(op.f('ix_agent_tool_calls_run_id'), table_name='agent_tool_calls')
    op.drop_table('agent_tool_calls')
    op.drop_index(op.f('ix_agent_runs_warehouse_id'), table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_status'), table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_sku_id'), table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_shop_id'), table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_case_id'), table_name='agent_runs')
    op.drop_table('agent_runs')
    op.drop_index(op.f('ix_purchase_agent_drafts_warehouse_id'), table_name='purchase_agent_drafts')
    op.drop_index(op.f('ix_purchase_agent_drafts_supplier_id'), table_name='purchase_agent_drafts')
    op.drop_index(op.f('ix_purchase_agent_drafts_status'), table_name='purchase_agent_drafts')
    op.drop_index(op.f('ix_purchase_agent_drafts_sku_id'), table_name='purchase_agent_drafts')
    op.drop_index(op.f('ix_purchase_agent_drafts_shop_id'), table_name='purchase_agent_drafts')
    op.drop_index(op.f('ix_purchase_agent_drafts_idempotency_key'), table_name='purchase_agent_drafts')
    op.drop_table('purchase_agent_drafts')
