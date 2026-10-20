"""Track durable staged-to-ready evidence storage state."""
from alembic import op
import sqlalchemy as sa


revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('payment_records', sa.Column('evidence_status', sa.String(20), nullable=False,
                                               server_default='ready'))


def downgrade():
    op.drop_column('payment_records', 'evidence_status')
