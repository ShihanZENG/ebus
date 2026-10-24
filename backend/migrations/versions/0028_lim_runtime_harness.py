"""Create LIM registry, runtime, trace, and evaluation tables."""
from alembic import op
import sqlalchemy as sa

revision = '0028'
down_revision = '0027'
branch_labels = None
depends_on = None


def record_columns():
    return [
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    ]


def upgrade():
    op.create_table(
        'lim_agents',
        *record_columns(),
        sa.Column('agent_id', sa.String(64), nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('display_name', sa.String(120), nullable=False),
        sa.Column('business_domain', sa.String(64), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('definition', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.UniqueConstraint('agent_id', 'version', name='uq_lim_agents_agent_version'),
        sa.CheckConstraint("status IN ('draft', 'validated', 'archived')", name='ck_lim_agents_status'),
    )
    op.create_index('ix_lim_agents_agent_id', 'lim_agents', ['agent_id'])
    op.create_index('ix_lim_agents_owner_id', 'lim_agents', ['owner_id'])
    op.create_index('ix_lim_agents_business_domain', 'lim_agents', ['business_domain'])
    op.create_index('ix_lim_agents_status_agent', 'lim_agents', ['status', 'agent_id'])

    op.create_table(
        'lim_tools',
        *record_columns(),
        sa.Column('tool_id', sa.String(120), nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('service', sa.String(80), nullable=False),
        sa.Column('domain', sa.String(64), nullable=False),
        sa.Column('operation_kind', sa.String(8), nullable=False),
        sa.Column('risk_tier', sa.String(16), nullable=False),
        sa.Column('timeout_ms', sa.Integer(), nullable=False),
        sa.Column('rate_limit', sa.JSON(), nullable=True),
        sa.Column('idempotency_mode', sa.String(32), nullable=False),
        sa.Column('scope_policy', sa.JSON(), nullable=False),
        sa.Column('input_schema', sa.JSON(), nullable=False),
        sa.Column('output_schema', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.UniqueConstraint('tool_id', 'version', name='uq_lim_tools_tool_version'),
        sa.CheckConstraint("operation_kind IN ('read', 'write')", name='ck_lim_tools_operation_kind'),
        sa.CheckConstraint("risk_tier IN ('low', 'medium', 'high', 'critical')", name='ck_lim_tools_risk_tier'),
        sa.CheckConstraint("status IN ('draft', 'active', 'archived')", name='ck_lim_tools_status'),
        sa.CheckConstraint('timeout_ms > 0', name='ck_lim_tools_timeout_positive'),
    )
    op.create_index('ix_lim_tools_tool_id', 'lim_tools', ['tool_id'])
    op.create_index('ix_lim_tools_owner_id', 'lim_tools', ['owner_id'])
    op.create_index('ix_lim_tools_domain', 'lim_tools', ['domain'])
    op.create_index('ix_lim_tools_status_domain', 'lim_tools', ['status', 'domain'])

    op.create_table(
        'lim_eval_datasets',
        *record_columns(),
        sa.Column('dataset_id', sa.String(64), nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('description', sa.String(1000), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.UniqueConstraint('dataset_id', 'version', name='uq_lim_eval_datasets_version'),
        sa.CheckConstraint("status IN ('draft','frozen','archived')", name='ck_lim_eval_datasets_status'),
    )
    op.create_index('ix_lim_eval_datasets_dataset_id', 'lim_eval_datasets', ['dataset_id'])
    op.create_index('ix_lim_eval_datasets_owner_id', 'lim_eval_datasets', ['owner_id'])

    op.create_table(
        'lim_eval_cases',
        *record_columns(),
        sa.Column('dataset_id', sa.String(64), nullable=False),
        sa.Column('dataset_version', sa.String(32), nullable=False),
        sa.Column('case_id', sa.String(64), nullable=False),
        sa.Column('scenario', sa.String(500), nullable=False),
        sa.Column('input_payload', sa.JSON(), nullable=False),
        sa.Column('scope', sa.JSON(), nullable=False),
        sa.Column('ground_truth', sa.JSON(), nullable=True),
        sa.Column('acceptable_outputs', sa.JSON(), nullable=False),
        sa.Column('required_evidence', sa.JSON(), nullable=False),
        sa.Column('forbidden_actions', sa.JSON(), nullable=False),
        sa.Column('risk_tier', sa.String(16), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id', 'dataset_version'], ['lim_eval_datasets.dataset_id', 'lim_eval_datasets.version'],
                                ondelete='RESTRICT', name='fk_lim_eval_cases_dataset_version'),
        sa.UniqueConstraint('dataset_id', 'dataset_version', 'case_id', name='uq_lim_eval_cases_key'),
        sa.CheckConstraint("risk_tier IN ('low','medium','high','critical')", name='ck_lim_eval_cases_risk'),
    )
    op.create_index('ix_lim_eval_cases_dataset_version', 'lim_eval_cases', ['dataset_id', 'dataset_version'])

    op.create_table(
        'lim_runs',
        *record_columns(),
        sa.Column('run_id', sa.String(36), nullable=False),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('scope_ref', sa.String(36), nullable=False),
        sa.Column('scope_snapshot', sa.JSON(), nullable=False),
        sa.Column('agent_id', sa.String(64), nullable=False),
        sa.Column('agent_version', sa.String(32), nullable=False),
        sa.Column('trace_id', sa.String(36), nullable=False),
        sa.Column('goal_summary', sa.Text(), nullable=False),
        sa.Column('input_summary', sa.JSON(), nullable=False),
        sa.Column('output_summary', sa.JSON(), nullable=False),
        sa.Column('budget', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('error_code', sa.String(64), nullable=True),
        sa.Column('error_summary', sa.String(500), nullable=True),
        sa.Column('token_usage', sa.Integer(), nullable=True),
        sa.Column('cost', sa.Numeric(14, 6), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id', 'agent_version'], ['lim_agents.agent_id', 'lim_agents.version'],
                                ondelete='RESTRICT', name='fk_lim_runs_agent_version'),
        sa.UniqueConstraint('run_id', name='uq_lim_runs_run_id'),
        sa.CheckConstraint(
            "status IN ('CREATED','SCOPE_CHECKED','PLANNED','RUNNING','VERIFYING','COMPLETED','REVIEW_REQUIRED','APPROVED','EXECUTING','RECONCILING','REJECTED','FAILED','WAITING_INPUT','WAITING_RECONCILIATION','BUDGET_EXCEEDED','CANCELLED')",
            name='ck_lim_runs_status'),
    )
    op.create_index('ix_lim_runs_actor_id', 'lim_runs', ['actor_id'])
    op.create_index('ix_lim_runs_scope_ref', 'lim_runs', ['scope_ref'])
    op.create_index('ix_lim_runs_error_code', 'lim_runs', ['error_code'])
    op.create_index('ix_lim_runs_status_created', 'lim_runs', ['status', 'created_at'])
    op.create_index('ix_lim_runs_actor_created', 'lim_runs', ['actor_id', 'created_at'])
    op.create_index('ix_lim_runs_trace_id', 'lim_runs', ['trace_id'])

    op.create_table(
        'lim_spans',
        *record_columns(),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('lim_runs.run_id', ondelete='CASCADE'), nullable=False),
        sa.Column('span_id', sa.String(36), nullable=False),
        sa.Column('parent_span_id', sa.String(36), nullable=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('attributes', sa.JSON(), nullable=False),
        sa.Column('error_type', sa.String(64), nullable=True),
        sa.Column('error_code', sa.String(64), nullable=True),
        sa.Column('token_usage', sa.Integer(), nullable=True),
        sa.Column('cost', sa.Numeric(14, 6), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('span_id', name='uq_lim_spans_span_id'),
        sa.CheckConstraint("status IN ('RUNNING','SUCCEEDED','FAILED','REJECTED','CANCELLED')", name='ck_lim_spans_status'),
    )
    op.create_index('ix_lim_spans_run_id', 'lim_spans', ['run_id'])
    op.create_index('ix_lim_spans_parent_span_id', 'lim_spans', ['parent_span_id'])
    op.create_index('ix_lim_spans_run_started', 'lim_spans', ['run_id', 'created_at'])

    op.create_table(
        'lim_tool_invocations',
        *record_columns(),
        sa.Column('invocation_id', sa.String(64), nullable=False),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('lim_runs.run_id', ondelete='CASCADE'), nullable=False),
        sa.Column('span_id', sa.String(36), sa.ForeignKey('lim_spans.span_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('tool_id', sa.String(120), nullable=False),
        sa.Column('tool_version', sa.String(32), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('read_only', sa.Boolean(), nullable=False),
        sa.Column('arguments_summary', sa.JSON(), nullable=False),
        sa.Column('response_summary', sa.JSON(), nullable=False),
        sa.Column('evidence_refs', sa.JSON(), nullable=False),
        sa.Column('error_code', sa.String(64), nullable=True),
        sa.Column('elapsed_ms', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['tool_id', 'tool_version'], ['lim_tools.tool_id', 'lim_tools.version'],
                                ondelete='RESTRICT', name='fk_lim_invocations_tool_version'),
        sa.UniqueConstraint('invocation_id', name='uq_lim_tool_invocations_id'),
        sa.CheckConstraint("status IN ('PENDING','SUCCEEDED','FAILED','BLOCKED','TIMEOUT')", name='ck_lim_invocations_status'),
    )
    op.create_index('ix_lim_tool_invocations_run_id', 'lim_tool_invocations', ['run_id'])
    op.create_index('ix_lim_tool_invocations_span_id', 'lim_tool_invocations', ['span_id'])
    op.create_index('ix_lim_invocations_run_created', 'lim_tool_invocations', ['run_id', 'created_at'])

    op.create_table(
        'lim_eval_runs',
        *record_columns(),
        sa.Column('eval_run_id', sa.String(36), nullable=False),
        sa.Column('dataset_id', sa.String(64), nullable=False),
        sa.Column('dataset_version', sa.String(32), nullable=False),
        sa.Column('agent_id', sa.String(64), nullable=False),
        sa.Column('agent_version', sa.String(32), nullable=False),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('environment', sa.String(24), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('metrics', sa.JSON(), nullable=False),
        sa.Column('error_code', sa.String(64), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['dataset_id', 'dataset_version'], ['lim_eval_datasets.dataset_id', 'lim_eval_datasets.version'],
                                ondelete='RESTRICT', name='fk_lim_eval_runs_dataset_version'),
        sa.ForeignKeyConstraint(['agent_id', 'agent_version'], ['lim_agents.agent_id', 'lim_agents.version'],
                                ondelete='RESTRICT', name='fk_lim_eval_runs_agent_version'),
        sa.CheckConstraint("status IN ('QUEUED','RUNNING','COMPLETED','FAILED')", name='ck_lim_eval_runs_status'),
    )
    op.create_index('ix_lim_eval_runs_eval_run_id', 'lim_eval_runs', ['eval_run_id'], unique=True)
    op.create_index('ix_lim_eval_runs_actor_id', 'lim_eval_runs', ['actor_id'])
    op.create_index('ix_lim_eval_runs_status_created', 'lim_eval_runs', ['status', 'created_at'])

    op.create_table(
        'lim_eval_case_results',
        *record_columns(),
        sa.Column('eval_run_id', sa.String(36), sa.ForeignKey('lim_eval_runs.eval_run_id', ondelete='CASCADE'), nullable=False),
        sa.Column('dataset_id', sa.String(64), nullable=False),
        sa.Column('dataset_version', sa.String(32), nullable=False),
        sa.Column('case_id', sa.String(64), nullable=False),
        sa.Column('outcome', sa.String(16), nullable=False),
        sa.Column('actual_output', sa.JSON(), nullable=False),
        sa.Column('failures', sa.JSON(), nullable=False),
        sa.Column('elapsed_ms', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['dataset_id', 'dataset_version', 'case_id'],
                                ['lim_eval_cases.dataset_id', 'lim_eval_cases.dataset_version', 'lim_eval_cases.case_id'],
                                ondelete='RESTRICT', name='fk_lim_eval_results_case'),
        sa.UniqueConstraint('eval_run_id', 'case_id', name='uq_lim_eval_case_results_case'),
        sa.CheckConstraint("outcome IN ('PASS','FAIL','NOT_EVALUATED')", name='ck_lim_eval_case_results_outcome'),
    )
    op.create_index('ix_lim_eval_case_results_run', 'lim_eval_case_results', ['eval_run_id'])


def downgrade():
    op.drop_index('ix_lim_eval_case_results_run', table_name='lim_eval_case_results')
    op.drop_table('lim_eval_case_results')
    op.drop_index('ix_lim_eval_runs_status_created', table_name='lim_eval_runs')
    op.drop_index('ix_lim_eval_runs_actor_id', table_name='lim_eval_runs')
    op.drop_index('ix_lim_eval_runs_eval_run_id', table_name='lim_eval_runs')
    op.drop_table('lim_eval_runs')
    op.drop_index('ix_lim_tool_invocations_run_created', table_name='lim_tool_invocations')
    op.drop_index('ix_lim_tool_invocations_span_id', table_name='lim_tool_invocations')
    op.drop_index('ix_lim_tool_invocations_run_id', table_name='lim_tool_invocations')
    op.drop_table('lim_tool_invocations')
    op.drop_index('ix_lim_spans_run_started', table_name='lim_spans')
    op.drop_index('ix_lim_spans_parent_span_id', table_name='lim_spans')
    op.drop_index('ix_lim_spans_run_id', table_name='lim_spans')
    op.drop_table('lim_spans')
    op.drop_index('ix_lim_runs_trace_id', table_name='lim_runs')
    op.drop_index('ix_lim_runs_actor_created', table_name='lim_runs')
    op.drop_index('ix_lim_runs_status_created', table_name='lim_runs')
    op.drop_index('ix_lim_runs_error_code', table_name='lim_runs')
    op.drop_index('ix_lim_runs_scope_ref', table_name='lim_runs')
    op.drop_index('ix_lim_runs_actor_id', table_name='lim_runs')
    op.drop_table('lim_runs')
    op.drop_index('ix_lim_eval_cases_dataset_version', table_name='lim_eval_cases')
    op.drop_table('lim_eval_cases')
    op.drop_index('ix_lim_eval_datasets_owner_id', table_name='lim_eval_datasets')
    op.drop_index('ix_lim_eval_datasets_dataset_id', table_name='lim_eval_datasets')
    op.drop_table('lim_eval_datasets')
    op.drop_index('ix_lim_tools_status_domain', table_name='lim_tools')
    op.drop_index('ix_lim_tools_domain', table_name='lim_tools')
    op.drop_index('ix_lim_tools_owner_id', table_name='lim_tools')
    op.drop_index('ix_lim_tools_tool_id', table_name='lim_tools')
    op.drop_table('lim_tools')
    op.drop_index('ix_lim_agents_status_agent', table_name='lim_agents')
    op.drop_index('ix_lim_agents_business_domain', table_name='lim_agents')
    op.drop_index('ix_lim_agents_owner_id', table_name='lim_agents')
    op.drop_index('ix_lim_agents_agent_id', table_name='lim_agents')
    op.drop_table('lim_agents')
