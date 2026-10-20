"""Persist order import provenance and results."""
import sqlalchemy as sa
from alembic import op

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('order_import_batches',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('shop_id', sa.String(36), sa.ForeignKey('shops.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('source_channel', sa.String(80), nullable=False),
        sa.Column('source_name', sa.String(255), nullable=False),
        sa.Column('data_origin', sa.String(24), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('row_count', sa.Integer(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False))
    op.create_index('ix_order_import_batches_shop_id', 'order_import_batches', ['shop_id'])


def downgrade():
    op.drop_table('order_import_batches')
