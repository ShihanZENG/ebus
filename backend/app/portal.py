"""Permission-aware entry points for the employee workspace portal."""

import os

from fastapi import APIRouter, Depends, HTTPException

from .schemas import RESOURCE_NAMES
from .security import current_user, role_for, session_db

router = APIRouter(prefix='/api/v1/portal', tags=['企业门户'])

STOREFRONT_PUBLIC_URL = os.getenv('STOREFRONT_PUBLIC_URL', 'http://127.0.0.1:15174/').rstrip('/')
OMS_LOGIN_URL = 'http://127.0.0.1:3001/login'

ERP_ENTRY_ROUTES = (
    ('dashboard:read', '/dashboard'),
    ('products:read', '/products'),
    ('skus:read', '/skus'),
    ('orders:read', '/orders'),
    ('payment_records:read', '/finance-settlements'),
    ('customers:read', '/customers'),
    ('after_sales:read', '/after-sales'),
    ('customer_tickets:read', '/customer-tickets'),
    ('inventory:read', '/inventory'),
    ('inbound_orders:read', '/inbound'),
    ('shipments:read', '/shipments'),
    ('purchase_orders:read', '/purchase-orders'),
    ('purchase_receipts:read', '/receiving'),
    ('purchase_plans:read', '/purchase-plans'),
    ('purchase_amendments:read', '/purchase-amendments'),
    ('supplier_quotes:read', '/purchase-supplier-quotation'),
    ('replenishment:read', '/replenishment'),
    ('fba_plans:read', '/fba-overview'),
    ('listings:read', '/listings'),
    ('advertising_agent:read', '/dashboard'),
    ('finance_agent:read', '/finance-settlements'),
    ('purchase_agent:read', '/purchase-agent'),
    ('supplier_skus:read', '/supply-infos'),
    ('shops:read', '/shops'),
    ('warehouses:read', '/warehouses'),
    ('suppliers:read', '/suppliers'),
    ('dictionaries:read', '/dictionaries'),
    ('audit:read', '/audit-logs'),
    ('storefront:read', '/storefront'),
)


@router.get('/workspaces')
def list_workspaces(user=Depends(current_user), db=Depends(session_db)):
    role = role_for(db, user)
    if role is None:
        raise HTTPException(403, '账号角色不可用')
    is_admin = role.code == 'admin'
    permissions = set(role.permissions or [])

    items = []
    erp_route = '/dashboard' if is_admin or 'dashboard:read' in permissions else next(
        (path for permission, path in ERP_ENTRY_ROUTES if permission in permissions), None
    )
    if is_admin:
        erp_route = '/dashboard'
    erp_resources = set(RESOURCE_NAMES) - {'purchase_agent', 'purchase_agent_drafts'}
    has_erp_read = is_admin or bool(permissions.intersection(
        {f'{resource}:read' for resource in erp_resources} | {'audit:read', 'dashboard:read'}
    ))
    if has_erp_read:
        items.append({
            'id': 'erp',
            'name': 'ERP 业务系统',
            'description': '商品、订单、库存、采购与财务等业务数据和流程。',
            'deep_link': erp_route or '/dashboard',
            'identity_note': '由 ERP 权限控制。',
            'available': True,
            'external': False,
        })

    ai_permissions = {'assistant:read', 'purchase_agent:read'}
    if is_admin or permissions.intersection(ai_permissions):
        ai_route = '/ai-assistant' if is_admin or 'assistant:read' in permissions else '/purchase-agent'
        items.append({
            'id': 'ai',
            'name': 'AI 智能经营系统',
            'description': '经营诊断、专业 Agent 工作流与人工复核入口。',
            'deep_link': ai_route,
            'identity_note': 'AI 建议需结合证据和审批；不会直接替代业务系统提交操作。',
            'available': True,
            'external': False,
        })

    # LIM 控制台沿用 /lim-console 路由的既有守卫口径：admin 或 assistant:read。
    if is_admin or 'assistant:read' in permissions:
        items.append({
            'id': 'lim',
            'name': 'LIM 智能中间层',
            'description': 'Agent、模型、工具与安全治理的控制台。',
            'deep_link': '/lim-console',
            'identity_note': '工程治理入口，按运行与安全权限开放。',
            'available': True,
            'external': False,
        })

    # This is a login-page launcher, not a grant of OMS access or SSO.
    items.append({
        'id': 'oms',
        'name': '独立 OMS',
        'description': '独立 OMS 的订单、履约、售后与客户工作区。',
        'deep_link': OMS_LOGIN_URL,
        'identity_note': '新窗口打开，使用 OMS 账号独立登录；不传递 ERP 登录凭据。',
        'available': True,
        'external': True,
    })

    # Storefront 是公开消费者站点：入口不携带任何 ERP 凭证。
    items.append({
        'id': 'storefront',
        'name': 'Storefront 独立站',
        'description': '面向消费者的独立品牌商城。',
        'deep_link': STOREFRONT_PUBLIC_URL,
        'identity_note': '公开站点，与 ERP 身份隔离；新窗口打开且不携带登录凭据。',
        'available': True,
        'external': True,
    })

    return {'items': items}
