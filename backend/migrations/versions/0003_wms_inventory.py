"""WMS inventory balances, transactions, inbound and shipment orders."""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
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


def upgrade():
    op.create_table('inventory_balances', *identity(),
                    fk('warehouse_id', 'warehouses.id'),
                    fk('sku_id', 'skus.id'),
                    field('on_hand_qty', sa.Integer(), server_default='0'),
                    field('reserved_qty', sa.Integer(), server_default='0'),
                    sa.UniqueConstraint('warehouse_id', 'sku_id', name='uq_inventory_wh_sku'))
    op.create_index('ix_inventory_balances_warehouse_id', 'inventory_balances', ['warehouse_id'])
    op.create_index('ix_inventory_balances_sku_id', 'inventory_balances', ['sku_id'])

    op.create_table('inventory_transactions', *identity(),
                    fk('warehouse_id', 'warehouses.id'),
                    fk('sku_id', 'skus.id'),
                    field('txn_type', sa.String(20)),
                    field('on_hand_delta', sa.Integer(), server_default='0'),
                    field('reserved_delta', sa.Integer(), server_default='0'),
                    sa.Column('order_id', sa.String(36),
                              sa.ForeignKey('sales_orders.id', ondelete='SET NULL'), nullable=True),
                    field('reference_no', sa.String(64), server_default=''),
                    field('remark', sa.String(500), server_default=''))
    op.create_index('ix_inventory_transactions_warehouse_id', 'inventory_transactions', ['warehouse_id'])
    op.create_index('ix_inventory_transactions_sku_id', 'inventory_transactions', ['sku_id'])

    op.create_table('inbound_orders', *identity(),
                    fk('warehouse_id', 'warehouses.id'),
                    sa.Column('supplier_id', sa.String(36),
                              sa.ForeignKey('suppliers.id', ondelete='RESTRICT'), nullable=True),
                    field('status', sa.String(20), server_default='confirmed'),
                    field('inbound_at', sa.DateTime()),
                    field('remark', sa.String(500), server_default=''))
    op.create_index('ix_inbound_orders_warehouse_id', 'inbound_orders', ['warehouse_id'])

    op.create_table('inbound_order_items', *identity(),
                    sa.Column('inbound_id', sa.String(36),
                              sa.ForeignKey('inbound_orders.id', ondelete='CASCADE'), nullable=False),
                    fk('sku_id', 'skus.id'),
                    field('quantity', sa.Integer()))
    op.create_index('ix_inbound_order_items_inbound_id', 'inbound_order_items', ['inbound_id'])

    op.create_table('shipment_orders', *identity(),
                    sa.Column('order_id', sa.String(36),
                              sa.ForeignKey('sales_orders.id', ondelete='RESTRICT'), nullable=False, unique=True),
                    fk('warehouse_id', 'warehouses.id'),
                    field('status', sa.String(20), server_default='picking'),
                    field('tracking_no', sa.String(120), server_default=''),
                    sa.Column('shipped_at', sa.DateTime(), nullable=True),
                    field('remark', sa.String(500), server_default=''))

    op.create_table('shipment_order_items', *identity(),
                    sa.Column('shipment_id', sa.String(36),
                              sa.ForeignKey('shipment_orders.id', ondelete='CASCADE'), nullable=False),
                    fk('sku_id', 'skus.id'),
                    field('quantity', sa.Integer()))
    op.create_index('ix_shipment_order_items_shipment_id', 'shipment_order_items', ['shipment_id'])


def downgrade():
    op.drop_table('shipment_order_items')
    op.drop_table('shipment_orders')
    op.drop_table('inbound_order_items')
    op.drop_table('inbound_orders')
    op.drop_table('inventory_transactions')
    op.drop_table('inventory_balances')
