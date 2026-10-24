"""Add storefront checkout completion: test payments, promo codes, customer addresses, profile fields and after-sales."""
from alembic import op
import sqlalchemy as sa

revision = '0042'
down_revision = '0041'
branch_labels = None
depends_on = None


def record_columns():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def upgrade():
    op.create_table('storefront_promos', *record_columns(),
        sa.Column('site_id', sa.String(36), sa.ForeignKey('storefront_sites.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('code', sa.String(40), nullable=False),
        sa.Column('kind', sa.String(10), nullable=False),
        sa.Column('value', sa.Numeric(12, 2), nullable=False),
        sa.Column('min_subtotal', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('max_discount', sa.Numeric(12, 2), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('max_uses', sa.Integer(), nullable=True),
        sa.Column('used_count', sa.Integer(), nullable=False, server_default='0'),
        sa.UniqueConstraint('site_id', 'code', name='uq_storefront_promo_code'),
        sa.CheckConstraint("kind IN ('percent', 'fixed')", name='ck_storefront_promo_kind'),
        sa.CheckConstraint('value >= 0', name='ck_storefront_promo_value_nonnegative'))
    op.create_index('ix_storefront_promos_site_id', 'storefront_promos', ['site_id'])
    op.create_table('storefront_payments', *record_columns(),
        sa.Column('site_id', sa.String(36), sa.ForeignKey('storefront_sites.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('sales_orders.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('public_ref', sa.String(40), nullable=False, unique=True),
        sa.Column('method', sa.String(40), nullable=False),
        sa.Column('scenario', sa.String(20), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('provider_ref', sa.String(64), nullable=False),
        sa.UniqueConstraint('order_id', 'method', 'scenario', name='uq_storefront_payment_attempt'),
        sa.CheckConstraint('amount >= 0', name='ck_storefront_payment_amount_nonnegative'))
    op.create_index('ix_storefront_payments_site_id', 'storefront_payments', ['site_id'])
    op.create_index('ix_storefront_payments_order_id', 'storefront_payments', ['order_id'])
    op.create_table('storefront_customer_addresses', *record_columns(),
        sa.Column('customer_id', sa.String(36), sa.ForeignKey('storefront_customers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('phone', sa.String(40), nullable=False, server_default=''),
        sa.Column('line1', sa.String(200), nullable=False),
        sa.Column('line2', sa.String(200), nullable=False, server_default=''),
        sa.Column('city', sa.String(100), nullable=False),
        sa.Column('region', sa.String(100), nullable=False, server_default=''),
        sa.Column('postcode', sa.String(10), nullable=False),
        sa.Column('country', sa.String(2), nullable=False, server_default='GB'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.create_index('ix_storefront_customer_addresses_customer_id', 'storefront_customer_addresses', ['customer_id'])
    op.create_table('storefront_after_sales', *record_columns(),
        sa.Column('site_id', sa.String(36), sa.ForeignKey('storefront_sites.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('sales_orders.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('customer_id', sa.String(36), sa.ForeignKey('storefront_customers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('public_ref', sa.String(40), nullable=False, unique=True),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('items', sa.JSON(), nullable=False),
        sa.Column('reason', sa.String(200), nullable=False),
        sa.Column('message', sa.Text(), nullable=False, server_default=''),
        sa.Column('status', sa.String(20), nullable=False, server_default='submitted'),
        sa.Column('note', sa.Text(), nullable=False, server_default=''))
    op.create_index('ix_storefront_after_sales_site_id', 'storefront_after_sales', ['site_id'])
    op.create_index('ix_storefront_after_sales_order_id', 'storefront_after_sales', ['order_id'])
    op.create_index('ix_storefront_after_sales_customer_id', 'storefront_after_sales', ['customer_id'])
    op.create_index('ix_storefront_after_sales_status', 'storefront_after_sales', ['status'])
    op.add_column('storefront_customers', sa.Column('display_name', sa.String(120), nullable=False, server_default=''))
    op.add_column('storefront_customers', sa.Column('phone', sa.String(40), nullable=False, server_default=''))
    op.add_column('storefront_customers', sa.Column('preferences', sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column('storefront_order_meta', sa.Column('promo_code', sa.String(40), nullable=False, server_default=''))
    op.add_column('storefront_order_meta', sa.Column('discount_amount', sa.Numeric(12, 2), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('storefront_order_meta', 'discount_amount')
    op.drop_column('storefront_order_meta', 'promo_code')
    op.drop_column('storefront_customers', 'preferences')
    op.drop_column('storefront_customers', 'phone')
    op.drop_column('storefront_customers', 'display_name')
    op.drop_table('storefront_after_sales')
    op.drop_table('storefront_customer_addresses')
    op.drop_table('storefront_payments')
    op.drop_index('ix_storefront_promos_site_id', table_name='storefront_promos')
    op.drop_table('storefront_promos')
