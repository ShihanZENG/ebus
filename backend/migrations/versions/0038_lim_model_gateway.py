"""Persist LIM Model Gateway provider registry, model catalog and per-call observability."""
from alembic import op
import sqlalchemy as sa

revision = '0038'
down_revision = '0037'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'lim_model_providers',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('provider_id', sa.String(64), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('protocol', sa.String(32), nullable=False),
        sa.Column('base_url', sa.String(500), nullable=False),
        # 只保存环境变量名，运行时 os.getenv 读取；明文 key 绝不落库。
        sa.Column('api_key_env', sa.String(120), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('timeout_ms', sa.Integer(), nullable=False, server_default='40000'),
        sa.Column('status', sa.String(16), nullable=False),
        sa.CheckConstraint("protocol IN ('openai_compatible')", name='ck_lim_model_providers_protocol'),
        sa.CheckConstraint("status IN ('ACTIVE','DISABLED','UNHEALTHY')", name='ck_lim_model_providers_status'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider_id', name='uq_lim_model_providers_id'),
    )
    op.create_index('ix_lim_model_providers_status', 'lim_model_providers', ['status'])

    op.create_table(
        'lim_model_catalog',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('alias_id', sa.String(36), nullable=False),
        sa.Column('alias', sa.String(64), nullable=False),
        sa.Column('provider_id', sa.String(64), nullable=False),
        sa.Column('model_name', sa.String(128), nullable=False),
        sa.Column('scene', sa.String(64), nullable=False, server_default='*'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='100'),
        sa.ForeignKeyConstraint(['provider_id'], ['lim_model_providers.provider_id'], ondelete='RESTRICT',
                                name='fk_lim_model_catalog_provider'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('alias_id', name='uq_lim_model_catalog_id'),
    )
    op.create_index('ix_lim_model_catalog_alias_scene', 'lim_model_catalog', ['alias', 'scene'])

    op.create_table(
        'lim_model_calls',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('call_id', sa.String(36), nullable=False),
        sa.Column('run_id', sa.String(36), nullable=True),
        sa.Column('span_id', sa.String(36), nullable=True),
        sa.Column('actor_id', sa.String(36), nullable=True),
        sa.Column('alias', sa.String(64), nullable=False),
        sa.Column('provider_id', sa.String(64), nullable=False),
        sa.Column('model', sa.String(128), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('error_code', sa.String(64), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('cost', sa.Numeric(14, 6), nullable=True),
        sa.Column('cache_hit', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('request_hash', sa.String(64), nullable=True),
        sa.CheckConstraint("status IN ('SUCCEEDED','FAILED','CACHED','REJECTED')",
                           name='ck_lim_model_calls_status'),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='RESTRICT',
                                name='fk_lim_model_calls_actor'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('call_id', name='uq_lim_model_calls_id'),
    )
    op.create_index('ix_lim_model_calls_created_at', 'lim_model_calls', ['created_at'])
    op.create_index('ix_lim_model_calls_actor_created', 'lim_model_calls', ['actor_id', 'created_at'])
    op.create_index('ix_lim_model_calls_provider_created', 'lim_model_calls', ['provider_id', 'created_at'])
    op.create_index('ix_lim_model_calls_run_id', 'lim_model_calls', ['run_id'])
    op.create_index('ix_lim_model_calls_request_hash', 'lim_model_calls', ['request_hash'])


def downgrade():
    op.drop_index('ix_lim_model_calls_request_hash', table_name='lim_model_calls')
    op.drop_index('ix_lim_model_calls_run_id', table_name='lim_model_calls')
    op.drop_index('ix_lim_model_calls_provider_created', table_name='lim_model_calls')
    op.drop_index('ix_lim_model_calls_actor_created', table_name='lim_model_calls')
    op.drop_index('ix_lim_model_calls_created_at', table_name='lim_model_calls')
    op.drop_table('lim_model_calls')
    op.drop_index('ix_lim_model_catalog_alias_scene', table_name='lim_model_catalog')
    op.drop_table('lim_model_catalog')
    op.drop_index('ix_lim_model_providers_status', table_name='lim_model_providers')
    op.drop_table('lim_model_providers')
