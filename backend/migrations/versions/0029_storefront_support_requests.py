"""Storefront customer support requests."""
from alembic import op
import sqlalchemy as sa


revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'storefront_support_requests',
        sa.Column('site_id', sa.String(36), sa.ForeignKey('storefront_sites.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('sales_orders.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('public_ref', sa.String(40), nullable=False),
        sa.Column('issue', sa.String(32), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='open'),
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('public_ref', name='uq_storefront_support_public_ref'),
    )
    op.create_index('ix_storefront_support_requests_site_id', 'storefront_support_requests', ['site_id'])
    op.create_index('ix_storefront_support_requests_order_id', 'storefront_support_requests', ['order_id'])
    op.create_index('ix_storefront_support_requests_status', 'storefront_support_requests', ['status'])


def downgrade():
    op.drop_index('ix_storefront_support_requests_status', table_name='storefront_support_requests')
    op.drop_index('ix_storefront_support_requests_order_id', table_name='storefront_support_requests')
    op.drop_index('ix_storefront_support_requests_site_id', table_name='storefront_support_requests')
    op.drop_table('storefront_support_requests')
