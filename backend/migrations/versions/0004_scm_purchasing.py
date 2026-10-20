"""SCM supplier SKUs, purchase orders, receipts and replenishment suggestions."""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def identity():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def field(name, type_, **kwargs):
    return sa.Column(name, type_, nullable=False, **kwargs)


def fk(name, target, nullable=False, ondelete='RESTRICT'):
    return sa.Column(name, sa.String(36), sa.ForeignKey(target, ondelete=ondelete), nullable=nullable)


def money(name):
    return sa.Column(name, sa.Numeric(12, 2), nullable=False, server_default='0')


def upgrade():
    op.create_table('supplier_skus', *identity(),
                    fk('supplier_id', 'suppliers.id'),
                    fk('sku_id', 'skus.id'),
                    money('supply_price'),
                    field('lead_time_days', sa.Integer(), server_default='7'),
                    field('is_active', sa.Boolean(), server_default=sa.text('true')),
                    sa.UniqueConstraint('supplier_id', 'sku_id', name='uq_supplier_sku'))
    op.create_index('ix_supplier_skus_supplier_id', 'supplier_skus', ['supplier_id'])
    op.create_index('ix_supplier_skus_sku_id', 'supplier_skus', ['sku_id'])

    op.create_table('purchase_orders', *identity(),
                    field('po_no', sa.String(64), unique=True),
                    fk('supplier_id', 'suppliers.id'),
                    fk('warehouse_id', 'warehouses.id'),
                    field('status', sa.String(20), server_default='draft'),
                    money('total_amount'),
                    sa.Column('expected_arrival_date', sa.DateTime(), nullable=True),
                    field('remark', sa.String(500), server_default=''))
    op.create_index('ix_purchase_orders_supplier_id', 'purchase_orders', ['supplier_id'])
    op.create_index('ix_purchase_orders_status', 'purchase_orders', ['status'])

    op.create_table('purchase_order_items', *identity(),
                    sa.Column('po_id', sa.String(36),
                              sa.ForeignKey('purchase_orders.id', ondelete='CASCADE'), nullable=False),
                    fk('sku_id', 'skus.id'),
                    field('sku_code_snapshot', sa.String(64)),
                    field('sku_name_snapshot', sa.String(120)),
                    field('quantity_ordered', sa.Integer()),
                    field('quantity_received', sa.Integer(), server_default='0'),
                    money('unit_price'))
    op.create_index('ix_purchase_order_items_po_id', 'purchase_order_items', ['po_id'])

    op.create_table('purchase_receipts', *identity(),
                    field('receipt_no', sa.String(64), unique=True),
                    fk('po_id', 'purchase_orders.id'),
                    field('received_at', sa.DateTime()),
                    field('remark', sa.String(500), server_default=''))
    op.create_index('ix_purchase_receipts_po_id', 'purchase_receipts', ['po_id'])

    op.create_table('purchase_receipt_items', *identity(),
                    sa.Column('receipt_id', sa.String(36),
                              sa.ForeignKey('purchase_receipts.id', ondelete='CASCADE'), nullable=False),
                    fk('po_item_id', 'purchase_order_items.id'),
                    fk('sku_id', 'skus.id'),
                    field('quantity_accepted', sa.Integer(), server_default='0'),
                    field('quantity_rejected', sa.Integer(), server_default='0'))
    op.create_index('ix_purchase_receipt_items_receipt_id', 'purchase_receipt_items', ['receipt_id'])

    op.create_table('replenishment_suggestions', *identity(),
                    fk('sku_id', 'skus.id'),
                    fk('warehouse_id', 'warehouses.id'),
                    sa.Column('supplier_id', sa.String(36),
                              sa.ForeignKey('suppliers.id', ondelete='RESTRICT'), nullable=True),
                    field('suggested_qty', sa.Integer(), server_default='0'),
                    field('safety_stock', sa.Integer(), server_default='0'),
                    field('lead_time_days', sa.Integer(), server_default='7'),
                    sa.Column('avg_daily_sales', sa.Numeric(10, 2), nullable=False, server_default='0'),
                    field('formula_inputs', sa.JSON()),
                    field('status', sa.String(20), server_default='pending'),
                    field('reason', sa.String(500), server_default=''),
                    sa.Column('po_id', sa.String(36),
                              sa.ForeignKey('purchase_orders.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_replenishment_suggestions_sku_id', 'replenishment_suggestions', ['sku_id'])


def downgrade():
    op.drop_table('replenishment_suggestions')
    op.drop_table('purchase_receipt_items')
    op.drop_table('purchase_receipts')
    op.drop_table('purchase_order_items')
    op.drop_table('purchase_orders')
    op.drop_table('supplier_skus')
