"""Add private support attachments."""
from alembic import op
import sqlalchemy as sa

revision = '0032'
down_revision = '0031'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'storefront_support_attachments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('request_id', sa.String(length=36), nullable=False),
        sa.Column('storage_key', sa.String(length=64), nullable=False),
        sa.Column('media_type', sa.String(length=40), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['request_id'], ['storefront_support_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('storage_key', name='uq_storefront_support_attachments_storage_key'),
        sa.CheckConstraint('size_bytes > 0 AND size_bytes <= 5242880', name='ck_storefront_support_attachments_size'),
    )
    op.create_index('ix_storefront_support_attachments_request_id', 'storefront_support_attachments', ['request_id'])


def downgrade():
    op.drop_index('ix_storefront_support_attachments_request_id', table_name='storefront_support_attachments')
    op.drop_table('storefront_support_attachments')
