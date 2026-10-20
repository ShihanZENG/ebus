"""Purchase business evidence."""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('purchase_business_evidence',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('profile_id', sa.String(36), sa.ForeignKey('purchase_agent_profiles.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('scenario', sa.String(20), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False), sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('currency_id', sa.String(36), sa.ForeignKey('dictionaries.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('source_kind', sa.String(20), nullable=False), sa.Column('source_reference', sa.String(500), nullable=False),
        sa.Column('confirmed', sa.Boolean(), nullable=False), sa.Column('values', sa.JSON(), nullable=False),
        sa.Column('updated_by', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.UniqueConstraint('profile_id', 'scenario', name='uq_business_profile_scenario'))


def downgrade():
    op.drop_table('purchase_business_evidence')
