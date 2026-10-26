"""Persist safe model attempt metadata and routing scene."""
from alembic import op
import sqlalchemy as sa

revision = '0047'
down_revision = '0046'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('lim_model_calls', sa.Column('scene', sa.String(64), nullable=False, server_default='*'))
    op.add_column('lim_model_calls', sa.Column('attempts', sa.JSON(), nullable=False, server_default='[]'))


def downgrade():
    op.drop_column('lim_model_calls', 'attempts')
    op.drop_column('lim_model_calls', 'scene')
