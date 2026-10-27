import { useMemo, useState } from 'react'
import { Alert, Card, Empty, Space, Tag, Typography } from 'antd'

export type GraphEntity = { id: string; type: string; value: string; label: string }
export type GraphClaim = { ref_id: string; claim_key: string; value: unknown; unit: string; source: string; observed_at: string; content_hash: string }
export type GraphEdge = { source: string; target: string; relation: string }
export type GraphRelation = { source: string; target: string; relation: string; evidence_ref: string }
export type GraphPayload = {
  backend: string; retrieval: string; embedding?: string; time_basis: string
  entities: GraphEntity[]; claims: GraphClaim[]; edges: GraphEdge[]; relations: GraphRelation[]
  limitations: string[]; matches?: { ref_id: string; vector_score: number; keyword_score: number }[]
}

const colors: Record<string, string> = {
  shop_id: '#1677ff', warehouse_id: '#13a8a8', product_id: '#9254de',
  sku_code: '#fa8c16', supplier_id: '#52c41a', purchase_order_id: '#eb2f96',
  campaign_id: '#fa541c',
}
const relationNames: Record<string, string> = {
  HAS_SKU: '包含 SKU', OBSERVED_SKU: '观测 SKU', PURCHASED_FROM: '向供应商采购',
  DELIVERS_TO: '送往仓库', ORDERS_SKU: '采购 SKU', PROMOTES_SKU: '推广 SKU',
}
const claimNames: Record<string, string> = {
  'product.active': '商品状态',
  'inventory.shop_available_qty': '店铺可售库存',
  'procurement.unreceived_quantity': '采购未收数量',
  'ads.spend': '广告花费',
  'ads.attributed_sales': '广告归因销售额',
  'ads.attributed_order_count': '广告归因订单数',
  'finance.verified_receipts': '已核验收款',
}
const claimName = (claim: GraphClaim) => claimNames[claim.claim_key] || claim.claim_key
const claimValue = (claim: GraphClaim) => {
  if (claim.claim_key === 'product.active') return Number(claim.value) === 1 ? '在售' : '停用'
  const value = typeof claim.value === 'number'
    ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(claim.value)
    : String(claim.value)
  const unit = ({ piece: '件', order: '单', boolean: '' } as Record<string, string>)[claim.unit] ?? claim.unit
  return `${value}${unit ? ` ${unit}` : ''}`
}

