"""Add a single-review workflow to generated results."""

import sqlalchemy as sa
from alembic import op


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('agent_generations') as batch:
        batch.add_column(sa.Column('review_status', sa.String(16), nullable=False, server_default='pending'))
        batch.add_column(sa.Column('reviewed_by', sa.String(36), nullable=True))
        batch.add_column(sa.Column('reviewed_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('review_note', sa.Text(), nullable=True))
        batch.create_foreign_key(
            'fk_agent_generations_reviewed_by_users', 'users', ['reviewed_by'], ['id'], ondelete='RESTRICT'
        )
        batch.create_check_constraint(
            'ck_agent_generations_review_status',
            "review_status IN ('pending', 'approved', 'rejected')",
        )
    op.create_index('ix_agent_generations_review_status', 'agent_generations', ['review_status'])


def downgrade():
    op.drop_index('ix_agent_generations_review_status', table_name='agent_generations')
    with op.batch_alter_table('agent_generations') as batch:
        batch.drop_constraint('ck_agent_generations_review_status', type_='check')
        batch.drop_constraint('fk_agent_generations_reviewed_by_users', type_='foreignkey')
        batch.drop_column('review_note')
        batch.drop_column('reviewed_at')
        batch.drop_column('reviewed_by')
        batch.drop_column('review_status')
