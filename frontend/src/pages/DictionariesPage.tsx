import { useState } from 'react'
import { Tabs } from 'antd'
import ResourcePage, { type FieldConfig } from '../components/ResourcePage'

function fieldsFor(kind: 'currency' | 'unit'): FieldConfig[] {
  return [
    { name: 'kind', label: '分类', type: 'select', required: true, immutable: true, hideInTable: true, defaultValue: kind },
    { name: 'code', label: '编码', required: true, immutable: true, width: 120 },
    { name: 'name', label: '名称', required: true, width: 160 },
    { name: 'is_active', label: '状态', type: 'switch', width: 90 },
  ]
}

/** 币种与单位：商品单位、订单币种、付款币种的取值来源。 */
export default function DictionariesPage() {
  const [tab, setTab] = useState<'currency' | 'unit'>('currency')

  return (
    <Tabs
      activeKey={tab}
      onChange={(k) => setTab(k as 'currency' | 'unit')}
      items={[
        {
          key: 'currency',
          label: '币种',
          children: (
            <ResourcePage
              key="currency"
              resource="dictionaries"
              title="币种"
              description="订单与付款记录的金额单位。停用后不能再被新订单引用。"
              fields={fieldsFor('currency')}
              extraParams={{ kind: 'currency' }}
            />
          ),
        },
        {
          key: 'unit',
          label: '单位',
          children: (
            <ResourcePage
              key="unit"
              resource="dictionaries"
              title="单位"
              description="商品的计量单位，商品创建时必填。"
              fields={fieldsFor('unit')}
              extraParams={{ kind: 'unit' }}
            />
          ),
        },
      ]}
    />
  )
}
