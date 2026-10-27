"""Durable checkpoints and memory for real business workflows."""
from alembic import op
import sqlalchemy as sa

revision = '0049'
down_revision = '0048'
branch_labels = None
depends_on = None


def record_columns():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def upgrade():
    op.create_table('lim_live_runs', *record_columns(),
        sa.Column('workflow_run_id', sa.String(36), sa.ForeignKey('lim_workflow_runs.workflow_run_id'), unique=True, nullable=False),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('shop_id', sa.String(36), sa.ForeignKey('shops.id'), nullable=False),
        sa.Column('warehouse_id', sa.String(36), sa.ForeignKey('warehouses.id'), nullable=False),
        sa.Column('lease_token', sa.String(36), nullable=True),
        sa.Column('lease_until', sa.DateTime(), nullable=True),
        sa.Column('child_run_ids', sa.JSON(), nullable=False))
    op.create_index('ix_lim_live_runs_actor_id', 'lim_live_runs', ['actor_id'])
    op.create_table('lim_live_checkpoints', *record_columns(),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('lim_live_runs.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('node_id', sa.String(32), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.UniqueConstraint('run_id', 'version', name='uq_live_checkpoint_version'))
    op.create_index('ix_lim_live_checkpoints_run_id', 'lim_live_checkpoints', ['run_id'])
    op.create_table('lim_live_memories', *record_columns(),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('lim_live_runs.id'), nullable=False),
        sa.Column('node_id', sa.String(32), nullable=False),
        sa.Column('tier', sa.String(16), nullable=False),
        sa.Column('content', sa.JSON(), nullable=False),
        sa.Column('archived', sa.Boolean(), nullable=False),
        sa.UniqueConstraint('run_id', 'node_id', 'tier', name='uq_live_memory_source'))
    op.create_index('ix_lim_live_memories_run_id', 'lim_live_memories', ['run_id'])


def downgrade():
    op.drop_table('lim_live_memories')
    op.drop_table('lim_live_checkpoints')
    op.drop_table('lim_live_runs')
