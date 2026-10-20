import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Card, Checkbox, Col, Descriptions, Divider, Drawer, Form, Input,
  message, Modal, Row, Select, Space, Switch, Table, Tabs, Tag, Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined, ReloadOutlined, SearchOutlined, TeamOutlined, UserOutlined } from '@ant-design/icons'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

interface Role { id: string; code: string; name: string; permissions: string[] }
interface UserRow {
  id: string; username: string; role_id: string; is_active: boolean
  shop_scope: string[] | null; warehouse_scope: string[] | null
  created_at: string; updated_at: string
}
interface ListResult<T> { items: T[]; total?: number }
interface ScopeItem { id: string; code: string; name: string }
interface RoleForm { code: string; name: string; permissions: string[] }
interface CreateUserForm { username: string; password: string; role_id: string; is_active: boolean; shop_scope: string[] | null; warehouse_scope: string[] | null }

const PERMISSION_LABELS: Record<string, string> = {
  products: '商品', skus: 'SKU', shops: '店铺', warehouses: '仓库', suppliers: '供应商',
  supply_infos: '供货信息', dictionaries: '数据字典', orders: '订单', after_sales: '售后',
  inventory: '库存', purchase_orders: '采购单', audit: '操作日志', users: '账号', roles: '角色',
}
const ACTION_LABELS: Record<string, string> = { read: '查看', write: '新增与修改' }

function permissionGroups(permissions: string[]) {
  const groups = new Map<string, string[]>()
  for (const permission of permissions) {
    const [resource, action] = permission.split(':')
    if (!resource || !action) continue
    groups.set(resource, [...(groups.get(resource) ?? []), permission])
  }
  return [...groups.entries()].sort(([a], [b]) => (PERMISSION_LABELS[a] ?? a).localeCompare(PERMISSION_LABELS[b] ?? b, 'zh-CN'))
}

function scopeLabel(ids: string[] | null, options: ScopeItem[]) {
  if (ids === null) return '全部范围'
  if (!ids.length) return '未分配'
  const names = ids.map((id) => options.find((item) => item.id === id)?.name ?? id)
  return names.length > 3 ? `${names.slice(0, 3).join('、')} 等 ${names.length} 项` : names.join('、')
}

