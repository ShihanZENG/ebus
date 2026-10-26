"""Persist ERP-owned OMS handoff events."""

from alembic import op
import sqlalchemy as sa

revision = '0048'
down_revision = '0047'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('payment_records') as batch:
        batch.add_column(sa.Column('external_transaction_id', sa.String(120), nullable=True))
        batch.create_unique_constraint('uq_payment_records_external_transaction_id', ['external_transaction_id'])
    op.create_table(
        'oms_outbox_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('sales_orders.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('contract_version', sa.String(16), nullable=False),
        sa.Column('idempotency_key', sa.String(120), nullable=False, unique=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.String(500), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(), nullable=True),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_oms_outbox_events_order_id', 'oms_outbox_events', ['order_id'])
    op.create_index('ix_oms_outbox_events_status', 'oms_outbox_events', ['status'])
    op.create_table(
        'storefront_holds',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('sales_orders.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('warehouse_id', sa.String(36), sa.ForeignKey('warehouses.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('sku_id', sa.String(36), sa.ForeignKey('skus.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('order_id', 'sku_id', name='uq_storefront_hold_order_sku'),
        sa.CheckConstraint('quantity > 0', name='ck_storefront_hold_quantity'),
    )
    op.create_index('ix_storefront_holds_order_id', 'storefront_holds', ['order_id'])
    op.create_index('ix_storefront_holds_status', 'storefront_holds', ['status'])
    op.create_index('ix_storefront_holds_expires_at', 'storefront_holds', ['expires_at'])


def downgrade():
    op.drop_table('storefront_holds')
    op.drop_table('oms_outbox_events')
    with op.batch_alter_table('payment_records') as batch:
        batch.drop_constraint('uq_payment_records_external_transaction_id', type_='unique')
        batch.drop_column('external_transaction_id')
