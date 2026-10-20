"""Persist independently reviewed daily sales-source evidence."""
import sqlalchemy as sa
from alembic import op

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sales_coverage_evidence',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('profile_id', sa.String(36), sa.ForeignKey('purchase_agent_profiles.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('source_reference', sa.String(500), nullable=False),
        sa.Column('source_sha256', sa.String(64), nullable=False),
        sa.Column('days', sa.JSON(), nullable=False),
        sa.Column('snapshot_hash', sa.String(64), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('submitted_by', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('reviewed_by', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT')),
        sa.Column('reviewed_at', sa.DateTime()),
        sa.Column('review_note', sa.String(500)),
        sa.CheckConstraint("status IN ('pending','approved','revoked')", name='ck_coverage_status'))
    op.create_index('ix_sales_coverage_evidence_profile_id', 'sales_coverage_evidence', ['profile_id'])


def downgrade():
    op.drop_table('sales_coverage_evidence')
