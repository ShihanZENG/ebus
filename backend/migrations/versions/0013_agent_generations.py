"""Evidence-backed generation and approved knowledge rules."""
import sqlalchemy as sa
from alembic import op

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def common():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def upgrade():
    op.create_table('agent_knowledge_rules', *common(),
        sa.Column('rule_code', sa.String(80), nullable=False),
        sa.Column('version', sa.String(40), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('market', sa.String(80), nullable=False),
        sa.Column('category', sa.String(80), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_until', sa.Date(), nullable=True),
        sa.Column('source_reference', sa.String(500), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('published_by', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=True),
        sa.UniqueConstraint('rule_code', 'version', name='uq_agent_rule_version'))
    op.create_table('agent_generations', *common(),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('shop_id', sa.String(36), sa.ForeignKey('shops.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('source_reference', sa.String(500), nullable=False),
        sa.Column('evidence_hash', sa.String(64), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False))
    op.create_index('ix_agent_generations_kind', 'agent_generations', ['kind'])
    op.create_index('ix_agent_generations_shop_id', 'agent_generations', ['shop_id'])


def downgrade():
    op.drop_index('ix_agent_generations_shop_id', table_name='agent_generations')
    op.drop_index('ix_agent_generations_kind', table_name='agent_generations')
    op.drop_table('agent_generations')
    op.drop_table('agent_knowledge_rules')
