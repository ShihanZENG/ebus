"""Add execution mode marker for isolated LIM Sandbox runs."""
from alembic import op
import sqlalchemy as sa

revision = '0035'
down_revision = '0034'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('lim_runs', sa.Column('execution_mode', sa.String(length=16), server_default='live', nullable=False))


def downgrade():
    op.drop_column('lim_runs', 'execution_mode')
