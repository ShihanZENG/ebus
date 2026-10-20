import ResourcePage, { type FieldConfig } from '../components/ResourcePage'

const FIELDS: FieldConfig[] = [
  { name: 'code', label: '供应商编码', required: true, immutable: true, width: 140 },
  { name: 'name', label: '供应商名称', required: true, width: 200 },
  { name: 'contact_name', label: '联系人', width: 110 },
  { name: 'phone', label: '电话', width: 130 },
  { name: 'email', label: '邮箱', width: 180 },
  { name: 'is_active', label: '状态', type: 'switch', width: 90 },
]

/** 供应商：采购单的供货方，供货价与交期维护在供货信息里。 */
export default function SuppliersPage() {
  return (
    <ResourcePage
      resource="suppliers"
      title="供应商"
      description="采购单的供货方。每个供应商对不同 SKU 的供货价与交期见「供货信息」。"
      fields={FIELDS}
    />
  )
}
