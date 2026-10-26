"""Add structured product content for storefront details.

Revision ID: 0030
Revises: 0029
"""
from alembic import op
import sqlalchemy as sa

revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('storefront_products', sa.Column('gallery', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('storefront_products', sa.Column('material', sa.Text(), nullable=False, server_default=''))
    op.add_column('storefront_products', sa.Column('care_instructions', sa.Text(), nullable=False, server_default=''))
    op.add_column('storefront_products', sa.Column('size_guide', sa.JSON(), nullable=False, server_default='[]'))


def downgrade():
    op.drop_column('storefront_products', 'size_guide')
    op.drop_column('storefront_products', 'care_instructions')
    op.drop_column('storefront_products', 'material')
    op.drop_column('storefront_products', 'gallery')
