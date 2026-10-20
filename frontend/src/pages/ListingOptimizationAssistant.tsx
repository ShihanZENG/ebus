import { useEffect, useState } from 'react'
import { Alert, Button, Card, Collapse, Descriptions, Input, List, Select, Space, Table, Tag, Typography, message } from 'antd'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

type Listing = { id: string; sku_code: string; sku_name: string; shop_name: string; title: string; asin?: string | null }
type Draft = { id: string; actor_id: string; review_status: string; effective_status?: string; result: { title: string; bullets: string[]; description?: string; missing_info: string[]; change_reasons: string[]; keyword_coverage: { keyword: string; covered: boolean }[]; review_warnings: string[]; limitations: string[] }; input_snapshot: { live: { market: string; channel: string; sku_code: string; sku_name: string; product_code: string; product_name: string; product_description?: string | null; attributes: Record<string, unknown> }; inputs: { target_language: string; keywords: string[]; existing_title: string; existing_bullets: string[]; brand_voice: string } }; review_note?: string }
const explain = (error: unknown) => error instanceof Error ? error.message : '请求失败，请重试'

export default function ListingOptimizationAssistant() {
  const { user } = useAuth()
  const can = (permission: string) => user?.role === 'admin' || Boolean(user?.permissions.includes(permission))
  const [listings, setListings] = useState<Listing[]>([])
  const [listingId, setListingId] = useState<string>()
  const [languages, setLanguages] = useState<string[]>(['English'])
  const [keywords, setKeywords] = useState('')
  const [bullets, setBullets] = useState('')
  const [voice, setVoice] = useState('')
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')

  const loadListings = async () => {
    if (!can('listings:read')) return
    try {
      const result = await request<{items: Listing[]}>('/listings', {params: {page: 1, page_size: 100, status: 'active'}})
      setListings(result.items)
      if (listingId && !result.items.some(row => row.id === listingId)) setListingId(undefined)
    } catch (e) { setError(explain(e)) }
  }
  const loadDrafts = async (id = listingId) => {
    if (!id) { setDrafts([]); return }
    try { setDrafts((await request<{items: Draft[]}>(`/listing-agent/drafts`, {params: {listing_id: id}})).items) }
    catch (e) { setError(explain(e)) }
  }
  useEffect(() => { void loadListings() }, [user?.role, user?.permissions])
  useEffect(() => { setDrafts([]); void loadDrafts(listingId) }, [listingId])

  const selected = listings.find(item => item.id === listingId)
  const generate = async () => {
    if (!listingId || loading || languages.length === 0) return
    setError(''); setLoading(true)
    const created: Draft[] = []
    const failures: string[] = []
    for (const target_language of languages) {
      try {
        const draft = await request<Draft>('/listing-agent/drafts', {method: 'POST', body: {
          listing_id: listingId, target_language,
          keywords: keywords.split(/[,，\n]/).map(x => x.trim()).filter(Boolean),
          existing_bullets: bullets.split('\n').map(x => x.trim()).filter(Boolean), brand_voice: voice,
        }})
        created.push(draft)
      } catch (e) { failures.push(`${target_language}：${explain(e)}`) }
    }
    if (created.length) {
      setDrafts(current => [...created.reverse(), ...current])
      message.success(`${created.length} 个语言草稿已保存，等待人工复核`)
    }
    if (failures.length) setError(`部分语言生成失败：\n${failures.join('\n')}`)
    setLoading(false)
  }
  const review = async (draft: Draft, approved: boolean) => {
    const note = approved ? '人工核对商品事实、文案与目标站点要求' : '人工审核后退回修改'
    setBusyId(draft.id); setError('')
    try {
      await request(`/listing-agent/drafts/${draft.id}/review`, {method: 'POST', params: {approved, note}})
      message.success(approved ? '草稿已人工审核通过，可复制到发布流程' : '草稿已退回')
      await loadDrafts()
    } catch (e) { setError(explain(e)) }
    finally { setBusyId('') }
  }
  const copy = async (text: string) => {
    await navigator.clipboard.writeText(text)
    message.success('已复制文案')
  }

  if (!can('listings:read')) return <Alert type="warning" showIcon message="使用 Listing 优化助手需要 listings:read 权限。" />
  return <Space direction="vertical" size="middle" style={{width:'100%'}}>
    <Alert type="info" showIcon message="基于商品事实生成待审核草稿" description="文案只参考 ERP 已维护的商品资料及本页输入。关键词覆盖仅表示是否出现，不代表流量或排名；系统未接入目标站点实时规则。审核通过后可复制，草稿不会修改或发布平台 Listing。" />
    {error && <Alert type="error" showIcon message="操作失败" description={error} />}
    <Card title="单条 Listing 体检与改写">
      <Space direction="vertical" style={{width:'100%'}}>
        <Select showSearch optionFilterProp="label" placeholder="选择已有 Listing" value={listingId} onChange={setListingId} options={listings.map(x=>({value:x.id,label:`${x.shop_name} · ${x.sku_code} · ${x.title || x.asin || x.sku_name}`}))} />
        {selected && <Typography.Text>当前标题：{selected.title || '暂无'} · 商品：{selected.sku_code} {selected.sku_name}</Typography.Text>}
        <Space wrap>
          <Select mode="tags" maxCount={5} value={languages} onChange={setLanguages} placeholder="选择或输入目标语言（最多 5 种）" style={{minWidth:320}} options={['English','French','German','Spanish','Italian','Japanese','Korean','Chinese'].map(value=>({value,label:value}))} />
          <Input value={voice} onChange={e=>setVoice(e.target.value)} maxLength={500} placeholder="品牌语气（可选）" style={{width:300}} />
        </Space>
        <Input.TextArea value={keywords} onChange={e=>setKeywords(e.target.value)} rows={2} placeholder="目标关键词，以逗号或换行分隔；只检查文案是否覆盖" />
        <Input.TextArea value={bullets} onChange={e=>setBullets(e.target.value)} rows={4} placeholder="现有卖点，每行一条。请勿写入未经证实的效果或认证" />
        <Button type="primary" disabled={!listingId || !languages.length || !can('listings:write')} loading={loading} onClick={()=>void generate()}>按所选语言生成草稿</Button>
      </Space>
    </Card>
    {drafts.map(draft=><Card key={draft.id} title={<Space><span>优化草稿</span><Tag color={draft.effective_status==='stale'?'red':draft.review_status==='approved'?'green':draft.review_status==='rejected'?'default':'orange'}>{draft.effective_status==='stale'?'商品资料已变化，需重新生成':draft.review_status==='approved'?'人工审核通过':draft.review_status==='rejected'?'已退回':'待审核'}</Tag></Space>}>
      <Space direction="vertical" style={{width:'100%'}}>
        {draft.result.review_warnings.map(w=><Alert key={w} type="warning" showIcon message={w} />)}
        <Collapse items={[{key:'source',label:'查看本次生成依据（原 Listing 与商品资料快照）',children:<Descriptions bordered size="small" column={1} items={[
          {key:'old-title',label:'原标题',children:draft.input_snapshot.inputs.existing_title || '未填写'},
          {key:'old-bullets',label:'原卖点',children:draft.input_snapshot.inputs.existing_bullets.length ? <List size="small" dataSource={draft.input_snapshot.inputs.existing_bullets} renderItem={item=><List.Item>{item}</List.Item>} /> : '未填写'},
          {key:'sku',label:'SKU',children:`${draft.input_snapshot.live.sku_code} · ${draft.input_snapshot.live.sku_name}`},
          {key:'product',label:'商品资料',children:`${draft.input_snapshot.live.product_code} · ${draft.input_snapshot.live.product_name}`},
          {key:'description',label:'商品描述',children:draft.input_snapshot.live.product_description || '暂无'},
          {key:'attributes',label:'SKU 属性',children:<Typography.Text style={{whiteSpace:'pre-wrap'}}>{JSON.stringify(draft.input_snapshot.live.attributes, null, 2)}</Typography.Text>},
          {key:'target',label:'目标语言 / 关键词',children:`${draft.input_snapshot.inputs.target_language} · ${draft.input_snapshot.inputs.keywords.join('、') || '未提供关键词'}`},
        ]} /> }]} />
        <Typography.Title level={5}>标题对照</Typography.Title>
        <Descriptions bordered size="small" column={1} items={[
          {key:'before',label:'原标题',children:draft.input_snapshot.inputs.existing_title || '未填写'},
          {key:'after',label:'优化草稿',children:draft.result.title},
        ]} />
        <Button size="small" onClick={()=>void copy(draft.result.title)}>复制标题</Button>
        <Typography.Title level={5}>卖点</Typography.Title>
        <List size="small" dataSource={draft.result.bullets} renderItem={item=><List.Item>{item}</List.Item>} />
        <Button size="small" onClick={()=>void copy(draft.result.bullets.join('\n'))}>复制卖点</Button>
        {draft.result.description && <><Typography.Title level={5}>描述</Typography.Title><Typography.Paragraph>{draft.result.description}</Typography.Paragraph><Button size="small" onClick={()=>void copy(draft.result.description ?? '')}>复制描述</Button></>}
        <Typography.Title level={5}>缺失资料</Typography.Title>
        {draft.result.missing_info.length ? <List size="small" dataSource={draft.result.missing_info} renderItem={item=><List.Item>{item}</List.Item>} /> : <Typography.Text type="secondary">未提示额外缺失项，请仍核对商品资料。</Typography.Text>}
        <Typography.Title level={5}>修改原因</Typography.Title><List size="small" dataSource={draft.result.change_reasons} renderItem={item=><List.Item>{item}</List.Item>} />
        <Typography.Title level={5}>关键词覆盖（字面检查）</Typography.Title>
        <Table size="small" rowKey="keyword" pagination={false} dataSource={draft.result.keyword_coverage} columns={[{title:'关键词',dataIndex:'keyword'},{title:'草稿是否出现',dataIndex:'covered',render:v=><Tag color={v?'green':'orange'}>{v?'已出现':'未出现'}</Tag>}]} />
        <List size="small" header="使用限制" dataSource={draft.result.limitations} renderItem={item=><List.Item>{item}</List.Item>} />
        {draft.review_status==='pending' && can('listings:write') && draft.actor_id !== user?.id && <Space><Button loading={busyId===draft.id} onClick={()=>void review(draft,false)}>退回修改</Button><Button type="primary" loading={busyId===draft.id} onClick={()=>void review(draft,true)}>人工审核通过</Button></Space>}
        {draft.review_status==='approved' && draft.effective_status!=='stale' && <Button onClick={()=>void copy([draft.result.title,...draft.result.bullets,draft.result.description ?? ''].filter(Boolean).join('\n\n'))}>复制完整 Listing 文案</Button>}
        {draft.review_note && <Typography.Text type="secondary">审核备注：{draft.review_note}</Typography.Text>}
      </Space>
    </Card>)}
  </Space>
}
