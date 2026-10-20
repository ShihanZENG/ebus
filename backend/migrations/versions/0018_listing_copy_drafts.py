"""Persist fact-based listing copy drafts for review."""
import sqlalchemy as sa
from alembic import op

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('listing_copy_drafts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('listing_id', sa.String(36), sa.ForeignKey('listings.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('source_hash', sa.String(64), nullable=False),
        sa.Column('input_snapshot', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('review_status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('reviewed_by', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT')),
        sa.Column('reviewed_at', sa.DateTime()),
        sa.Column('review_note', sa.String(500)))
    op.create_index('ix_listing_copy_drafts_listing_id', 'listing_copy_drafts', ['listing_id'])
    op.create_index('ix_listing_copy_drafts_actor_id', 'listing_copy_drafts', ['actor_id'])
    op.create_index('ix_listing_copy_drafts_review_status', 'listing_copy_drafts', ['review_status'])


def downgrade():
    op.drop_table('listing_copy_drafts')
