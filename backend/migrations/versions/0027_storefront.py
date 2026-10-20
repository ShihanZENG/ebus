"""Retail publication and isolated guest checkout metadata."""
from alembic import op
import sqlalchemy as sa

revision = '0027'
down_revision = '0026'
branch_labels = None
depends_on = None


def record():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def fk(name, table):
    return sa.Column(name, sa.String(36), sa.ForeignKey(table + '.id', ondelete='RESTRICT'), nullable=False)


def upgrade():
    op.create_table('storefront_sites', *record(), sa.Column('code', sa.String(64), nullable=False, unique=True),
        fk('shop_id', 'shops'), fk('warehouse_id', 'warehouses'),
        sa.Column('brand_name', sa.String(120), nullable=False),
        sa.Column('company_name', sa.String(200), nullable=False),
        sa.Column('company_address', sa.String(500), nullable=False),
        sa.Column('contact_email', sa.String(254), nullable=False))
    op.create_table('storefront_products', *record(), fk('site_id', 'storefront_sites'), fk('product_id', 'products'),
        sa.Column('slug', sa.String(80), nullable=False), sa.Column('title', sa.String(120), nullable=False),
        sa.Column('description', sa.String(2000), nullable=False), sa.Column('category', sa.String(40), nullable=False),
        sa.Column('image_url', sa.String(300), nullable=False), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False), sa.UniqueConstraint('site_id', 'slug', name='uq_storefront_product_slug'))
    op.create_table('storefront_variants', *record(), fk('site_id', 'storefront_sites'),
        fk('product_id', 'storefront_products'), fk('sku_id', 'skus'),
        sa.Column('color', sa.String(60), nullable=False), sa.Column('size', sa.String(30), nullable=False),
        sa.Column('price', sa.Numeric(12, 2), nullable=False),
        sa.UniqueConstraint('site_id', 'sku_id', name='uq_storefront_variant_sku'),
        sa.CheckConstraint('price > 0', name='ck_storefront_price_positive'))
    op.create_table('storefront_order_meta', *record(), fk('site_id', 'storefront_sites'), fk('order_id', 'sales_orders'),
        sa.Column('public_id', sa.String(64), nullable=False, unique=True),
        sa.Column('access_hash', sa.String(64), nullable=False), sa.Column('address', sa.JSON(), nullable=False),
        sa.Column('items', sa.JSON(), nullable=False), sa.Column('grand_total', sa.Numeric(12, 2), nullable=False),
        sa.UniqueConstraint('order_id'))
    op.create_table('storefront_submissions', *record(), fk('site_id', 'storefront_sites'), fk('order_id', 'sales_orders'),
        sa.Column('key', sa.String(128), nullable=False), sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('recovery_hash', sa.String(64), nullable=False),
        sa.UniqueConstraint('site_id', 'key', name='uq_storefront_submission_key'))


def downgrade():
    for table in ('storefront_submissions', 'storefront_order_meta', 'storefront_variants', 'storefront_products', 'storefront_sites'):
        op.drop_table(table)
