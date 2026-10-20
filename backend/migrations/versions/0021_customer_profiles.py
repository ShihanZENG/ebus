"""Add shop-scoped customer profiles and optional sales/ticket links."""
import sqlalchemy as sa
from alembic import op


revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'customers',
        sa.Column('shop_id', sa.String(36), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('contact', sa.String(200), nullable=False, server_default=''),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_customers_shop_id', 'customers', ['shop_id'])
    with op.batch_alter_table('sales_orders') as batch:
        batch.add_column(sa.Column('customer_id', sa.String(36), nullable=True))
        batch.create_foreign_key('fk_sales_orders_customer_id_customers', 'customers',
                                 ['customer_id'], ['id'], ondelete='RESTRICT')
        batch.create_index('ix_sales_orders_customer_id', ['customer_id'])
    with op.batch_alter_table('customer_tickets') as batch:
        batch.add_column(sa.Column('customer_id', sa.String(36), nullable=True))
        batch.create_foreign_key('fk_customer_tickets_customer_id_customers', 'customers',
                                 ['customer_id'], ['id'], ondelete='RESTRICT')
        batch.create_index('ix_customer_tickets_customer_id', ['customer_id'])


def downgrade():
    with op.batch_alter_table('customer_tickets') as batch:
        batch.drop_index('ix_customer_tickets_customer_id')
        batch.drop_constraint('fk_customer_tickets_customer_id_customers', type_='foreignkey')
        batch.drop_column('customer_id')
    with op.batch_alter_table('sales_orders') as batch:
        batch.drop_index('ix_sales_orders_customer_id')
        batch.drop_constraint('fk_sales_orders_customer_id_customers', type_='foreignkey')
        batch.drop_column('customer_id')
    op.drop_index('ix_customers_shop_id', table_name='customers')
    op.drop_table('customers')