export default function GraphEvidenceCanvas({ graph }: { graph: GraphPayload }) {
  const [selected, setSelected] = useState<string | null>(null)
  const { entityPositions, claimPositions, height, connected } = useMemo(() => {
    const entityPositions = new Map(graph.entities.map((item, index) => [item.id, 52 + index * 76]))
    const claimPositions = new Map(graph.claims.map((item, index) => [item.ref_id, 52 + index * 76]))
    const connected = new Set<string>()
    for (const edge of graph.edges) {
      if (edge.source === selected) connected.add(edge.target)
      if (edge.target === selected) connected.add(edge.source)
    }
    for (const relation of graph.relations || []) {
      if (relation.source === selected) connected.add(relation.target)
      if (relation.target === selected) connected.add(relation.source)
    }
    return { entityPositions, claimPositions, connected,
      height: Math.max(250, 110 + Math.max(graph.entities.length, graph.claims.length) * 76) }
  }, [graph, selected])
  const focused = (id: string) => !selected || selected === id || connected.has(id)
  const claim = graph.claims.find(item => item.ref_id === selected)
  const entity = graph.entities.find(item => item.id === selected)
  if (!graph.claims.length) return <Empty description="所选业务范围没有可绘制的证据。请换一个真实 SKU 或日期范围。" />
  return <Space direction="vertical" size="middle" style={{ width: '100%' }}>
    <Space wrap><Tag color="blue">{graph.backend === 'neo4j' ? 'Neo4j' : '业务数据库'}</Tag>
      <Typography.Text>{graph.backend === 'neo4j' ? '向量与关键词联合排序' : '业务证据关系'}</Typography.Text>
      <Typography.Text type="secondary">{graph.claims.length} 条证据 · {graph.entities.length} 个实体 · {(graph.relations || []).length} 条业务关系</Typography.Text></Space>
    <Typography.Text type="secondary">时间依据：检查点记录的证据观察时间</Typography.Text>
    {graph.embedding && <Alert type="info" showIcon message="本地词元哈希向量可做词面相似度匹配，同义词语义能力有限" />}
    {graph.limitations.filter(note => !(graph.embedding && note.startsWith('向量使用本地词元哈希')))
      .map((note, index) => <Typography.Text key={index} type="secondary">{note}</Typography.Text>)}
    <div style={{ overflow: 'auto', maxHeight: 590, border: '1px solid #e5e9ee', borderRadius: 8, background: '#fbfcff' }}>
      <svg viewBox={`0 0 620 ${height}`} width="100%" role="img" aria-label="业务实体与证据关系图" style={{ display: 'block', minWidth: 450, aspectRatio: `620 / ${height}` }}>
        <text x="30" y="24" fill="#667085" fontSize="15">业务实体</text>
        <text x="350" y="24" fill="#667085" fontSize="15">可追溯证据</text>
        {(graph.relations || []).map((edge, index) => {
          const from = entityPositions.get(edge.source), to = entityPositions.get(edge.target)
          if (from === undefined || to === undefined) return null
          return <line key={`r-${index}`} x1="260" y1={from + 26} x2="260" y2={to + 26}
            stroke="#91a8c5" strokeWidth="2" strokeDasharray="4 4" opacity={focused(edge.source) || focused(edge.target) ? 0.8 : 0.1}>
            <title>{relationNames[edge.relation] || edge.relation}</title>
          </line>
        })}
        {graph.edges.map((edge, index) => {
          const from = entityPositions.get(edge.source), to = claimPositions.get(edge.target)
          if (from === undefined || to === undefined) return null
          return <path key={`e-${index}`} d={`M 252 ${from + 26} C 300 ${from + 26}, 290 ${to + 26}, 340 ${to + 26}`}
            fill="none" stroke="#b6c4d6" strokeWidth="1.5" opacity={focused(edge.source) && focused(edge.target) ? 0.65 : 0.07} />
        })}
        {graph.entities.map(item => {
          const y = entityPositions.get(item.id) || 0
          return <g key={item.id} onClick={() => setSelected(selected === item.id ? null : item.id)}
            style={{ cursor: 'pointer', opacity: focused(item.id) ? 1 : 0.25 }}>
            <title>{item.label} · {item.type}</title>
            <rect x="22" y={y} width="230" height="52" rx="8" fill={selected === item.id ? '#e6f4ff' : 'white'}
              stroke={colors[item.type] || '#8c8c8c'} strokeWidth={selected === item.id ? 2.5 : 1.5} />
            <circle cx="38" cy={y + 26} r="5" fill={colors[item.type] || '#8c8c8c'} />
            <text x="50" y={y + 31} fill="#26364a" fontSize="14">{item.label.length > 22 ? `${item.label.slice(0, 21)}…` : item.label}</text>
          </g>
        })}
        {graph.claims.map(item => {
          const y = claimPositions.get(item.ref_id) || 0
          return <g key={item.ref_id} onClick={() => setSelected(selected === item.ref_id ? null : item.ref_id)}
            style={{ cursor: 'pointer', opacity: focused(item.ref_id) ? 1 : 0.25 }}>
            <title>{claimName(item)}：{claimValue(item)} · {item.observed_at}</title>
            <rect x="340" y={y} width="260" height="52" rx="8" fill={selected === item.ref_id ? '#e6f4ff' : 'white'}
              stroke="#63758b" strokeWidth={selected === item.ref_id ? 2.5 : 1.5} />
            <text x="350" y={y + 20} fill="#526578" fontSize="13">
              {claimName(item).length > 22 ? `${claimName(item).slice(0, 21)}…` : claimName(item)}
            </text>
            <text x="350" y={y + 41} fill="#14283f" fontSize="16" fontWeight="600">{claimValue(item)}</text>
          </g>
        })}
      </svg>
    </div>
    {(claim || entity) && <Card size="small" title="选中节点">
      {entity && <Typography.Paragraph>{entity.label}（{entity.type}）</Typography.Paragraph>}
      {claim && <><Typography.Paragraph><strong>{claimName(claim)}：{claimValue(claim)}</strong></Typography.Paragraph>
        <Typography.Paragraph type="secondary">原始指标：{claim.claim_key}</Typography.Paragraph>
        <Typography.Text type="secondary">来源：{claim.source} · 观察：{claim.observed_at} · 校验摘要：{claim.content_hash.slice(0, 12)}</Typography.Text></>}
    </Card>}
    {!!graph.matches?.length && <Card size="small" title="检索排序">
      {graph.matches.slice(0, 8).map((match, index) => <Typography.Paragraph key={match.ref_id} style={{ marginBottom: 4 }}>
        {index + 1}. {(() => { const item = graph.claims.find(row => row.ref_id === match.ref_id); return item ? `${claimName(item)} · ${claimValue(item)}` : match.ref_id })()} · 向量 {match.vector_score.toFixed(3)} · 关键词 {match.keyword_score}
      </Typography.Paragraph>)}
    </Card>}
  </Space>
}
