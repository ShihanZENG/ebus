"""Business risk events and immutable strategy versions."""
from alembic import op
import sqlalchemy as sa

revision = '0041'
down_revision = '0040'
branch_labels = None
depends_on = None


def common():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def upgrade():
    op.create_table('decision_risks', *common(),
        sa.Column('profile_id', sa.String(36), sa.ForeignKey('purchase_agent_profiles.id'), nullable=False),
        sa.Column('dedupe_key', sa.String(64), nullable=False, unique=True),
        sa.Column('business_date', sa.Date(), nullable=False),
        sa.Column('risk_type', sa.String(40), nullable=False),
        sa.Column('severity', sa.String(16), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('detected_at', sa.DateTime(), nullable=False),
        sa.Column('metrics', sa.JSON(), nullable=False),
        sa.Column('source', sa.JSON(), nullable=False),
        sa.Column('history', sa.JSON(), nullable=False))
    op.create_index('ix_decision_risks_profile_id', 'decision_risks', ['profile_id'])
    op.create_table('decision_tasks', *common(),
        sa.Column('risk_id', sa.String(36), sa.ForeignKey('decision_risks.id'), nullable=False),
        sa.Column('objective', sa.String(300), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('selected_version', sa.String(36), nullable=True),
        sa.Column('selected_scenario', sa.Integer(), nullable=True),
        sa.Column('requested_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('approved_by', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('execution', sa.JSON(), nullable=False),
        sa.Column('execution_key', sa.String(64), nullable=True, unique=True),
        sa.Column('history', sa.JSON(), nullable=False))
    op.create_index('ix_decision_tasks_risk_id', 'decision_tasks', ['risk_id'])
    op.create_table('decision_versions', *common(),
        sa.Column('task_id', sa.String(36), sa.ForeignKey('decision_tasks.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('evidence_hash', sa.String(64), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('scenarios', sa.JSON(), nullable=False),
        sa.Column('calculation_version', sa.String(40), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('task_id', 'version', name='uq_decision_task_version'))
    op.create_index('ix_decision_versions_task_id', 'decision_versions', ['task_id'])


def downgrade():
    op.drop_table('decision_versions')
    op.drop_table('decision_tasks')
    op.drop_table('decision_risks')
