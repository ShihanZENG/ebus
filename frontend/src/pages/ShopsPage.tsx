import ResourcePage, { type FieldConfig } from '../components/ResourcePage'

const FIELDS: FieldConfig[] = [
  { name: 'code', label: '店铺编码', required: true, immutable: true, width: 140 },
  { name: 'name', label: '店铺名称', required: true, width: 180 },
  { name: 'channel', label: '平台渠道', required: true, width: 110, defaultValue: 'manual' },
  { name: 'market', label: '国家站点', required: true, width: 100 },
  { name: 'timezone', label: '时区', required: true, width: 160, defaultValue: 'Asia/Shanghai' },
  {
    name: 'currency_id',
    label: '结算币种',
    type: 'select',
    required: true,
    width: 140,
    optionsFrom: { resource: 'dictionaries', params: { kind: 'currency' } },
  },
  { name: 'is_active', label: '状态', type: 'switch', width: 90 },
]

/** 店铺：订单的来源站点，决定币种与时区。 */
export default function ShopsPage() {
  return (
    <ResourcePage
      resource="shops"
      title="店铺"
      description="订单的来源站点。币种决定订单金额单位，时区影响报表日期口径。"
      fields={FIELDS}
    />
  )
}
