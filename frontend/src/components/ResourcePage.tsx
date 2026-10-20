import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { request } from '../api/client'

type Row = Record<string, unknown>

interface ListResult {
  items: Row[]
  total: number
  page: number
  page_size: number
}

export interface Option {
  label: string
  value: string
}

export interface FieldConfig {
  name: string
  label: string
  /** 表单控件类型；不传按普通文本处理。 */
  type?: 'text' | 'textarea' | 'number' | 'money' | 'switch' | 'select'
  required?: boolean
  /** 静态下拉选项。 */
  options?: Option[]
  /** 从后端资源动态加载下拉选项。 */
  optionsFrom?: { resource: string; labelField?: string; codeField?: string; params?: Record<string, string> }
  width?: number
  hideInTable?: boolean
  hideInForm?: boolean
  /** 后端不允许修改的字段（code / kind / product_id），编辑时不提交、表单里置灰。 */
  immutable?: boolean
  defaultValue?: unknown
  /** 表格单元格自定义渲染。 */
  render?: (value: unknown, row: Row) => ReactNode
}

interface Props {
  /** 后端资源路径，例如 shops、warehouses。 */
  resource: string
  title: string
  description?: string
  fields: FieldConfig[]
  /** 列表固定附加参数，例如 { kind: 'unit' }。 */
  extraParams?: Record<string, string>
  /** 只读资源（如审计日志）不提供新增与编辑。 */
  readOnly?: boolean
}

function FieldControl({
  field,
  options,
  disabled,
}: {
  field: FieldConfig
  options: Option[]
  disabled?: boolean
}) {
  switch (field.type) {
    case 'switch':
      return <Switch disabled={disabled} />
    case 'number':
      return <InputNumber style={{ width: '100%' }} min={0} disabled={disabled} />
    case 'money':
      return <InputNumber style={{ width: '100%' }} min={0} precision={2} disabled={disabled} />
    case 'select':
      return (
        <Select
          options={options}
          showSearch
          optionFilterProp="label"
          disabled={disabled}
          placeholder={`请选择${field.label}`}
        />
      )
    case 'textarea':
      return <Input.TextArea rows={2} maxLength={500} disabled={disabled} />
    default:
      return <Input placeholder={`请输入${field.label}`} maxLength={120} disabled={disabled} />
  }
}

/**
 * 配置驱动的通用资源页：搜索、服务端分页、新增、编辑。
 * 基础资料类（店铺 / 仓库 / 供应商 / 字典 / 供货信息）共用同一套交互，
 * 省去逐个手写重复代码，也保证各页行为一致。
 */
