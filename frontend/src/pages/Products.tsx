import { useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Button, Form, Input, Modal, Select, Space, Table, Tabs, Tag, message } from 'antd'
import dayjs from 'dayjs'
import api from '../api'
import { useAuth } from '../auth/AuthProvider'

interface Product {
  id: string
  code: string
  name: string
  description: string
  unit_id: string
  is_active: boolean
  created_at: string
}

interface Sku {
  id: string
  code: string
  name: string
  product_id: string
  attributes: Record<string, string> | null
  is_active: boolean
}

interface SkuAttribute {
  key: string
  value: string
}

interface SkuFormValues {
  code: string
  name: string
  product_id: string
  attributes: SkuAttribute[]
  is_active: boolean
}

interface Dict {
  id: string
  code: string
  name: string
}

interface ListResult<T> {
  items: T[]
  total: number
}

export default function Products() {
  const location = useLocation()
  const navigate = useNavigate()
  const { user } = useAuth()
  const canReadProducts = user?.role === 'admin' || !!user?.permissions.includes('products:read')
  const canWriteProducts = user?.role === 'admin' || !!user?.permissions.includes('products:write')
  const canReadSkus = user?.role === 'admin' || !!user?.permissions.includes('skus:read')
  const canWriteSkus = user?.role === 'admin' || !!user?.permissions.includes('skus:write')
  const canReadUnits = user?.role === 'admin' || !!user?.permissions.includes('dictionaries:read')
  const [products, setProducts] = useState<Product[]>([])
  const [skus, setSkus] = useState<Sku[]>([])
  const [skuProducts, setSkuProducts] = useState<Product[]>([])
  const [units, setUnits] = useState<Dict[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [active, setActive] = useState<boolean | undefined>(undefined)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Product | null>(null)
  const [form] = Form.useForm()
  const [skuModalOpen, setSkuModalOpen] = useState(false)
  const [editingSku, setEditingSku] = useState<Sku | null>(null)
  const [skuForm] = Form.useForm<SkuFormValues>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [p, s, u] = await Promise.allSettled([
        canReadProducts
          ? api.get<ListResult<Product>>('/products', {
              params: { q: keyword || undefined, is_active: active, page, page_size: pageSize },
            })
          : Promise.resolve(null),
        canReadSkus ? api.get<ListResult<Sku>>('/skus', { params: { page_size: 100 } }) : Promise.resolve(null),
        canReadUnits ? api.get<ListResult<Dict>>('/dictionaries', { params: { kind: 'unit', page_size: 100 } }) : Promise.resolve(null),
      ])
      if (p.status === 'fulfilled' && p.value) {
        setProducts(p.value.data.items)
        setTotal(p.value.data.total)
      }
      if (s.status === 'fulfilled' && s.value) setSkus(s.value.data.items)
      if (u.status === 'fulfilled' && u.value) setUnits(u.value.data.items)
      if ([p, s, u].some((result) => result.status === 'rejected')) message.error('部分商品资料加载失败')
    } finally {
      setLoading(false)
    }
  }, [keyword, active, page, pageSize, canReadProducts, canReadSkus, canReadUnits])

  useEffect(() => {
    void load().catch(() => {})
  }, [load])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ is_active: true })
    setModalOpen(true)
  }

  const openEdit = (row: Product) => {
    setEditing(row)
    form.setFieldsValue(row)
    setModalOpen(true)
  }

  const save = async () => {
    const values = await form.validateFields()
    if (editing) {
      const body = { ...values }
      delete body.code
      await api.patch(`/products/${editing.id}`, body)
      message.success('已更新')
    } else {
      await api.post('/products', values)
      message.success('已创建')
    }
    setModalOpen(false)
    void load().catch(() => {})
  }

  const unitName = (id: string) => units.find((u) => u.id === id)?.name ?? id

  const openCreateSku = async () => {
    setEditingSku(null)
    skuForm.resetFields()
    skuForm.setFieldsValue({ is_active: true, attributes: [] })
    setSkuModalOpen(true)
    if (canReadProducts) {
      try {
        const result = await api.get<ListResult<Product>>('/products', { params: { page: 1, page_size: 100, is_active: true } })
        setSkuProducts(result.data.items)
      } catch {
        message.warning('商品选项加载失败；可检查商品查看权限')
      }
    }
  }

  const openEditSku = (row: Sku) => {
    setEditingSku(row)
    skuForm.setFieldsValue({
      code: row.code,
      name: row.name,
      product_id: row.product_id,
      attributes: Object.entries(row.attributes ?? {}).map(([key, value]) => ({ key, value })),
      is_active: row.is_active,
    })
    setSkuModalOpen(true)
  }

  const saveSku = async () => {
    let values: SkuFormValues
    try {
      values = await skuForm.validateFields()
    } catch {
      return
    }
    const attributes = Object.fromEntries(
      (values.attributes ?? [])
        .filter((item) => item.key.trim())
        .map((item) => [item.key.trim(), item.value ?? '']),
    ) as Record<string, string>
    try {
      if (editingSku) {
        await api.patch(`/skus/${editingSku.id}`, {
          name: values.name,
          attributes,
          is_active: values.is_active,
        })
        message.success('SKU 已更新')
      } else {
        await api.post('/skus', {
          code: values.code,
          name: values.name,
          product_id: values.product_id,
          attributes,
          is_active: values.is_active,
        })
        message.success('SKU 已创建')
      }
      setSkuModalOpen(false)
      await load()
    } catch {
      // 请求拦截器已展示接口错误。
    }
  }

  return (
    <>
      <Tabs
        activeKey={location.pathname === '/skus' ? 'skus' : 'products'}
        onChange={(key) => navigate(`/${key}`)}
        items={[
          {
            key: 'products',
            label: '商品',
            children: (
              <>
                <Space wrap style={{ marginBottom: 16 }}>
                  <Input
                    allowClear
                    placeholder="按编码或名称搜索"
                    style={{ width: 240 }}
                    value={keyword}
                    onChange={(e) => setKeyword(e.target.value)}
                    onPressEnter={() => {
                      setPage(1)
                      void load().catch(() => {})
                    }}
                  />
                  <Select
                    allowClear
                    placeholder="状态"
                    style={{ width: 120 }}
                    value={active}
                    onChange={(v) => {
                      setActive(v)
                      setPage(1)
                    }}
                    options={[
                      { value: true, label: '启用' },
                      { value: false, label: '停用' },
                    ]}
                  />
                  <Button onClick={() => { setKeyword(''); setActive(undefined); setPage(1) }}>
                    重置
                  </Button>
                  {canWriteProducts && <Button type="primary" disabled={!canReadUnits} onClick={openCreate}>
                    新增商品
                  </Button>}
                </Space>

                <Table<Product>
                  rowKey="id"
                  loading={loading}
                  dataSource={products}
                  scroll={{ x: 800 }}
                  columns={[
                    { title: '编码', dataIndex: 'code', width: 150 },
                    { title: '名称', dataIndex: 'name' },
                    {
                      title: '单位',
                      dataIndex: 'unit_id',
                      width: 100,
                      render: (v: string) => unitName(v),
                    },
                    {
                      title: '描述',
                      dataIndex: 'description',
                      ellipsis: true,
                      render: (v: string) => v || '—',
                    },
                    {
                      title: '状态',
                      dataIndex: 'is_active',
                      width: 90,
                      render: (v: boolean) => (
                        <Tag color={v ? 'blue' : 'default'}>{v ? '启用' : '停用'}</Tag>
                      ),
                    },
                    {
                      title: '创建时间',
                      dataIndex: 'created_at',
                      width: 170,
                      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm'),
                    },
                    ...(canWriteProducts ? [{
                      title: '操作',
                      width: 90,
                      render: (_: unknown, row: Product) => (
                        <Button size="small" disabled={!canReadUnits} onClick={() => openEdit(row)}>
                          编辑
                        </Button>
                      ),
                    }] : []),
                  ]}
                  pagination={{
                    current: page,
                    pageSize,
                    total,
                    showSizeChanger: true,
                    showTotal: (t) => `共 ${t} 条`,
                    onChange: (p, ps) => {
                      setPage(p)
                      setPageSize(ps)
                    },
                  }}
                />
              </>
            ),
          },
          {
            key: 'skus',
            label: 'SKU',
            children: (
              <>
                <Space style={{ marginBottom: 16 }}>
                  <Button onClick={() => void load()}>刷新</Button>
                  {canWriteSkus && <Button type="primary" onClick={() => void openCreateSku()}>新增 SKU</Button>}
                </Space>
                <Table<Sku>
                  rowKey="id"
                  loading={loading}
                  dataSource={skus}
                  pagination={false}
                  columns={[
                    { title: 'SKU 编码', dataIndex: 'code', width: 180 },
                    { title: '名称', dataIndex: 'name' },
                    {
                      title: '规格',
                      dataIndex: 'attributes',
                      render: (v: Record<string, string> | null) =>
                        v && Object.keys(v).length ? Object.entries(v).map(([k, val]) => `${k}:${val}`).join('，') : '—',
                    },
                    {
                      title: '状态',
                      dataIndex: 'is_active',
                      width: 90,
                      render: (v: boolean) => <Tag color={v ? 'blue' : 'default'}>{v ? '启用' : '停用'}</Tag>,
                    },
                    ...(canWriteSkus ? [{
                      title: '操作',
                      key: 'action',
                      width: 90,
                      render: (_: unknown, row: Sku) => <Button size="small" onClick={() => openEditSku(row)}>编辑</Button>,
                    }] : []),
                  ]}
                />
              </>
            ),
          },
        ].filter((item) => item.key === 'products' ? canReadProducts : canReadSkus)}
      />

      <Modal
        open={modalOpen}
        title={editing ? '编辑商品' : '新增商品'}
        onCancel={() => setModalOpen(false)}
        onOk={() => void save().catch(() => {})}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="code" label="编码" rules={[{ required: true, message: '请输入编码' }]}>
            <Input placeholder="如 CUP" disabled={!!editing} />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="unit_id" label="单位" rules={[{ required: true, message: '请选择单位' }]}>
            <Select
              placeholder="请选择单位"
              options={units.map((u) => ({ label: `${u.name}（${u.code}）`, value: u.id }))}
            />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="is_active" label="状态" rules={[{ required: true }]}>
            <Select
              options={[
                { value: true, label: '启用' },
                { value: false, label: '停用' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={skuModalOpen}
        title={editingSku ? '编辑 SKU' : '新增 SKU'}
        onCancel={() => setSkuModalOpen(false)}
        onOk={() => void saveSku()}
        destroyOnClose
      >
        <Form form={skuForm} layout="vertical" preserve={false}>
          <Form.Item name="code" label="SKU 编码" rules={[
            { required: true, message: '请输入 SKU 编码' },
            { min: 1, max: 64, pattern: /^[A-Za-z0-9][A-Za-z0-9_.-]*$/, message: '编码需以字母或数字开头，最多64位，仅可含字母、数字、点、下划线和连字符' },
          ]}>
            <Input maxLength={64} disabled={!!editingSku} />
          </Form.Item>
          <Form.Item name="name" label="SKU 名称" rules={[{ required: true, min: 1, max: 120, message: '请输入不超过120字的 SKU 名称' }]}>
            <Input maxLength={120} />
          </Form.Item>
          <Form.Item name="product_id" label="所属商品" rules={[{ required: true, message: '请选择或填写所属商品' }, { len: 36, message: '商品 ID 必须为36位' }]}>
            {canReadProducts && !editingSku ? (
              <Select
                showSearch
                optionFilterProp="label"
                placeholder="请选择商品"
                options={skuProducts.map((product) => ({ value: product.id, label: `${product.code} ${product.name}` }))}
              />
            ) : (
              <Input disabled={!!editingSku} placeholder={canReadProducts ? '所属商品 ID' : '需要商品查看权限才能选择商品；也可粘贴商品 ID'} />
            )}
          </Form.Item>
          <Form.List name="attributes">
            {(fields, { add, remove }) => (
              <>
                <div style={{ marginBottom: 8 }}>规格属性（可选，键和值均为文本）</div>
                {fields.map((field) => (
                  <Space key={field.key} align="baseline" style={{ display: 'flex' }}>
                    <Form.Item {...field} name={[field.name, 'key']} rules={[{ required: true, message: '请输入属性名' }, { max: 64, message: '属性名最多64字' }]}>
                      <Input placeholder="属性名，如颜色" maxLength={64} />
                    </Form.Item>
                    <Form.Item {...field} name={[field.name, 'value']} rules={[{ max: 200, message: '属性值最多200字' }]}>
                      <Input placeholder="属性值，如黑色" maxLength={200} />
                    </Form.Item>
                    <Button type="link" danger onClick={() => remove(field.name)}>删除</Button>
                  </Space>
                ))}
                <Button type="dashed" block onClick={() => add({ key: '', value: '' })}>添加规格属性</Button>
              </>
            )}
          </Form.List>
          <Form.Item name="is_active" label="状态" rules={[{ required: true, message: '请选择状态' }]}>
            <Select options={[{ value: true, label: '启用' }, { value: false, label: '停用' }]} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
