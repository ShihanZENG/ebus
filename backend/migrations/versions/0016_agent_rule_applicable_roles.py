"""Add role applicability to customer knowledge rules."""

import sqlalchemy as sa
from alembic import op


revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('agent_knowledge_rules', sa.Column(
        'applicable_roles', sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade():
    op.drop_column('agent_knowledge_rules', 'applicable_roles')
