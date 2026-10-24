from types import SimpleNamespace
from app.portal import list_workspaces


def test_portal_opens_oms_login_without_forwarding_erp_identity():
    role = SimpleNamespace(code='viewer', permissions=[])
    db = SimpleNamespace(get=lambda model, ident: role)
    user = SimpleNamespace(role_id='viewer', id='erp-user-not-an-oms-identity')
    oms = next(x for x in list_workspaces(user=user, db=db)['items'] if x['id'] == 'oms')
    assert oms['available'] is True
    assert oms['external'] is True
    assert oms['deep_link'] == 'http://127.0.0.1:3001/login'
    assert '独立登录' in oms['identity_note']
    assert user.id not in oms['deep_link']
    assert '?' not in oms['deep_link'] and '#' not in oms['deep_link']
