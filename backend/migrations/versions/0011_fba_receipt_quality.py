"""Partial physical receipts and inspection before sellable inventory."""
import uuid
import sqlalchemy as sa
from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def record_columns():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def upgrade():
    op.add_column('fba_plans', sa.Column('difference_reason', sa.String(500), nullable=False, server_default=''))
    op.add_column('fba_plans', sa.Column('closed_at', sa.DateTime(), nullable=True))
    for name in ('received_qty', 'accepted_qty', 'rejected_qty'):
        op.add_column('fba_plan_items', sa.Column(name, sa.Integer(), nullable=False, server_default='0'))
    with op.batch_alter_table('fba_plan_items') as batch:
        batch.create_check_constraint('ck_fba_item_receipt_qty',
            'quantity >= received_qty AND received_qty >= accepted_qty + rejected_qty AND accepted_qty >= 0 AND rejected_qty >= 0')
    op.create_table('fba_receipts', *record_columns(),
        sa.Column('plan_id', sa.String(36), sa.ForeignKey('fba_plans.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('remark', sa.String(500), nullable=False),
        sa.Column('received_at', sa.DateTime(), nullable=False),
        sa.Column('inspected_at', sa.DateTime(), nullable=True))
    op.create_index('ix_fba_receipts_plan_id', 'fba_receipts', ['plan_id'])
    op.create_table('fba_receipt_items', *record_columns(),
        sa.Column('receipt_id', sa.String(36), sa.ForeignKey('fba_receipts.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('plan_item_id', sa.String(36), sa.ForeignKey('fba_plan_items.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('sku_id', sa.String(36), sa.ForeignKey('skus.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('accepted_qty', sa.Integer(), nullable=False),
        sa.Column('rejected_qty', sa.Integer(), nullable=False),
        sa.Column('dedicated_accepted_qty', sa.Integer(), nullable=False),
        sa.CheckConstraint('quantity >= accepted_qty + rejected_qty AND accepted_qty >= 0 AND rejected_qty >= 0',
                           name='ck_fba_receipt_item_qty'))
    op.create_index('ix_fba_receipt_items_receipt_id', 'fba_receipt_items', ['receipt_id'])
    op.create_index('ix_fba_receipt_items_plan_item_id', 'fba_receipt_items', ['plan_item_id'])
    conn = op.get_bind()
    # Old completed plans already credited their destination stock. Represent that past action
    # as an inspected receipt; never post inventory again during migration.
    completed = conn.execute(sa.text("""SELECT id, received_at, route_type FROM fba_plans
        WHERE status='received'""")).mappings().all()
    for plan in completed:
        receipt_id = str(uuid.uuid4())
        when = plan['received_at']
        conn.execute(sa.text("""INSERT INTO fba_receipts
            (id,created_at,updated_at,plan_id,status,remark,received_at,inspected_at)
            VALUES (:id,:when,:when,:plan_id,'inspected','升级前已全量签收的历史记录',:when,:when)"""),
            {'id': receipt_id, 'when': when, 'plan_id': plan['id']})
        items = conn.execute(sa.text("SELECT id,sku_id,quantity FROM fba_plan_items WHERE plan_id=:plan_id"),
                             {'plan_id': plan['id']}).mappings().all()
        for item in items:
            conn.execute(sa.text("""UPDATE fba_plan_items SET received_qty=quantity,accepted_qty=quantity
                WHERE id=:id"""), {'id': item['id']})
            conn.execute(sa.text("""INSERT INTO fba_receipt_items
                (id,created_at,updated_at,receipt_id,plan_item_id,sku_id,quantity,accepted_qty,rejected_qty,dedicated_accepted_qty)
                VALUES (:id,:when,:when,:receipt_id,:item_id,:sku_id,:qty,:qty,0,:dedicated)"""),
                {'id': str(uuid.uuid4()), 'when': when, 'receipt_id': receipt_id,
                 'item_id': item['id'], 'sku_id': item['sku_id'], 'qty': item['quantity'],
                 'dedicated': 0 if plan['route_type'] == 'domestic_to_overseas' else item['quantity']})


def downgrade():
    op.drop_index('ix_fba_receipt_items_plan_item_id', table_name='fba_receipt_items')
    op.drop_index('ix_fba_receipt_items_receipt_id', table_name='fba_receipt_items')
    op.drop_table('fba_receipt_items')
    op.drop_index('ix_fba_receipts_plan_id', table_name='fba_receipts')
    op.drop_table('fba_receipts')
    with op.batch_alter_table('fba_plan_items') as batch:
        batch.drop_constraint('ck_fba_item_receipt_qty', type_='check')
    for name in ('rejected_qty', 'accepted_qty', 'received_qty'):
        op.drop_column('fba_plan_items', name)
    op.drop_column('fba_plans', 'closed_at')
    op.drop_column('fba_plans', 'difference_reason')
