"""Storefront support classification, staff reply, and private presales receipt."""
from alembic import op
import sqlalchemy as sa

revision = '0051'
down_revision = '0050'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('storefront_support_requests', sa.Column('intent', sa.String(32), nullable=False, server_default='other'))
    op.add_column('storefront_support_requests', sa.Column('reply', sa.Text(), nullable=False, server_default=''))
    op.add_column('storefront_support_requests', sa.Column('receipt_hash', sa.String(64), nullable=False, server_default=''))


def downgrade():
    op.drop_column('storefront_support_requests', 'receipt_hash')
    op.drop_column('storefront_support_requests', 'reply')
    op.drop_column('storefront_support_requests', 'intent')
