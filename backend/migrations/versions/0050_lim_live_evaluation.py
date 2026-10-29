"""Persist versioned evaluations for real LIM runs."""
from alembic import op
import sqlalchemy as sa

revision = '0050'
down_revision = '0049'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('lim_live_evaluations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('lim_live_runs.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('metrics', sa.JSON(), nullable=False),
        sa.Column('usage', sa.JSON(), nullable=False),
        sa.Column('delivery', sa.JSON(), nullable=False),
        sa.UniqueConstraint('run_id', name='uq_lim_live_evaluations_run_id'))
    op.create_index('ix_lim_live_evaluations_run_id', 'lim_live_evaluations', ['run_id'])


def downgrade():
    op.drop_table('lim_live_evaluations')
