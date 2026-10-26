"""Add storefront campaigns: promotions and themed product collections."""
from alembic import op
import sqlalchemy as sa

revision = '0045'
down_revision = '0044'
branch_labels = None
depends_on = None


def record_columns():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def upgrade():
    op.create_table('storefront_campaigns', *record_columns(),
        sa.Column('site_id', sa.String(36), sa.ForeignKey('storefront_sites.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('slug', sa.String(80), nullable=False),
        sa.Column('title', sa.String(120), nullable=False),
        sa.Column('subtitle', sa.String(200), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('kind', sa.String(20), nullable=False, server_default='promotion'),
        sa.Column('image_url', sa.String(300), nullable=False, server_default=''),
        sa.Column('promo_code', sa.String(40), nullable=False, server_default=''),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('starts_at', sa.DateTime(), nullable=True),
        sa.Column('ends_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('site_id', 'slug', name='uq_storefront_campaign_slug'),
        sa.CheckConstraint("status IN ('draft', 'published')", name='ck_storefront_campaign_status'),
        sa.CheckConstraint("kind IN ('promotion', 'collection')", name='ck_storefront_campaign_kind'))
    op.create_index('ix_storefront_campaigns_site_id', 'storefront_campaigns', ['site_id'])
    op.create_index('ix_storefront_campaigns_status', 'storefront_campaigns', ['status'])
    op.create_table('storefront_campaign_products', *record_columns(),
        sa.Column('campaign_id', sa.String(36), sa.ForeignKey('storefront_campaigns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('product_id', sa.String(36), sa.ForeignKey('storefront_products.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.UniqueConstraint('campaign_id', 'product_id', name='uq_storefront_campaign_product'),
        sa.CheckConstraint('position >= 0', name='ck_storefront_campaign_position'))
    op.create_index('ix_storefront_campaign_products_campaign_id', 'storefront_campaign_products', ['campaign_id'])
    op.create_index('ix_storefront_campaign_products_product_id', 'storefront_campaign_products', ['product_id'])


def downgrade():
    op.drop_table('storefront_campaign_products')
    op.drop_table('storefront_campaigns')