export default function ResourcePage({
  resource,
  title,
  description,
  fields,
  extraParams,
  readOnly = false,
}: Props) {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [activeFilter, setActiveFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState<Row | null>(null)
  const [open, setOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [optionMap, setOptionMap] = useState<Record<string, Option[]>>({})
  const [form] = Form.useForm()

  // 动态下拉选项：按字段声明一次性加载，资源量有限，不做分页。
  useEffect(() => {
    let cancelled = false
    const loadOptions = async () => {
      const map: Record<string, Option[]> = {}
      for (const field of fields) {
        if (!field.optionsFrom) continue
        const { resource: src, labelField = 'name', codeField = 'code', params } = field.optionsFrom
        try {
          const res = await request<ListResult>(`/${src}`, { params: { page: 1, page_size: 100, ...params } })
          map[field.name] = res.items.map((row) => {
            const code = row[codeField]
            const label = row[labelField]
            return {
              value: String(row.id),
              label: code ? `${code} ${label ?? ''}`.trim() : String(label ?? row.id),
            }
          })
        } catch {
          map[field.name] = []
        }
      }
      if (!cancelled) setOptionMap(map)
    }
    void loadOptions()
    return () => {
      cancelled = true
    }
  }, [fields])

  const optionsByField = useMemo(() => {
    const map: Record<string, Option[]> = { ...optionMap }
    for (const field of fields) {
      if (field.options && !map[field.name]) map[field.name] = field.options
    }
    return map
  }, [fields, optionMap])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await request<ListResult>(`/${resource}`, {
        params: {
          page,
          page_size: pageSize,
          q: keyword || undefined,
          is_active: activeFilter || undefined,
          ...extraParams,
        },
      })
      setRows(res.items)
      setTotal(res.total)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [resource, page, pageSize, keyword, activeFilter, extraParams])

  useEffect(() => {
    void load()
  }, [load])

  const columns: ColumnsType<Row> = fields
    .filter((f) => !f.hideInTable)
    .map((f) => ({
      title: f.label,
      dataIndex: f.name,
      key: f.name,
      width: f.width,
      render: (value: unknown, row: Row) => {
        if (f.render) return f.render(value, row)
        if (f.type === 'switch') return <Tag color={value ? 'blue' : 'default'}>{value ? '启用' : '停用'}</Tag>
        if (f.type === 'select') {
          const hit = (optionsByField[f.name] ?? []).find((o) => o.value === value)
          return hit ? hit.label : value ? String(value).slice(0, 12) : '—'
        }
        if (value === null || value === undefined || value === '') return '—'
        return String(value)
      },
    }))

  if (!readOnly) {
    columns.push({
      title: '操作',
      key: '__actions',
      width: 90,
      fixed: 'right',
      render: (_, row) => (
        <Button
          type="link"
          size="small"
          onClick={() => {
            setEditing(row)
            const values: Record<string, unknown> = {}
            for (const f of fields) {
              if (!f.hideInForm) values[f.name] = row[f.name]
            }
            form.setFieldsValue(values)
            setOpen(true)
          }}
        >
          编辑
        </Button>
      ),
    })
  }

  const openCreate = () => {
    setEditing(null)
    const values: Record<string, unknown> = {}
    for (const f of fields) {
      if (f.hideInForm) continue
      values[f.name] = f.defaultValue ?? (f.type === 'switch' ? true : undefined)
    }
    form.setFieldsValue(values)
    setOpen(true)
  }

  const submit = async () => {
    let values: Record<string, unknown>
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    setSubmitting(true)
    try {
      if (editing) {
        // 后端 PATCH 采用 extra=forbid，提交不可变字段会被拒，这里先剔除
        const body: Record<string, unknown> = { ...values }
        for (const f of fields) {
          if (f.immutable) delete body[f.name]
        }
        await request(`/${resource}/${editing.id}`, { method: 'PATCH', body })
        message.success('已保存')
      } else {
        await request(`/${resource}`, { method: 'POST', body: values })
        message.success('已创建')
      }
      setOpen(false)
      await load()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card
      title={
        <Space direction="vertical" size={0}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>{title}</span>
          {description && (
            <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
              {description}
            </Typography.Text>
          )}
        </Space>
      }
      extra={
        <Space wrap>
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder="编码或名称"
            style={{ width: 180 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={() => {
              setPage(1)
              void load()
            }}
          />
          <Select
            allowClear
            style={{ width: 110 }}
            placeholder="状态"
            value={activeFilter || undefined}
            onChange={(v) => {
              setActiveFilter(v ?? '')
              setPage(1)
            }}
            options={[
              { label: '启用', value: 'true' },
              { label: '停用', value: 'false' },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            刷新
          </Button>
          {!readOnly && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新增
            </Button>
          )}
        </Space>
      }
    >
      <Table<Row>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={rows}
        columns={columns}
        scroll={{ x: 'max-content' }}
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

      <Modal
        title={editing ? `编辑${title}` : `新增${title}`}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => void submit()}
        confirmLoading={submitting}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          {fields
            .filter((f) => !f.hideInForm)
            .map((f) => (
              <Form.Item
                key={f.name}
                name={f.name}
                label={f.label}
                valuePropName={f.type === 'switch' ? 'checked' : 'value'}
                rules={f.required ? [{ required: true, message: `请填写${f.label}` }] : undefined}
              >
                <FieldControl
                  field={f}
                  options={optionsByField[f.name] ?? []}
                  disabled={Boolean(editing) && f.immutable === true}
                />
              </Form.Item>
            ))}
          {editing && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              编码与分类字段创建后不可修改；留空的字段保持原值。
            </Typography.Text>
          )}
        </Form>
      </Modal>
    </Card>
  )
}
