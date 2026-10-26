"""Storefront: no-op placeholder.

The earlier draft added payment status columns to ``storefront_order_meta`` and
``storefront_payments``. Those columns were never read or written by the service
layer (payment state is derived from the ``storefront_payments`` table via
``payment_view``), so they were removed from the models. This revision is kept as
a no-op so the migration chain stays linear and existing databases upgrade cleanly
without re-adding dead columns.
"""
from alembic import op

revision = '0043'
down_revision = '0042'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
