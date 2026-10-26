"""Add independent storefront customer identities and persistent order ownership."""
from alembic import op
import sqlalchemy as sa

revision = '0039'
down_revision = '0037'
branch_labels = None
depends_on = None


def record_columns():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def upgrade():
    op.create_table('storefront_customers', *record_columns(),
        sa.Column('site_id', sa.String(36), sa.ForeignKey('storefront_sites.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('username', sa.String(40), nullable=False),
        sa.Column('password_hash', sa.String(256), nullable=False),
        sa.UniqueConstraint('site_id', 'username', name='uq_storefront_customer_username'))
    op.create_table('storefront_customer_sessions', *record_columns(),
        sa.Column('customer_id', sa.String(36), sa.ForeignKey('storefront_customers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False))
    op.create_index('ix_storefront_customer_sessions_customer_id', 'storefront_customer_sessions', ['customer_id'])
    op.create_table('storefront_customer_orders', *record_columns(),
        sa.Column('customer_id', sa.String(36), sa.ForeignKey('storefront_customers.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('sales_orders.id', ondelete='RESTRICT'), nullable=False, unique=True))
    op.create_index('ix_storefront_customer_orders_customer_id', 'storefront_customer_orders', ['customer_id'])


def downgrade():
    op.drop_table('storefront_customer_orders')
    op.drop_table('storefront_customer_sessions')
    op.drop_table('storefront_customers')
