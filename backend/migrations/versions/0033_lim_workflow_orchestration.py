"""Add LIM workflow definition, run, and task tables."""
from alembic import op
import sqlalchemy as sa


revision = '0033'
down_revision = '0032'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'lim_workflows',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('workflow_id', sa.String(length=64), nullable=False),
        sa.Column('display_name', sa.String(length=120), nullable=False),
        sa.Column('business_domain', sa.String(length=64), nullable=False),
        sa.Column('owner_id', sa.String(length=36), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workflow_id', name='uq_lim_workflows_workflow_id'),
        sa.CheckConstraint("status IN ('draft','active','archived')", name='ck_lim_workflows_status'),
    )
    op.create_index('ix_lim_workflows_owner_id', 'lim_workflows', ['owner_id'])
    op.create_index('ix_lim_workflows_domain_status', 'lim_workflows', ['business_domain', 'status'])

    op.create_table(
        'lim_workflow_versions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('workflow_id', sa.String(length=64), nullable=False),
        sa.Column('version', sa.String(length=32), nullable=False),
        sa.Column('definition', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_by', sa.String(length=36), nullable=False),
        sa.Column('validated_by', sa.String(length=36), nullable=True),
        sa.Column('validated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['workflow_id'], ['lim_workflows.workflow_id'], ondelete='RESTRICT',
                                name='fk_lim_workflow_versions_workflow'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['validated_by'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workflow_id', 'version', name='uq_lim_workflow_versions_version'),
        sa.CheckConstraint("status IN ('draft','validated','archived')", name='ck_lim_workflow_versions_status'),
    )
    op.create_index('ix_lim_workflow_versions_created_by', 'lim_workflow_versions', ['created_by'])
    op.create_index('ix_lim_workflow_versions_status', 'lim_workflow_versions', ['status', 'created_at'])

    op.create_table(
        'lim_workflow_runs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('workflow_run_id', sa.String(length=36), nullable=False),
        sa.Column('workflow_id', sa.String(length=64), nullable=False),
        sa.Column('workflow_version', sa.String(length=32), nullable=False),
        sa.Column('actor_id', sa.String(length=36), nullable=False),
        sa.Column('scope_ref', sa.String(length=36), nullable=False),
        sa.Column('scope_snapshot', sa.JSON(), nullable=False),
        sa.Column('input_summary', sa.JSON(), nullable=False),
        sa.Column('output_summary', sa.JSON(), nullable=False),
        sa.Column('budget', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('cancellation_requested', sa.Boolean(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['workflow_id', 'workflow_version'],
                                ['lim_workflow_versions.workflow_id', 'lim_workflow_versions.version'],
                                ondelete='RESTRICT', name='fk_lim_workflow_runs_version'),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workflow_run_id', name='uq_lim_workflow_runs_run_id'),
        sa.CheckConstraint("status IN ('CREATED','RUNNING','COMPLETED','COMPLETED_WITH_CONFLICTS','PARTIAL','FAILED','CANCELLED','BUDGET_EXCEEDED')",
                           name='ck_lim_workflow_runs_status'),
    )
    op.create_index('ix_lim_workflow_runs_actor_id', 'lim_workflow_runs', ['actor_id'])
    op.create_index('ix_lim_workflow_runs_scope_ref', 'lim_workflow_runs', ['scope_ref'])
    op.create_index('ix_lim_workflow_runs_error_code', 'lim_workflow_runs', ['error_code'])
    op.create_index('ix_lim_workflow_runs_actor_created', 'lim_workflow_runs', ['actor_id', 'created_at'])
    op.create_index('ix_lim_workflow_runs_status_created', 'lim_workflow_runs', ['status', 'created_at'])

    op.create_table(
        'lim_workflow_tasks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('workflow_run_id', sa.String(length=36), nullable=False),
        sa.Column('node_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('dependencies', sa.JSON(), nullable=False),
        sa.Column('child_run_id', sa.String(length=36), nullable=True),
        sa.Column('result_summary', sa.JSON(), nullable=False),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('condition_result', sa.Boolean(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['workflow_run_id'], ['lim_workflow_runs.workflow_run_id'], ondelete='RESTRICT',
                                name='fk_lim_workflow_tasks_run'),
        sa.ForeignKeyConstraint(['child_run_id'], ['lim_runs.run_id'], ondelete='RESTRICT',
                                name='fk_lim_workflow_tasks_child_run'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workflow_run_id', 'node_id', name='uq_lim_workflow_tasks_node'),
        sa.CheckConstraint("status IN ('PENDING','RUNNING','COMPLETED','SKIPPED','FAILED','CANCELLED','BUDGET_EXCEEDED')",
                           name='ck_lim_workflow_tasks_status'),
    )
    op.create_index('ix_lim_workflow_tasks_child_run_id', 'lim_workflow_tasks', ['child_run_id'])
    op.create_index('ix_lim_workflow_tasks_status', 'lim_workflow_tasks', ['workflow_run_id', 'status'])


def downgrade():
    op.drop_index('ix_lim_workflow_tasks_status', table_name='lim_workflow_tasks')
    op.drop_index('ix_lim_workflow_tasks_child_run_id', table_name='lim_workflow_tasks')
    op.drop_table('lim_workflow_tasks')
    op.drop_index('ix_lim_workflow_runs_status_created', table_name='lim_workflow_runs')
    op.drop_index('ix_lim_workflow_runs_actor_created', table_name='lim_workflow_runs')
    op.drop_index('ix_lim_workflow_runs_error_code', table_name='lim_workflow_runs')
    op.drop_index('ix_lim_workflow_runs_scope_ref', table_name='lim_workflow_runs')
    op.drop_index('ix_lim_workflow_runs_actor_id', table_name='lim_workflow_runs')
    op.drop_table('lim_workflow_runs')
    op.drop_index('ix_lim_workflow_versions_status', table_name='lim_workflow_versions')
    op.drop_index('ix_lim_workflow_versions_created_by', table_name='lim_workflow_versions')
    op.drop_table('lim_workflow_versions')
    op.drop_index('ix_lim_workflows_domain_status', table_name='lim_workflows')
    op.drop_index('ix_lim_workflows_owner_id', table_name='lim_workflows')
    op.drop_table('lim_workflows')
