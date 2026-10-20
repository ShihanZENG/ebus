"""Add explicit local refund and return receipt evidence."""
import sqlalchemy as sa
from alembic import op

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('after_sales', sa.Column('refund_execution', sa.JSON(), nullable=True))
    op.add_column('after_sales', sa.Column('return_receipt', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('after_sales', 'return_receipt')
    op.drop_column('after_sales', 'refund_execution')
