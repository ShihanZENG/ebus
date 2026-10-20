"""ERP identity and master data foundation."""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def identity():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def field(name, type_, **kwargs):
    return sa.Column(name, type_, nullable=False, **kwargs)


def code_name():
    return [field('code', sa.String(64), unique=True), field('name', sa.String(120))]


def active():
    return field('is_active', sa.Boolean())


def fk(name, target):
    return sa.Column(name, sa.String(36), sa.ForeignKey(target, ondelete='RESTRICT'), nullable=False)


def upgrade():
    op.create_table('roles', *identity(), *code_name(), field('permissions', sa.JSON()))
    op.create_table('users', *identity(), field('username', sa.String(64), unique=True),
                    field('password_hash', sa.String(256)), fk('role_id', 'roles.id'), active(),
                    sa.Column('shop_scope', sa.JSON(), nullable=True), sa.Column('warehouse_scope', sa.JSON(), nullable=True),
                    field('failed_attempts', sa.Integer()), sa.Column('locked_until', sa.DateTime(), nullable=True))
    op.create_table('auth_sessions', sa.Column('token_hash', sa.String(64), primary_key=True),
                    fk('user_id', 'users.id'), field('expires_at', sa.DateTime()), field('revoked', sa.Boolean()))
    op.create_index('ix_auth_sessions_user_id', 'auth_sessions', ['user_id'])
    op.create_table('dictionaries', *identity(), field('kind', sa.String(16)), field('code', sa.String(32)),
                    field('name', sa.String(120)), active(), sa.UniqueConstraint('kind', 'code'))
    op.create_table('products', *identity(), *code_name(), field('description', sa.String(2000)), fk('unit_id', 'dictionaries.id'), active())
    op.create_table('skus', *identity(), *code_name(), fk('product_id', 'products.id'), field('attributes', sa.JSON()), active())
    op.create_index('ix_skus_product_id', 'skus', ['product_id'])
    op.create_table('shops', *identity(), *code_name(), field('channel', sa.String(80)), field('market', sa.String(80)),
                    field('timezone', sa.String(80)), fk('currency_id', 'dictionaries.id'), active())
    op.create_table('warehouses', *identity(), *code_name(), field('warehouse_type', sa.String(16)),
                    field('country', sa.String(80)), field('address', sa.String(500)), active())
    op.create_table('suppliers', *identity(), *code_name(), field('contact_name', sa.String(120)),
                    field('phone', sa.String(80)), field('email', sa.String(254)), active())
    op.create_table('audit_logs', sa.Column('id', sa.String(36), primary_key=True), fk('actor_id', 'users.id'),
                    field('resource', sa.String(64)), field('record_id', sa.String(64)), field('action', sa.String(32)),
                    sa.Column('before', sa.JSON(), nullable=True), sa.Column('after', sa.JSON(), nullable=True),
                    field('created_at', sa.DateTime()))
    for column in ('actor_id', 'resource', 'created_at'):
        op.create_index(f'ix_audit_logs_{column}', 'audit_logs', [column])


def downgrade():
    for table in ('audit_logs', 'suppliers', 'warehouses', 'shops', 'skus', 'products', 'dictionaries', 'auth_sessions', 'users', 'roles'):
        op.drop_table(table)