/** 管理员专用账号与角色管理。所有密码只在表单提交时发送，页面不读取或保存密码。 */
export default function UsersPage() {
  const { user: currentUser } = useAuth()
  const [activeTab, setActiveTab] = useState('users')
  const [users, setUsers] = useState<UserRow[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [permissions, setPermissions] = useState<string[]>([])
  const [shops, setShops] = useState<ScopeItem[]>([])
  const [warehouses, setWarehouses] = useState<ScopeItem[]>([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [userModal, setUserModal] = useState(false)
  const [roleModal, setRoleModal] = useState(false)
  const [editingRole, setEditingRole] = useState<Role | null>(null)
  const [detail, setDetail] = useState<UserRow | null>(null)
  const [resetTarget, setResetTarget] = useState<UserRow | null>(null)
  const [userForm] = Form.useForm<CreateUserForm>()
  const [roleForm] = Form.useForm<RoleForm>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [userResult, roleResult, permissionResult, shopResult, warehouseResult] = await Promise.all([
        request<ListResult<UserRow>>('/users', { params: { page: 1, page_size: 100 } }),
        request<ListResult<Role>>('/roles'),
        request<ListResult<string>>('/permissions'),
        request<ListResult<ScopeItem>>('/shops', { params: { page: 1, page_size: 100 } }),
        request<ListResult<ScopeItem>>('/warehouses', { params: { page: 1, page_size: 100 } }),
      ])
      setUsers(userResult.items)
      setRoles(roleResult.items)
      setPermissions(permissionResult.items)
      setShops(shopResult.items)
      setWarehouses(warehouseResult.items)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '账号数据加载失败')
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])

  const roleById = useMemo(() => new Map(roles.map((role) => [role.id, role])), [roles])
  const filteredUsers = useMemo(() => {
    const q = search.trim().toLocaleLowerCase()
    return q ? users.filter((item) => item.username.toLocaleLowerCase().includes(q) || (roleById.get(item.role_id)?.name ?? '').toLocaleLowerCase().includes(q)) : users
  }, [users, search, roleById])
  const sortedPermissions = useMemo(() => [...permissions].sort(), [permissions])

  const createUser = async (values: CreateUserForm) => {
    try {
      await request<UserRow>('/users', { method: 'POST', body: values })
      message.success('账号已创建')
      setUserModal(false)
      userForm.resetFields()
      await load()
    } catch (err) { message.error(err instanceof Error ? err.message : '创建账号失败') }
  }

  const saveUser = async (row: UserRow, patch: Partial<UserRow>) => {
    try {
      const updated = await request<UserRow>(`/users/${row.id}`, { method: 'PATCH', body: patch })
      setUsers((items) => items.map((item) => item.id === row.id ? updated : item))
      setDetail((item) => item?.id === row.id ? updated : item)
      message.success('账号设置已更新')
    } catch (err) { message.error(err instanceof Error ? err.message : '更新账号失败'); await load() }
  }

  const saveRole = async (values: RoleForm) => {
    try {
      const role = editingRole
        ? await request<Role>(`/roles/${editingRole.id}`, { method: 'PUT', body: values })
        : await request<Role>('/roles', { method: 'POST', body: values })
      setRoles((items) => editingRole ? items.map((item) => item.id === role.id ? role : item) : [...items, role])
      message.success(editingRole ? '角色已更新' : '角色已创建')
      setRoleModal(false); setEditingRole(null); roleForm.resetFields()
    } catch (err) { message.error(err instanceof Error ? err.message : '保存角色失败') }
  }

  const resetPassword = async (values: { password: string; confirm: string }) => {
    if (!resetTarget) return
    try {
      await request<void>(`/users/${resetTarget.id}/password`, { method: 'PUT', body: { password: values.password } })
      message.success('密码已重置；该账号的其他登录会话已失效')
      setResetTarget(null)
    } catch (err) { message.error(err instanceof Error ? err.message : '重置密码失败') }
  }

  const userColumns: ColumnsType<UserRow> = [
    { title: '账号', dataIndex: 'username', width: 200, render: (value: string, row) => <Button type="link" style={{ padding: 0 }} onClick={() => setDetail(row)}><UserOutlined /> {value}</Button> },
    { title: '角色', width: 160, render: (_, row) => roleById.get(row.role_id)?.name ?? '未知角色' },
    { title: '店铺范围', width: 210, render: (_, row) => scopeLabel(row.shop_scope, shops) },
    { title: '仓库范围', width: 210, render: (_, row) => scopeLabel(row.warehouse_scope, warehouses) },
    { title: '状态', dataIndex: 'is_active', width: 100, render: (active: boolean) => <Tag color={active ? 'green' : 'default'}>{active ? '启用' : '停用'}</Tag> },
    { title: '创建时间', dataIndex: 'created_at', width: 175, render: (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false }) },
    { title: '操作', fixed: 'right', width: 230, render: (_, row) => <Space size={4}>
      <Select size="small" value={row.role_id} style={{ width: 120 }} disabled={roleById.get(row.role_id)?.code === 'admin'} options={roles.filter((role) => role.code !== 'admin').map((role) => ({ label: role.name, value: role.id }))} onChange={(role_id) => void saveUser(row, { role_id })} />
      <Button size="small" onClick={() => setResetTarget(row)}>重置密码</Button>
      <Switch size="small" checked={row.is_active} disabled={row.id === currentUser?.id} checkedChildren="启用" unCheckedChildren="停用" onChange={(is_active) => void saveUser(row, { is_active })} />
    </Space> },
  ]

  const roleColumns: ColumnsType<Role> = [
    { title: '角色名称', dataIndex: 'name', width: 180 },
    { title: '角色编码', dataIndex: 'code', width: 180, render: (code: string) => <Tag>{code}</Tag> },
    { title: '权限', dataIndex: 'permissions', render: (items: string[]) => <Space wrap>{items.length ? items.map((permission) => <Tag key={permission} color="blue">{permission}</Tag>) : <Typography.Text type="secondary">暂无权限</Typography.Text>}</Space> },
    { title: '操作', width: 120, render: (_, role) => role.code === 'admin'
      ? <Typography.Text type="secondary">系统内置</Typography.Text>
      : <Button type="link" onClick={() => { setEditingRole(role); roleForm.setFieldsValue(role); setRoleModal(true) }}>编辑权限</Button> },
  ]

  return <Space direction="vertical" size={16} style={{ display: 'flex' }}>
    <Row gutter={16}>
      <Col xs={24} md={8}><Card bordered={false}><Space><TeamOutlined style={{ fontSize: 22, color: '#2b5cff' }} /><div><Typography.Text type="secondary">账号总数</Typography.Text><div><Typography.Title level={3} style={{ margin: 0 }}>{users.length}</Typography.Title></div></div></Space></Card></Col>
      <Col xs={24} md={8}><Card bordered={false}><Space><UserOutlined style={{ fontSize: 22, color: '#13a8a8' }} /><div><Typography.Text type="secondary">已启用</Typography.Text><div><Typography.Title level={3} style={{ margin: 0 }}>{users.filter((item) => item.is_active).length}</Typography.Title></div></div></Space></Card></Col>
      <Col xs={24} md={8}><Card bordered={false}><Space><TeamOutlined style={{ fontSize: 22, color: '#8b5cf6' }} /><div><Typography.Text type="secondary">自定义角色</Typography.Text><div><Typography.Title level={3} style={{ margin: 0 }}>{roles.filter((item) => item.code !== 'admin').length}</Typography.Title></div></div></Space></Card></Col>
    </Row>
    <Card bordered={false}>
      <Space direction="vertical" size={16} style={{ display: 'flex' }}>
        <Row align="middle" justify="space-between" gutter={[12, 12]}>
          <Col><Space direction="vertical" size={0}><Typography.Title level={4} style={{ margin: 0 }}>账号与角色</Typography.Title><Typography.Text type="secondary">管理系统登录账号、角色权限和店铺/仓库数据范围</Typography.Text></Space></Col>
          <Col><Space wrap>
            {activeTab === 'users' && <Input allowClear prefix={<SearchOutlined />} placeholder="搜索账号或角色" value={search} onChange={(event) => setSearch(event.target.value)} style={{ width: 210 }} />}
            <Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => activeTab === 'users' ? (userForm.resetFields(), userForm.setFieldsValue({ is_active: true, shop_scope: [], warehouse_scope: [] }), setUserModal(true)) : (setEditingRole(null), roleForm.resetFields(), setRoleModal(true))}>{activeTab === 'users' ? '新建账号' : '新建角色'}</Button>
          </Space></Col>
        </Row>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          { key: 'users', label: `账号 (${users.length})`, children: <Table<UserRow> rowKey="id" size="middle" loading={loading} dataSource={filteredUsers} columns={userColumns} scroll={{ x: 1180 }} pagination={{ pageSize: 10, showTotal: (total) => `共 ${total} 个账号` }} /> },
          { key: 'roles', label: `角色 (${roles.length})`, children: <Table<Role> rowKey="id" size="middle" loading={loading} dataSource={roles} columns={roleColumns} pagination={{ pageSize: 10, showTotal: (total) => `共 ${total} 个角色` }} /> },
        ]} />
      </Space>
    </Card>

    <Modal title="新建账号" open={userModal} onCancel={() => setUserModal(false)} onOk={() => userForm.submit()} okText="创建账号" cancelText="取消" destroyOnClose>
      <Form form={userForm} layout="vertical" onFinish={createUser} initialValues={{ is_active: true, shop_scope: [], warehouse_scope: [] }}>
        <Form.Item name="username" label="登录账号" rules={[{ required: true }, { max: 64 }]}><Input autoComplete="off" /></Form.Item>
        <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 8, max: 128 }]}><Input.Password autoComplete="new-password" /></Form.Item>
        <Form.Item name="role_id" label="角色" rules={[{ required: true }]}><Select placeholder="选择角色" options={roles.filter((role) => role.code !== 'admin').map((role) => ({ label: role.name, value: role.id }))} /></Form.Item>
        <Form.Item name="shop_scope" label="店铺数据范围"><Select mode="multiple" allowClear placeholder="留空表示暂不分配店铺" options={shops.map((item) => ({ label: `${item.name}（${item.code}）`, value: item.id }))} /></Form.Item>
        <Form.Item name="warehouse_scope" label="仓库数据范围"><Select mode="multiple" allowClear placeholder="留空表示暂不分配仓库" options={warehouses.map((item) => ({ label: `${item.name}（${item.code}）`, value: item.id }))} /></Form.Item>
        <Form.Item name="is_active" label="账号状态" valuePropName="checked"><Switch checkedChildren="启用" unCheckedChildren="停用" /></Form.Item>
      </Form>
    </Modal>

    <Modal title={editingRole ? `编辑角色 · ${editingRole.name}` : '新建角色'} open={roleModal} width={760} onCancel={() => { setRoleModal(false); setEditingRole(null) }} onOk={() => roleForm.submit()} okText="保存" cancelText="取消" destroyOnClose>
      <Form form={roleForm} layout="vertical" onFinish={saveRole}>
        <Row gutter={16}><Col span={10}><Form.Item name="code" label="角色编码" rules={[{ required: true }, { pattern: /^[a-z][a-z0-9_-]{1,39}$/, message: '以小写字母开头，仅使用小写字母、数字、下划线或连字符' }]}><Input disabled={!!editingRole} placeholder="例如 warehouse_editor" /></Form.Item></Col><Col span={14}><Form.Item name="name" label="角色名称" rules={[{ required: true }, { max: 80 }]}><Input placeholder="例如仓库专员" /></Form.Item></Col></Row>
        <Form.Item name="permissions" label="功能权限" rules={[{ required: true, type: 'array' }]}>
          <Checkbox.Group style={{ width: '100%' }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              {permissionGroups(sortedPermissions).map(([resource, values]) => <Row key={resource} align="middle" style={{ borderBottom: '1px solid #f0f0f0', padding: '8px 0' }}>
                <Col span={7}><Typography.Text strong>{PERMISSION_LABELS[resource] ?? resource}</Typography.Text></Col>
                <Col span={17}><Space wrap>{values.map((value) => <Checkbox key={value} value={value}>{ACTION_LABELS[value.split(':')[1]] ?? value.split(':')[1]}</Checkbox>)}</Space></Col>
              </Row>)}
            </Space>
          </Checkbox.Group>
        </Form.Item>
      </Form>
    </Modal>

    <Modal title={`重置密码 · ${resetTarget?.username ?? ''}`} open={!!resetTarget} onCancel={() => setResetTarget(null)} footer={null} destroyOnClose>
      <Alert type="warning" showIcon message="密码不会显示在页面或操作记录中。保存后，该账号现有登录会话将失效。" style={{ marginBottom: 16 }} />
      <Form layout="vertical" onFinish={resetPassword}>
        <Form.Item name="password" label="新密码" rules={[{ required: true }, { min: 8, max: 128 }]}><Input.Password autoComplete="new-password" /></Form.Item>
        <Form.Item name="confirm" label="确认新密码" dependencies={['password']} rules={[{ required: true }, ({ getFieldValue }) => ({ validator(_, value) { return !value || getFieldValue('password') === value ? Promise.resolve() : Promise.reject(new Error('两次输入的密码不一致')) } })]}><Input.Password autoComplete="new-password" /></Form.Item>
        <Space style={{ width: '100%', justifyContent: 'flex-end' }}><Button onClick={() => setResetTarget(null)}>取消</Button><Button type="primary" htmlType="submit">确认重置</Button></Space>
      </Form>
    </Modal>

    <Drawer title={`账号详情 · ${detail?.username ?? ''}`} open={!!detail} onClose={() => setDetail(null)} width={520}>
      {detail && <><Descriptions column={1} bordered size="small">
        <Descriptions.Item label="账号">{detail.username}</Descriptions.Item><Descriptions.Item label="角色">{roleById.get(detail.role_id)?.name ?? '未知角色'}</Descriptions.Item>
        <Descriptions.Item label="状态"><Tag color={detail.is_active ? 'green' : 'default'}>{detail.is_active ? '启用' : '停用'}</Tag></Descriptions.Item>
        <Descriptions.Item label="店铺范围">{scopeLabel(detail.shop_scope, shops)}</Descriptions.Item><Descriptions.Item label="仓库范围">{scopeLabel(detail.warehouse_scope, warehouses)}</Descriptions.Item>
        <Descriptions.Item label="创建时间">{new Date(detail.created_at).toLocaleString('zh-CN', { hour12: false })}</Descriptions.Item>
      </Descriptions><Divider orientation="left">角色权限</Divider>
      {roleById.get(detail.role_id)?.code === 'admin' ? <Alert type="info" showIcon message="管理员拥有系统注册的全部权限。" /> : <Space wrap>{roleById.get(detail.role_id)?.permissions.map((permission) => <Tag key={permission} color="blue">{permission}</Tag>) ?? <Typography.Text type="secondary">该角色没有权限</Typography.Text>}</Space>}</>}
    </Drawer>
  </Space>
}
