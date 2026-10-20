"""Give the existing default viewer access to advertising generation records."""

import sqlalchemy as sa
from alembic import op


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


roles = sa.table(
    'roles',
    sa.column('id', sa.String(36)),
    sa.column('code', sa.String(64)),
    sa.column('permissions', sa.JSON()),
)


def _change_viewer_permission(add):
    bind = op.get_bind()
    row = bind.execute(
        sa.select(roles.c.id, roles.c.permissions).where(roles.c.code == 'viewer')
    ).mappings().first()
    if not row:
        return
    permissions = set(row['permissions'] or [])
    if add:
        permissions.add('advertising_agent:read')
    else:
        permissions.discard('advertising_agent:read')
    bind.execute(
        sa.update(roles).where(roles.c.id == row['id']).values(permissions=sorted(permissions))
    )


def upgrade():
    _change_viewer_permission(add=True)


def downgrade():
    _change_viewer_permission(add=False)
