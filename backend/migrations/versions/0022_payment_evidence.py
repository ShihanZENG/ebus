"""Add payment evidence metadata, fee and reconciliation state."""
from alembic import op
import sqlalchemy as sa


revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('payment_records', sa.Column('fee_amount', sa.Numeric(12, 2), nullable=False,
                                               server_default='0'))
    op.add_column('payment_records', sa.Column('record_type', sa.String(20), nullable=False,
                                               server_default='legacy'))
    op.add_column('payment_records', sa.Column('reconciliation_status', sa.String(20), nullable=False,
                                               server_default='legacy'))
    op.add_column('payment_records', sa.Column('evidence_name', sa.String(255), nullable=True))
    op.add_column('payment_records', sa.Column('evidence_key', sa.String(80), nullable=True))
    op.add_column('payment_records', sa.Column('evidence_content_type', sa.String(80), nullable=True))
    op.add_column('payment_records', sa.Column('evidence_size', sa.Integer(), nullable=True))
    op.add_column('payment_records', sa.Column('evidence_sha256', sa.String(64), nullable=True))
    op.add_column('payment_records', sa.Column('verified_at', sa.DateTime(), nullable=True))
    op.add_column('payment_records', sa.Column('verified_by', sa.String(36), nullable=True))
    with op.batch_alter_table('payment_records') as batch:
        batch.alter_column('source', existing_type=sa.String(40), type_=sa.String(120), existing_nullable=False)
        batch.create_foreign_key('fk_payment_records_verified_by_users', 'users', ['verified_by'], ['id'],
                                 ondelete='RESTRICT')
        batch.create_unique_constraint('uq_payment_records_evidence_key', ['evidence_key'])

    # Backfill only the one demo record whose source and remark both identify it as simulated.
    op.execute(sa.text(
        "UPDATE payment_records SET record_type='simulated', reconciliation_status='not_required' "
        "WHERE source='SIM-SETTLEMENT-IMP-001' AND remark LIKE '%非真实收款凭据%'"
    ))


def downgrade():
    with op.batch_alter_table('payment_records') as batch:
        batch.drop_constraint('uq_payment_records_evidence_key', type_='unique')
        batch.drop_constraint('fk_payment_records_verified_by_users', type_='foreignkey')
        batch.alter_column('source', existing_type=sa.String(120), type_=sa.String(40), existing_nullable=False)
        batch.drop_column('verified_by')
        batch.drop_column('verified_at')
        batch.drop_column('evidence_sha256')
        batch.drop_column('evidence_size')
        batch.drop_column('evidence_content_type')
        batch.drop_column('evidence_key')
        batch.drop_column('evidence_name')
        batch.drop_column('reconciliation_status')
        batch.drop_column('record_type')
        batch.drop_column('fee_amount')
