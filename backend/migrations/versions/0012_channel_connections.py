"""Multi-platform channel connections, sync jobs, SKU mappings and order mirrors."""
import sqlalchemy as sa
from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def record_columns():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def upgrade():
    op.create_table('channel_connections', *record_columns(),
        sa.Column('shop_id', sa.String(36), sa.ForeignKey('shops.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('channel_code', sa.String(32), nullable=False),
        sa.Column('sync_mode', sa.String(16), nullable=False, server_default='polling'),
        sa.Column('status', sa.String(16), nullable=False, server_default='enabled'),
        sa.Column('settings', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('credential_ref', sa.String(120), nullable=False, server_default=''),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.String(500), nullable=False, server_default=''),
        sa.Column('remark', sa.String(500), nullable=False, server_default=''),
        sa.UniqueConstraint('shop_id', 'channel_code', name='uq_channel_shop'))
    op.create_index('ix_channel_connections_shop_id', 'channel_connections', ['shop_id'])
    op.create_index('ix_channel_connections_channel_code', 'channel_connections', ['channel_code'])

    op.create_table('channel_sync_jobs', *record_columns(),
        sa.Column('connection_id', sa.String(36), sa.ForeignKey('channel_connections.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('trigger', sa.String(20), nullable=False, server_default='manual'),
        sa.Column('status', sa.String(20), nullable=False, server_default='running'),
        sa.Column('fetched_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('skipped_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.String(1000), nullable=False, server_default=''),
        sa.CheckConstraint('fetched_count >= 0 AND created_count >= 0 AND skipped_count >= 0 AND error_count >= 0',
                           name='ck_sync_job_counts'))
    op.create_index('ix_channel_sync_jobs_connection_id', 'channel_sync_jobs', ['connection_id'])
    op.create_index('ix_channel_sync_jobs_status', 'channel_sync_jobs', ['status'])

    op.create_table('channel_sku_mappings', *record_columns(),
        sa.Column('connection_id', sa.String(36), sa.ForeignKey('channel_connections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('external_sku', sa.String(120), nullable=False),
        sa.Column('sku_id', sa.String(36), sa.ForeignKey('skus.id', ondelete='RESTRICT'), nullable=False),
        sa.UniqueConstraint('connection_id', 'external_sku', name='uq_channel_sku'))
    op.create_index('ix_channel_sku_mappings_connection_id', 'channel_sku_mappings', ['connection_id'])
    op.create_index('ix_channel_sku_mappings_sku_id', 'channel_sku_mappings', ['sku_id'])

    op.create_table('channel_order_records', *record_columns(),
        sa.Column('connection_id', sa.String(36), sa.ForeignKey('channel_connections.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('shop_id', sa.String(36), sa.ForeignKey('shops.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('channel_code', sa.String(32), nullable=False),
        sa.Column('source_order_no', sa.String(120), nullable=False),
        sa.Column('external_status', sa.String(40), nullable=False, server_default=''),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('sales_orders.id', ondelete='SET NULL'), nullable=True),
        sa.Column('sync_job_id', sa.String(36), sa.ForeignKey('channel_sync_jobs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('raw_payload', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('last_synced_at', sa.DateTime(), nullable=False),
        sa.Column('push_shipment_status', sa.String(20), nullable=False, server_default='none'),
        sa.Column('tracking_no', sa.String(120), nullable=False, server_default=''),
        sa.Column('last_error', sa.String(500), nullable=False, server_default=''),
        sa.UniqueConstraint('connection_id', 'source_order_no', name='uq_channel_order'))
    op.create_index('ix_channel_order_records_connection_id', 'channel_order_records', ['connection_id'])
    op.create_index('ix_channel_order_records_shop_id', 'channel_order_records', ['shop_id'])
    op.create_index('ix_channel_order_records_order_id', 'channel_order_records', ['order_id'])


def downgrade():
    op.drop_index('ix_channel_order_records_order_id', table_name='channel_order_records')
    op.drop_index('ix_channel_order_records_shop_id', table_name='channel_order_records')
    op.drop_index('ix_channel_order_records_connection_id', table_name='channel_order_records')
    op.drop_table('channel_order_records')
    op.drop_index('ix_channel_sku_mappings_sku_id', table_name='channel_sku_mappings')
    op.drop_index('ix_channel_sku_mappings_connection_id', table_name='channel_sku_mappings')
    op.drop_table('channel_sku_mappings')
    op.drop_index('ix_channel_sync_jobs_status', table_name='channel_sync_jobs')
    op.drop_index('ix_channel_sync_jobs_connection_id', table_name='channel_sync_jobs')
    op.drop_table('channel_sync_jobs')
    op.drop_index('ix_channel_connections_channel_code', table_name='channel_connections')
    op.drop_index('ix_channel_connections_shop_id', table_name='channel_connections')
    op.drop_table('channel_connections')
