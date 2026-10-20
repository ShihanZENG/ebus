"""Add manually imported daily advertising reports."""
from alembic import op
import sqlalchemy as sa


revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ads_report_batches',
        sa.Column('shop_id', sa.String(length=36), nullable=False),
        sa.Column('actor_id', sa.String(length=36), nullable=False),
        sa.Column('source_name', sa.String(length=255), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('row_count', sa.Integer(), nullable=False),
        sa.Column('inserted_count', sa.Integer(), nullable=False),
        sa.Column('corrected_count', sa.Integer(), nullable=False),
        sa.Column('report_date_from', sa.Date(), nullable=False),
        sa.Column('report_date_to', sa.Date(), nullable=False),
        sa.Column('currencies', sa.JSON(), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shop_id', 'content_hash', name='uq_ads_report_batch_content'),
    )
    op.create_index('ix_ads_report_batches_shop_id', 'ads_report_batches', ['shop_id'])
    op.create_table(
        'ads_campaign_daily',
        sa.Column('shop_id', sa.String(length=36), nullable=False),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('campaign_id', sa.String(length=120), nullable=False),
        sa.Column('campaign_name', sa.String(length=255), nullable=False),
        sa.Column('campaign_status', sa.String(length=80), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('spend', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('impressions', sa.Integer(), nullable=False),
        sa.Column('clicks', sa.Integer(), nullable=False),
        sa.Column('orders', sa.Integer(), nullable=False),
        sa.Column('attributed_sales', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('sku_code', sa.String(length=64), nullable=True),
        sa.Column('latest_batch_id', sa.String(length=36), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('attributed_sales >= 0', name='ck_ads_campaign_daily_sales_nonnegative'),
        sa.CheckConstraint('clicks >= 0 AND impressions >= 0 AND orders >= 0',
                           name='ck_ads_campaign_daily_counts_nonnegative'),
        sa.CheckConstraint('spend >= 0', name='ck_ads_campaign_daily_spend_nonnegative'),
        sa.ForeignKeyConstraint(['latest_batch_id'], ['ads_report_batches.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shop_id', 'report_date', 'campaign_id', 'currency',
                            name='uq_ads_campaign_daily_key'),
    )
    op.create_index('ix_ads_campaign_daily_report_date', 'ads_campaign_daily', ['report_date'])
    op.create_index('ix_ads_campaign_daily_shop_id', 'ads_campaign_daily', ['shop_id'])
    op.create_index('ix_ads_campaign_daily_sku_code', 'ads_campaign_daily', ['sku_code'])


def downgrade():
    op.drop_index('ix_ads_campaign_daily_sku_code', table_name='ads_campaign_daily')
    op.drop_index('ix_ads_campaign_daily_shop_id', table_name='ads_campaign_daily')
    op.drop_index('ix_ads_campaign_daily_report_date', table_name='ads_campaign_daily')
    op.drop_table('ads_campaign_daily')
    op.drop_index('ix_ads_report_batches_shop_id', table_name='ads_report_batches')
    op.drop_table('ads_report_batches')
