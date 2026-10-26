"""Persist immutable LIM Eval comparison reports."""
from alembic import op
import sqlalchemy as sa

revision = '0037'
down_revision = '0036'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'lim_eval_comparisons',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('comparison_id', sa.String(36), nullable=False),
        sa.Column('actor_id', sa.String(36), nullable=False),
        sa.Column('baseline_eval_run_id', sa.String(36), nullable=False),
        sa.Column('candidate_eval_run_id', sa.String(36), nullable=False),
        sa.Column('report', sa.JSON(), nullable=False),
        sa.Column('report_hash', sa.String(64), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.CheckConstraint("status IN ('PASS','FAIL','NOT_EVALUATED')", name='ck_lim_eval_comparisons_status'),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['baseline_eval_run_id'], ['lim_eval_runs.eval_run_id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['candidate_eval_run_id'], ['lim_eval_runs.eval_run_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('comparison_id', name='uq_lim_eval_comparisons_id'),
    )
    op.create_index('ix_lim_eval_comparisons_actor_id', 'lim_eval_comparisons', ['actor_id'])
    op.create_index('ix_lim_eval_comparisons_actor_created', 'lim_eval_comparisons', ['actor_id', 'created_at'])


def downgrade():
    op.drop_index('ix_lim_eval_comparisons_actor_created', table_name='lim_eval_comparisons')
    op.drop_index('ix_lim_eval_comparisons_actor_id', table_name='lim_eval_comparisons')
    op.drop_table('lim_eval_comparisons')
