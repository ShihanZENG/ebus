"""Inventory ownership and document allocations; preserve historical balances."""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def base_columns():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('warehouse_id', sa.String(36), sa.ForeignKey('warehouses.id', ondelete='RESTRICT'), nullable=False),
            sa.Column('sku_id', sa.String(36), sa.ForeignKey('skus.id', ondelete='RESTRICT'), nullable=False)]


def upgrade():
    op.add_column('fba_plans', sa.Column('route_type', sa.String(32), nullable=False, server_default='domestic_to_fba'))
    op.create_table('inventory_ownership', *base_columns(),
        sa.Column('shop_id', sa.String(36), sa.ForeignKey('shops.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('reserved_qty', sa.Integer(), nullable=False),
        sa.UniqueConstraint('warehouse_id', 'sku_id', 'shop_id', name='uq_inventory_owner'),
        sa.CheckConstraint('quantity >= reserved_qty AND reserved_qty >= 0', name='ck_inventory_owner_qty'))
    op.create_table('inventory_allocations', *base_columns(),
        sa.Column('shop_id', sa.String(36), sa.ForeignKey('shops.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('pool_key', sa.String(36), nullable=False),
        sa.Column('task_type', sa.String(20), nullable=False),
        sa.Column('task_id', sa.String(36), nullable=False),
        sa.Column('reference_no', sa.String(120), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.UniqueConstraint('task_type', 'task_id', 'warehouse_id', 'sku_id', 'pool_key', name='uq_inventory_allocation'),
        sa.CheckConstraint('quantity > 0', name='ck_allocation_qty'))
    # Historical order reservations are already included in reserved_qty; do not reserve again.
    import uuid
    conn = op.get_bind()
    rows = conn.execute(sa.text("""SELECT s.id, s.warehouse_id, s.order_id, o.shop_id,
        o.source_order_no, i.sku_id, SUM(i.quantity) AS quantity
        FROM shipment_orders s JOIN sales_orders o ON o.id=s.order_id
        JOIN shipment_order_items i ON i.shipment_id=s.id
        WHERE s.status='picking'
        GROUP BY s.id,s.warehouse_id,s.order_id,o.shop_id,o.source_order_no,i.sku_id""")).mappings()
    for row in rows:
        conn.execute(sa.text("""INSERT INTO inventory_allocations
            (id,created_at,updated_at,warehouse_id,sku_id,shop_id,pool_key,task_type,task_id,reference_no,quantity,status)
            VALUES (:id,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,:warehouse_id,:sku_id,:shop_id,'public','order',:order_id,:source_order_no,:quantity,'reserved')"""),
            dict(row, id=str(uuid.uuid4())))


def downgrade():
    op.drop_table('inventory_allocations')
    op.drop_table('inventory_ownership')
    op.drop_column('fba_plans', 'route_type')
