"""Add persisted LIM alert rules and alert lifecycle records."""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = '0036'
down_revision = '0035'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'lim_alert_rules',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('rule_key', sa.String(length=64), nullable=False),
        sa.Column('display_name', sa.String(length=120), nullable=False),
        sa.Column('dimension', sa.String(length=16), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('threshold', sa.Integer(), nullable=False),
        sa.Column('window_seconds', sa.Integer(), nullable=False),
        sa.CheckConstraint("dimension IN ('agent','tool','workflow')", name='ck_lim_alert_rules_dimension'),
        sa.CheckConstraint('threshold BETWEEN 1 AND 1000', name='ck_lim_alert_rules_threshold'),
        sa.CheckConstraint('window_seconds BETWEEN 60 AND 86400', name='ck_lim_alert_rules_window'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('rule_key', name='uq_lim_alert_rules_key'),
    )
    op.create_index('ix_lim_alert_rules_enabled', 'lim_alert_rules', ['enabled'])
    op.create_table(
        'lim_alerts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('alert_id', sa.String(length=36), nullable=False),
        sa.Column('dedupe_key', sa.String(length=200), nullable=False),
        sa.Column('rule_key', sa.String(length=64), nullable=False),
        sa.Column('entity_key', sa.String(length=120), nullable=False),
        sa.Column('entity_label', sa.String(length=160), nullable=False),
        sa.Column('severity', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('summary', sa.String(length=240), nullable=False),
        sa.Column('error_code', sa.String(length=64), nullable=False),
        sa.Column('occurrence_count', sa.Integer(), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(), nullable=False),
        sa.Column('actor_id', sa.String(length=36), nullable=False),
        sa.Column('agent_id', sa.String(length=64), nullable=True),
        sa.Column('tool_id', sa.String(length=120), nullable=True),
        sa.Column('workflow_id', sa.String(length=64), nullable=True),
        sa.Column('run_id', sa.String(length=36), nullable=True),
        sa.Column('trace_id', sa.String(length=36), nullable=True),
        sa.Column('workflow_run_id', sa.String(length=36), nullable=True),
        sa.Column('acknowledged_by', sa.String(length=36), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
        sa.Column('closed_by', sa.String(length=36), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','CLOSED')", name='ck_lim_alerts_status'),
        sa.ForeignKeyConstraint(['rule_key'], ['lim_alert_rules.rule_key'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['acknowledged_by'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['closed_by'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('alert_id'),
        sa.UniqueConstraint('dedupe_key', name='uq_lim_alerts_dedupe_key'),
    )
    for name, column in [
        ('ix_lim_alerts_rule_key', 'rule_key'),
        ('ix_lim_alerts_actor_id', 'actor_id'), ('ix_lim_alerts_agent_id', 'agent_id'),
        ('ix_lim_alerts_tool_id', 'tool_id'), ('ix_lim_alerts_workflow_id', 'workflow_id'),
        ('ix_lim_alerts_run_id', 'run_id'), ('ix_lim_alerts_trace_id', 'trace_id'),
        ('ix_lim_alerts_workflow_run_id', 'workflow_run_id'),
    ]:
        op.create_index(name, 'lim_alerts', [column])
    op.create_index('ix_lim_alerts_status_last_seen', 'lim_alerts', ['status', 'last_seen_at'])
    op.create_index('ix_lim_alerts_actor_created', 'lim_alerts', ['actor_id', 'created_at'])
    op.create_index('ix_lim_alerts_entity', 'lim_alerts', ['rule_key', 'entity_key'])

    rules = sa.table('lim_alert_rules', sa.column('id', sa.String), sa.column('created_at', sa.DateTime),
                     sa.column('updated_at', sa.DateTime), sa.column('rule_key', sa.String),
                     sa.column('display_name', sa.String), sa.column('dimension', sa.String),
                     sa.column('enabled', sa.Boolean), sa.column('threshold', sa.Integer),
                     sa.column('window_seconds', sa.Integer))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    op.bulk_insert(rules, [
        {'id': 'lim-alert-rule-run-failure', 'created_at': now, 'updated_at': now,
         'rule_key': 'run_failure', 'display_name': 'Agent Run 失败', 'dimension': 'agent',
         'enabled': True, 'threshold': 3, 'window_seconds': 600},
        {'id': 'lim-alert-rule-tool-timeout', 'created_at': now, 'updated_at': now,
         'rule_key': 'tool_timeout', 'display_name': '只读 Tool 超时', 'dimension': 'tool',
         'enabled': True, 'threshold': 2, 'window_seconds': 600},
        {'id': 'lim-alert-rule-workflow-failure', 'created_at': now, 'updated_at': now,
         'rule_key': 'workflow_failure', 'display_name': 'Workflow 编排失败', 'dimension': 'workflow',
         'enabled': True, 'threshold': 3, 'window_seconds': 600},
    ])


def downgrade():
    op.drop_index('ix_lim_alerts_entity', table_name='lim_alerts')
    op.drop_index('ix_lim_alerts_actor_created', table_name='lim_alerts')
    op.drop_index('ix_lim_alerts_status_last_seen', table_name='lim_alerts')
    for name in ['ix_lim_alerts_workflow_run_id', 'ix_lim_alerts_trace_id', 'ix_lim_alerts_run_id',
                 'ix_lim_alerts_workflow_id', 'ix_lim_alerts_tool_id', 'ix_lim_alerts_agent_id',
                 'ix_lim_alerts_actor_id', 'ix_lim_alerts_rule_key']:
        op.drop_index(name, table_name='lim_alerts')
    op.drop_table('lim_alerts')
    op.drop_index('ix_lim_alert_rules_enabled', table_name='lim_alert_rules')
    op.drop_table('lim_alert_rules')
