"""OMS lifecycle: three-dimension order states, events, reservations, routing, exceptions, logistics, rules."""
from alembic import op
import sqlalchemy as sa

revision = '0044'
down_revision = '0043'
branch_labels = None
depends_on = None


def record_columns():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def upgrade():
    # 1) 订单三维状态 + 存量回填（旧 status 保留为派生兼容字段）
    op.add_column('sales_orders', sa.Column('order_status', sa.String(20), nullable=False, server_default='created'))
    op.add_column('sales_orders', sa.Column('payment_status', sa.String(24), nullable=False, server_default='unpaid'))
    op.add_column('sales_orders', sa.Column('fulfillment_status', sa.String(24), nullable=False, server_default='unallocated'))
    op.execute("""
        UPDATE sales_orders SET
          order_status = CASE
            WHEN status = 'draft' THEN 'created'
            WHEN status = 'cancelled' THEN 'cancelled'
            ELSE 'confirmed' END
    """)
    op.execute("""
        UPDATE sales_orders SET fulfillment_status = 'shipped'
        WHERE EXISTS (SELECT 1 FROM shipment_orders
                      WHERE shipment_orders.order_id = sales_orders.id
                        AND shipment_orders.status = 'shipped')
    """)
    op.execute("""
        UPDATE sales_orders SET fulfillment_status = 'allocated'
        WHERE fulfillment_status = 'unallocated'
          AND EXISTS (SELECT 1 FROM shipment_orders
                      WHERE shipment_orders.order_id = sales_orders.id
                        AND shipment_orders.status = 'picking')
    """)
    op.execute("""
        UPDATE sales_orders SET payment_status = 'pending'
        WHERE EXISTS (SELECT 1 FROM payment_records WHERE payment_records.order_id = sales_orders.id)
    """)
    op.execute("""
        UPDATE sales_orders SET payment_status = 'paid'
        WHERE EXISTS (SELECT 1 FROM payment_records WHERE payment_records.order_id = sales_orders.id)
          AND (SELECT COALESCE(SUM(payment_records.amount), 0) FROM payment_records
               WHERE payment_records.order_id = sales_orders.id) >= sales_orders.grand_total
    """)
    op.create_index('ix_sales_orders_order_status', 'sales_orders', ['order_status'])
    op.create_index('ix_sales_orders_payment_status', 'sales_orders', ['payment_status'])
    op.create_index('ix_sales_orders_fulfillment_status', 'sales_orders', ['fulfillment_status'])

    # 2) 出库单：履约阶段与承运商
    op.add_column('shipment_orders', sa.Column('stage', sa.String(12), nullable=False, server_default='pick'))
    op.add_column('shipment_orders', sa.Column('carrier', sa.String(80), nullable=False, server_default=''))
    op.add_column('shipment_orders', sa.Column('packed_at', sa.DateTime(), nullable=True))
    op.create_index('ix_shipment_orders_stage', 'shipment_orders', ['stage'])
    op.execute("UPDATE shipment_orders SET stage = 'ship' WHERE status = 'shipped'")

    # 3) 渠道同步任务：重试链与逐单明细
    op.add_column('channel_sync_jobs', sa.Column('detail', sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    with op.batch_alter_table('channel_sync_jobs') as batch_op:
        batch_op.add_column(sa.Column('retry_of_job_id', sa.String(36),
                                      sa.ForeignKey('channel_sync_jobs.id', ondelete='SET NULL',
                                                    name='fk_channel_sync_jobs_retry_of_job_id'), nullable=True))
    op.add_column('channel_sync_jobs', sa.Column('attempt_no', sa.Integer(), nullable=False, server_default='1'))
    op.create_index('ix_channel_sync_jobs_retry_of_job_id', 'channel_sync_jobs', ['retry_of_job_id'])

    # 4) 订单事件时间线
    op.create_table('order_events', *record_columns(),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('sales_orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(40), nullable=False),
        sa.Column('dimension', sa.String(24), nullable=True),
        sa.Column('from_value', sa.String(24), nullable=True),
        sa.Column('to_value', sa.String(24), nullable=True),
        sa.Column('source', sa.String(40), nullable=False, server_default='erp'),
        sa.Column('message', sa.String(500), nullable=False, server_default=''),
        sa.Column('payload', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('idempotency_key', sa.String(160), nullable=True),
        sa.UniqueConstraint('order_id', 'idempotency_key', name='uq_order_event_idempotency'))
    op.create_index('ix_order_events_order_id', 'order_events', ['order_id'])
    op.create_index('ix_order_events_event_type', 'order_events', ['event_type'])
    op.create_index('ix_order_events_actor_id', 'order_events', ['actor_id'])

    # 5) 订单库存预留记录
    op.create_table('order_reservations', *record_columns(),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('sales_orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('warehouse_id', sa.String(36), sa.ForeignKey('warehouses.id', ondelete='SET NULL'), nullable=True),
        sa.Column('shipment_id', sa.String(36), sa.ForeignKey('shipment_orders.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='reserved'),
        sa.Column('lines', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('error', sa.String(500), nullable=False, server_default=''),
        sa.Column('idempotency_key', sa.String(160), nullable=True),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('changed_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('idempotency_key', name='uq_order_reservation_idempotency'))
    op.create_index('ix_order_reservations_order_id', 'order_reservations', ['order_id'])
    op.create_index('ix_order_reservations_warehouse_id', 'order_reservations', ['warehouse_id'])
    op.create_index('ix_order_reservations_status', 'order_reservations', ['status'])

    # 6) 路由规则与路由决策
    op.create_table('routing_rules', *record_columns(),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('warehouse_id', sa.String(36), sa.ForeignKey('warehouses.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('countries', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('shop_ids', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('channel_codes', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('conditions', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('remark', sa.String(500), nullable=False, server_default=''))
    op.create_index('ix_routing_rules_priority', 'routing_rules', ['priority'])
    op.create_index('ix_routing_rules_warehouse_id', 'routing_rules', ['warehouse_id'])
    op.create_table('routing_decisions', *record_columns(),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('sales_orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('rule_id', sa.String(36), sa.ForeignKey('routing_rules.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='auto'),
        sa.Column('warehouse_id', sa.String(36), sa.ForeignKey('warehouses.id', ondelete='SET NULL'), nullable=True),
        sa.Column('allocations', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('reason', sa.String(500), nullable=False, server_default=''))
    op.create_index('ix_routing_decisions_order_id', 'routing_decisions', ['order_id'])

    # 7) 异常订单工单
    op.create_table('order_exceptions', *record_columns(),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('sales_orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('exception_type', sa.String(32), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='open'),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('detail', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('resolution', sa.String(500), nullable=False, server_default=''),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('assignee_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('detected_by', sa.String(24), nullable=False, server_default='system'))
    op.create_index('ix_order_exceptions_order_id', 'order_exceptions', ['order_id'])
    op.create_index('ix_order_exceptions_exception_type', 'order_exceptions', ['exception_type'])
    op.create_index('ix_order_exceptions_status', 'order_exceptions', ['status'])
    op.create_index('ix_order_exceptions_assignee_id', 'order_exceptions', ['assignee_id'])

    # 8) 物流节点事件
    op.create_table('logistics_events', *record_columns(),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('sales_orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('shipment_id', sa.String(36), sa.ForeignKey('shipment_orders.id', ondelete='SET NULL'), nullable=True),
        sa.Column('tracking_no', sa.String(120), nullable=False, server_default=''),
        sa.Column('carrier', sa.String(80), nullable=False, server_default=''),
        sa.Column('event_code', sa.String(40), nullable=False),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.Column('source', sa.String(24), nullable=False, server_default='manual'),
        sa.Column('message', sa.String(500), nullable=False, server_default=''),
        sa.Column('dedup_key', sa.String(160), nullable=True),
        sa.UniqueConstraint('dedup_key', name='uq_logistics_event_dedup'))
    op.create_index('ix_logistics_events_order_id', 'logistics_events', ['order_id'])
    op.create_index('ix_logistics_events_shipment_id', 'logistics_events', ['shipment_id'])
    op.create_index('ix_logistics_events_tracking_no', 'logistics_events', ['tracking_no'])
    op.create_index('ix_logistics_events_event_code', 'logistics_events', ['event_code'])

    # 9) 订单规则配置
    op.create_table('order_rule_configs', *record_columns(),
        sa.Column('key', sa.String(64), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('description', sa.String(500), nullable=False, server_default=''),
        sa.Column('updated_by', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_order_rule_configs_key', 'order_rule_configs', ['key'], unique=True)


def downgrade():
    op.drop_table('order_rule_configs')
    op.drop_table('logistics_events')
    op.drop_table('order_exceptions')
    op.drop_table('routing_decisions')
    op.drop_table('routing_rules')
    op.drop_table('order_reservations')
    op.drop_table('order_events')
    with op.batch_alter_table('channel_sync_jobs') as batch_op:
        batch_op.drop_index('ix_channel_sync_jobs_retry_of_job_id')
        batch_op.drop_column('attempt_no')
        batch_op.drop_column('retry_of_job_id')
        batch_op.drop_column('detail')
    with op.batch_alter_table('shipment_orders') as batch_op:
        batch_op.drop_index('ix_shipment_orders_stage')
        batch_op.drop_column('packed_at')
        batch_op.drop_column('carrier')
        batch_op.drop_column('stage')
    with op.batch_alter_table('sales_orders') as batch_op:
        batch_op.drop_index('ix_sales_orders_fulfillment_status')
        batch_op.drop_index('ix_sales_orders_payment_status')
        batch_op.drop_index('ix_sales_orders_order_status')
        batch_op.drop_column('fulfillment_status')
        batch_op.drop_column('payment_status')
        batch_op.drop_column('order_status')
