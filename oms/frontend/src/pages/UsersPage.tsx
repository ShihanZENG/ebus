import { useEffect, useState } from 'react'
import { Table, Card, Tag, Button, Space, Modal, Form, Input, Select, Switch, message, Tabs } from 'antd'
import { PlusOutlined, ReloadOutlined, KeyOutlined } from '@ant-design/icons'
import api from '../api'

export default function UsersPage() {
  const [users, setUsers] = useState<any[]>([])
  const [roles, setRoles] = useState<any[]>([])
  const [permissions, setPermissions] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [userOpen, setUserOpen] = useState(false)
  const [roleOpen, setRoleOpen] = useState(false)
  const [pwOpen, setPwOpen] = useState<any>(null)
  const [editingRole, setEditingRole] = useState<any>(null)
  const [userForm] = Form.useForm()
  const [roleForm] = Form.useForm()
  const [pwForm] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const [u, r, p] = await Promise.all([
        api.get('/users?page_size=100'),
        api.get('/roles'),
        api.get('/permissions'),
      ])
      setUsers(u.data.items); setRoles(r.data.items); setPermissions(p.data.items)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const saveUser = async () => {
    const v = await userForm.validateFields()
    if (v.id) await api.patch(`/users/${v.id}`, { role_id: v.role_id, is_active: v.is_active })
    else await api.post('/users', v)
    message.success('保存成功'); setUserOpen(false); userForm.resetFields(); load()
  }

  const saveRole = async () => {
    const v = await roleForm.validateFields()
    if (editingRole) await api.put(`/roles/${editingRole.id}`, v)
    else await api.post('/roles', v)
    message.success('角色已保存'); setRoleOpen(false); roleForm.resetFields(); load()
  }

  const resetPw = async () => {
    const v = await pwForm.validateFields()
    await api.put(`/users/${pwOpen.id}/password`, { password: v.password })
    message.success('密码已重置，该账号所有会话已失效')
    setPwOpen(null); pwForm.resetFields()
  }

  return (
    <Card>
      <Tabs items={[
        { key: 'users', label: '账号管理', children: (
          <>
            <Space style={{ marginBottom: 12 }}>
              <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => { userForm.resetFields(); setUserOpen(true) }}>新增账号</Button>
            </Space>
            <Table rowKey="id" loading={loading} dataSource={users}
              columns={[
                { title: '账号', dataIndex: 'username', width: 140 },
                { title: '角色', dataIndex: 'role_id', width: 120, render: (v: string) => <Tag>{roles.find((r) => r.id === v)?.name ?? v}</Tag> },
                { title: '状态', dataIndex: 'is_active', width: 90, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '停用'}</Tag> },
                { title: '店铺范围', dataIndex: 'shop_scope', render: (v: string[] | null) => v === null ? '全部店铺' : (v?.length ?? 0) ? `${v.length} 家` : '无' },
                { title: '仓库范围', dataIndex: 'warehouse_scope', render: (v: string[] | null) => v === null ? '全部仓库' : (v?.length ?? 0) ? `${v.length} 个` : '无' },
                { title: '操作', key: 'op', width: 220, render: (_: any, r: any) => (
                  <Space>
                    <Button size="small" icon={<KeyOutlined />} onClick={() => { pwForm.resetFields(); setPwOpen(r) }}>重置密码</Button>
                    <Button size="small" onClick={() => { userForm.setFieldsValue({ ...r, id: r.id }); setUserOpen(true) }}>编辑</Button>
                    <Switch checked={r.is_active} size="small" onChange={async (v) => {
                      await api.patch(`/users/${r.id}`, { is_active: v })
                      message.success('已更新'); load()
                    }} />
                  </Space>
                )},
              ]} />
          </>
        )},
        { key: 'roles', label: '角色权限', children: (
          <>
            <Space style={{ marginBottom: 12 }}>
              <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingRole(null); roleForm.resetFields(); setRoleOpen(true) }}>新增角色</Button>
            </Space>
            <Table rowKey="id" dataSource={roles}
              columns={[
                { title: '角色编码', dataIndex: 'code', width: 130 },
                { title: '角色名称', dataIndex: 'name', width: 140 },
                { title: '权限数', dataIndex: 'permissions', width: 90, render: (v: string[]) => v?.length ?? 0 },
                { title: '权限', dataIndex: 'permissions', ellipsis: true, render: (v: string[]) => v?.slice(0, 8).map((p) => <Tag key={p} style={{ marginBottom: 4 }}>{p}</Tag>) },
                { title: '操作', key: 'op', width: 100, render: (_: any, r: any) => r.code !== 'admin' && (
                  <Button size="small" onClick={() => { setEditingRole(r); roleForm.setFieldsValue(r); setRoleOpen(true) }}>编辑</Button>
                )},
              ]} />
          </>
        )},
      ]} />

      <Modal open={userOpen} title="账号管理" onCancel={() => setUserOpen(false)} onOk={saveUser}>
        <Form form={userForm} layout="vertical">
          {!userForm.getFieldValue('id') && <>
            <Form.Item name="username" label="账号" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 8 }]}><Input.Password /></Form.Item>
          </>}
          <Form.Item name="id" hidden><Input /></Form.Item>
          <Form.Item name="role_id" label="角色" rules={[{ required: true }]}>
            <Select options={roles.map((r) => ({ value: r.id, label: `${r.name}（${r.code}）` }))} /></Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked" initialValue={true}>
            <Switch /></Form.Item>
        </Form>
      </Modal>

      <Modal open={roleOpen} title={editingRole ? '编辑角色' : '新增角色'} onCancel={() => setRoleOpen(false)} onOk={saveRole} width={640}>
        <Form form={roleForm} layout="vertical">
          <Form.Item name="code" label="角色编码" rules={[{ required: true }]}><Input disabled={!!editingRole} /></Form.Item>
          <Form.Item name="name" label="角色名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="permissions" label="权限" initialValue={[]}>
            <Select mode="multiple" placeholder="选择权限" style={{ width: '100%' }}
              options={permissions.map((p) => ({ value: p, label: p }))}
              optionFilterProp="label" showSearch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal open={!!pwOpen} title={`重置密码 ${pwOpen?.username ?? ''}`} onCancel={() => setPwOpen(null)} onOk={resetPw}>
        <Form form={pwForm} layout="vertical">
          <Form.Item name="password" label="新密码" rules={[{ required: true, min: 8 }]}><Input.Password /></Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
