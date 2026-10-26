"""Add versioned LIM knowledge source snapshots and chunks."""
from alembic import op
import sqlalchemy as sa


revision = '0031'
down_revision = '0030'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'lim_knowledge_sources',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('source_id', sa.String(length=64), nullable=False),
        sa.Column('path', sa.String(length=500), nullable=False),
        sa.Column('display_name', sa.String(length=200), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('required_permissions', sa.JSON(), nullable=False),
        sa.Column('is_present', sa.Boolean(), nullable=False),
        sa.Column('is_archived', sa.Boolean(), nullable=False),
        sa.Column('owner_id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('path', name='uq_lim_knowledge_sources_path'),
        sa.UniqueConstraint('source_id', name='uq_lim_knowledge_sources_source_id'),
        sa.CheckConstraint('length(trim(display_name)) > 0', name='ck_lim_knowledge_sources_name_nonempty'),
    )
    op.create_index('ix_lim_knowledge_sources_owner_id', 'lim_knowledge_sources', ['owner_id'])
    op.create_index('ix_lim_knowledge_sources_archived_present', 'lim_knowledge_sources', ['is_archived', 'is_present'])

    op.create_table(
        'lim_knowledge_source_versions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('source_id', sa.String(length=64), nullable=False),
        sa.Column('version', sa.String(length=64), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('valid_from', sa.DateTime(), nullable=True),
        sa.Column('valid_until', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.String(length=36), nullable=False),
        sa.Column('reviewed_by', sa.String(length=36), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['source_id'], ['lim_knowledge_sources.source_id'], ondelete='RESTRICT',
                                name='fk_lim_knowledge_source_versions_source'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'version', name='uq_lim_knowledge_source_versions_version'),
        sa.CheckConstraint("status IN ('draft','active','archived')", name='ck_lim_knowledge_source_versions_status'),
        sa.CheckConstraint('valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from',
                           name='ck_lim_knowledge_source_versions_validity'),
    )
    op.create_index('ix_lim_knowledge_source_versions_created_by', 'lim_knowledge_source_versions', ['created_by'])
    op.create_index('ix_lim_knowledge_source_versions_status', 'lim_knowledge_source_versions', ['status', 'created_at'])
    op.create_index('uq_lim_knowledge_source_versions_one_active', 'lim_knowledge_source_versions', ['source_id'],
                    unique=True, sqlite_where=sa.text("status = 'active'"),
                    postgresql_where=sa.text("status = 'active'"))

    op.create_table(
        'lim_knowledge_chunks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('source_id', sa.String(length=64), nullable=False),
        sa.Column('version', sa.String(length=64), nullable=False),
        sa.Column('chunk_id', sa.String(length=64), nullable=False),
        sa.Column('section', sa.String(length=200), nullable=False),
        sa.Column('start_line', sa.Integer(), nullable=False),
        sa.Column('end_line', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['source_id', 'version'],
                                ['lim_knowledge_source_versions.source_id', 'lim_knowledge_source_versions.version'],
                                ondelete='RESTRICT', name='fk_lim_knowledge_chunks_version'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'version', 'chunk_id', name='uq_lim_knowledge_chunks_identity'),
        sa.CheckConstraint('start_line > 0 AND end_line >= start_line', name='ck_lim_knowledge_chunks_lines'),
    )
    op.create_index('ix_lim_knowledge_chunks_source_version', 'lim_knowledge_chunks', ['source_id', 'version'])


def downgrade():
    op.drop_index('ix_lim_knowledge_chunks_source_version', table_name='lim_knowledge_chunks')
    op.drop_table('lim_knowledge_chunks')
    op.drop_index('ix_lim_knowledge_source_versions_status', table_name='lim_knowledge_source_versions')
    op.drop_index('ix_lim_knowledge_source_versions_created_by', table_name='lim_knowledge_source_versions')
    op.drop_index('uq_lim_knowledge_source_versions_one_active', table_name='lim_knowledge_source_versions')
    op.drop_table('lim_knowledge_source_versions')
    op.drop_index('ix_lim_knowledge_sources_archived_present', table_name='lim_knowledge_sources')
    op.drop_index('ix_lim_knowledge_sources_owner_id', table_name='lim_knowledge_sources')
    op.drop_table('lim_knowledge_sources')
