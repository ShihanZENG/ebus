"""OMS sales orders, items, payments and after-sales."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def identity():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def field(name, type_, **kwargs):
    return sa.Column(name, type_, nullable=False, **kwargs)


def fk(name, target, nullable=False):
    return sa.Column(name, sa.String(36), sa.ForeignKey(target, ondelete='RESTRICT'),
                     nullable=nullable)


def money(name):
    return sa.Column(name, sa.Numeric(12, 2), nullable=False, server_default='0')


def upgrade():
    op.create_table('sales_orders', *identity(),
                    fk('shop_id', 'shops.id'),
                    field('source_channel', sa.String(80)),
                    field('source_order_no', sa.String(120)),
                    field('status', sa.String(20)),
                    fk('currency_id', 'dictionaries.id'),
                    money('total_amount'), money('discount_amount'), money('grand_total'),
                    fk('warehouse_id', 'warehouses.id', nullable=True),
                    field('customer_name', sa.String(120), server_default=''),
                    field('customer_contact', sa.String(200), server_default=''),
                    field('remark', sa.String(1000), server_default=''),
                    field('cancel_reason', sa.String(500), server_default=''),
                    sa.UniqueConstraint('shop_id', 'source_channel', 'source_order_no',
                                       name='uq_sales_order_source'))
    op.create_index('ix_sales_orders_shop_id', 'sales_orders', ['shop_id'])
    op.create_index('ix_sales_orders_status', 'sales_orders', ['status'])

    op.create_table('sales_order_items', *identity(),
                    sa.Column('order_id', sa.String(36), sa.ForeignKey('sales_orders.id', ondelete='CASCADE'), nullable=False),
                    fk('sku_id', 'skus.id'),
                    field('sku_code_snapshot', sa.String(64)),
                    field('sku_name_snapshot', sa.String(120)),
                    field('quantity', sa.Integer()),
                    money('unit_price'), money('discount_amount'), money('line_total'))
    op.create_index('ix_sales_order_items_order_id', 'sales_order_items', ['order_id'])

    op.create_table('payment_records', *identity(),
                    fk('order_id', 'sales_orders.id'),
                    money('amount'),
                    fk('currency_id', 'dictionaries.id'),
                    field('method', sa.String(40), server_default='manual'),
                    field('source', sa.String(40), server_default='manual'),
                    field('paid_at', sa.DateTime()),
                    field('remark', sa.String(500), server_default=''))
    op.create_index('ix_payment_records_order_id', 'payment_records', ['order_id'])

    op.create_table('after_sales', *identity(),
                    fk('order_id', 'sales_orders.id'),
                    field('type', sa.String(20)),
                    field('reason', sa.String(500)),
                    field('status', sa.String(20), server_default='pending'),
                    field('quantity', sa.Integer(), server_default='0'),
                    money('amount'),
                    field('remark', sa.String(500), server_default=''))
    op.create_index('ix_after_sales_order_id', 'after_sales', ['order_id'])


def downgrade():
    op.drop_table('after_sales')
    op.drop_table('payment_records')
    op.drop_table('sales_order_items')
    op.drop_table('sales_orders')
