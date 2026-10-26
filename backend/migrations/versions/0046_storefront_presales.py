"""Allow pre-order storefront support messages without inventing an order."""
from alembic import op
import sqlalchemy as sa

revision = '0046'
down_revision = '0045'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == 'sqlite':
        # Recreating the parent with FK checks enabled would cascade-delete attachments.
        with op.get_context().autocommit_block():
            op.execute('PRAGMA foreign_keys=OFF')
        try:
            with op.batch_alter_table('storefront_support_requests') as batch:
                batch.alter_column('order_id', existing_type=sa.String(36), nullable=True)
                batch.add_column(sa.Column('contact_email', sa.String(254), nullable=False, server_default=''))
        finally:
            with op.get_context().autocommit_block():
                op.execute('PRAGMA foreign_keys=ON')
    else:
        op.alter_column('storefront_support_requests', 'order_id', existing_type=sa.String(36), nullable=True)
        op.add_column('storefront_support_requests', sa.Column('contact_email', sa.String(254), nullable=False, server_default=''))


def downgrade():
    # Pre-order messages cannot be represented in the old schema. Never silently delete them.
    if op.get_bind().execute(sa.text('SELECT COUNT(*) FROM storefront_support_requests WHERE order_id IS NULL')).scalar():
        raise RuntimeError('Cannot downgrade while pre-sales messages exist')
    sqlite = op.get_bind().dialect.name == 'sqlite'
    if sqlite:
        with op.get_context().autocommit_block():
            op.execute('PRAGMA foreign_keys=OFF')
    try:
        with op.batch_alter_table('storefront_support_requests') as batch:
            batch.drop_column('contact_email')
            batch.alter_column('order_id', existing_type=sa.String(36), nullable=False)
    finally:
        if sqlite:
            with op.get_context().autocommit_block():
                op.execute('PRAGMA foreign_keys=ON')
