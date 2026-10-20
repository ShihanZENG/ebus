import ResourcePage, { type FieldConfig } from '../components/ResourcePage'

const FIELDS: FieldConfig[] = [
  {
    name: 'supplier_id',
    label: '供应商',
    type: 'select',
    required: true,
    width: 190,
    // 后端 SupplierSkuPatch 只接受价格/交期/启停，编辑时不提交供应商与 SKU
    immutable: true,
    optionsFrom: { resource: 'suppliers' },
  },
  {
    name: 'sku_id',
    label: 'SKU',
    type: 'select',
    required: true,
    width: 240,
    immutable: true,
    optionsFrom: { resource: 'skus' },
  },
  { name: 'supply_price', label: '供货价', type: 'money', required: true, width: 110 },
  { name: 'lead_time_days', label: '采购交期（天）', type: 'number', required: true, width: 130, defaultValue: 7 },
  { name: 'is_active', label: '状态', type: 'switch', width: 90 },
]

/** 供货信息：供应商对某 SKU 的供货价与交期，是补货建议与采购单价的依据。 */
export default function SupplyInfosPage({ title = '供货信息' }: { title?: string }) {
  return (
    <ResourcePage
      resource="supply-infos"
      title={title}
      description="维护供应商对 SKU 的当前供货价与采购交期，补货建议转采购单时可引用。当前记录为现行供货信息，不包含历史报价版本。"
      fields={FIELDS}
    />
  )
}
