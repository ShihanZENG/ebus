import ResourcePage, { type FieldConfig } from '../components/ResourcePage'

const FIELDS: FieldConfig[] = [
  { name: 'code', label: '仓库编码', required: true, immutable: true, width: 130 },
  { name: 'name', label: '仓库名称', required: true, width: 180 },
  {
    name: 'warehouse_type',
    label: '类型',
    type: 'select',
    required: true,
    width: 100,
    options: [
      { label: '国内仓', value: 'domestic' },
      { label: '海外仓', value: 'overseas' },
    ],
  },
  { name: 'country', label: '国家', required: true, width: 90 },
  { name: 'address', label: '地址', type: 'textarea', width: 240 },
  { name: 'is_active', label: '状态', type: 'switch', width: 90 },
]

/** 仓库档案：库存与出入库的归属维度。 */
export default function WarehousesPage() {
  return (
    <ResourcePage
      resource="warehouses"
      title="仓库档案"
      description="库存按仓库维度隔离，订单审核时需指定履约仓库。"
      fields={FIELDS}
    />
  )
}
