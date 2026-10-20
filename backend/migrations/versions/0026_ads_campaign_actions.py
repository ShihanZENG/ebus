"""Save review outcomes and notes for daily ad campaigns."""
from alembic import op
import sqlalchemy as sa


revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ads_campaign_actions',
        sa.Column('shop_id', sa.String(length=36), nullable=False),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('campaign_id', sa.String(length=120), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('action_status', sa.String(length=20), nullable=False),
        sa.Column('note', sa.String(length=1000), nullable=False),
        sa.Column('actor_id', sa.String(length=36), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("action_status IN ('pending', 'checked', 'watching', 'adjusted')",
                           name='ck_ads_campaign_action_status'),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shop_id', 'report_date', 'campaign_id', 'currency',
                            name='uq_ads_campaign_action_daily'),
    )
    op.create_index('ix_ads_campaign_actions_shop_id', 'ads_campaign_actions', ['shop_id'])


def downgrade():
    op.drop_index('ix_ads_campaign_actions_shop_id', table_name='ads_campaign_actions')
    op.drop_table('ads_campaign_actions')
