"""Add versioned LIM Skill governance records."""
from alembic import op
import sqlalchemy as sa


revision = '0034'
down_revision = '0033'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'lim_skills',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('skill_id', sa.String(length=64), nullable=False),
        sa.Column('display_name', sa.String(length=120), nullable=False),
        sa.Column('owner_id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('skill_id', name='uq_lim_skills_skill_id'),
    )
    op.create_index('ix_lim_skills_owner_id', 'lim_skills', ['owner_id'])
    op.create_index('ix_lim_skills_owner_name', 'lim_skills', ['owner_id', 'display_name'])

    op.create_table(
        'lim_skill_versions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('skill_id', sa.String(length=64), nullable=False),
        sa.Column('version', sa.String(length=32), nullable=False),
        sa.Column('memory_level', sa.String(length=16), nullable=False),
        sa.Column('definition', sa.JSON(), nullable=False),
        sa.Column('source_event', sa.String(length=200), nullable=False),
        sa.Column('evidence_refs', sa.JSON(), nullable=False),
        sa.Column('business_scope', sa.JSON(), nullable=False),
        sa.Column('last_verified_at', sa.DateTime(), nullable=True),
        sa.Column('confidence_calibration', sa.JSON(), nullable=False),
        sa.Column('usage_count', sa.Integer(), nullable=False),
        sa.Column('correction_count', sa.Integer(), nullable=False),
        sa.Column('expiry_policy', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('created_by', sa.String(length=36), nullable=False),
        sa.Column('reviewed_by', sa.String(length=36), nullable=True),
        sa.Column('activated_by', sa.String(length=36), nullable=True),
        sa.Column('transitioned_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('CANDIDATE','UNDER_REVIEW','VERIFIED','ACTIVE','DEGRADED','FROZEN','REVOKED')",
                           name='ck_lim_skill_versions_status'),
        sa.CheckConstraint("memory_level IN ('short_term','episodic','semantic','procedural')",
                           name='ck_lim_skill_versions_memory_level'),
        sa.CheckConstraint('usage_count >= 0 AND correction_count >= 0',
                           name='ck_lim_skill_versions_counts_nonnegative'),
        sa.ForeignKeyConstraint(['skill_id'], ['lim_skills.skill_id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['activated_by'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('skill_id', 'version', name='uq_lim_skill_versions_version'),
    )
    op.create_index('ix_lim_skill_versions_created_by', 'lim_skill_versions', ['created_by'])
    op.create_index('ix_lim_skill_versions_state', 'lim_skill_versions', ['status', 'updated_at'])
    op.create_index('uq_lim_skill_versions_one_active', 'lim_skill_versions', ['skill_id'], unique=True,
                    postgresql_where=sa.text("status = 'ACTIVE'"),
                    sqlite_where=sa.text("status = 'ACTIVE'"))


def downgrade():
    op.drop_index('uq_lim_skill_versions_one_active', table_name='lim_skill_versions')
    op.drop_index('ix_lim_skill_versions_state', table_name='lim_skill_versions')
    op.drop_index('ix_lim_skill_versions_created_by', table_name='lim_skill_versions')
    op.drop_table('lim_skill_versions')
    op.drop_index('ix_lim_skills_owner_name', table_name='lim_skills')
    op.drop_index('ix_lim_skills_owner_id', table_name='lim_skills')
    op.drop_table('lim_skills')
