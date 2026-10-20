import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Input, Modal, Space, Table, Tag, Typography } from 'antd'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

interface EvidenceDay { date: string; order_count: number; quantity: number }
interface Evidence {
  id: string
  status: 'pending' | 'approved' | 'revoked'
  effective_status?: 'pending' | 'approved' | 'revoked' | 'stale'
  source_reference: string
  source_sha256: string
  start_date: string
  end_date: string
  submitted_by: string
  reviewed_by: string | null
  review_note: string | null
}
interface EvidenceResult {
  shop_today: string
  items: Evidence[]
  expected_days: EvidenceDay[]
  snapshot_hash: string
  missing_ordered_at_orders: number
}
const statuses = {
  pending: { label: '待复核', color: 'orange' },
  approved: { label: '人工凭证已复核', color: 'green' },
  revoked: { label: '已撤销', color: 'default' },
  stale: { label: '订单已变化，凭证失效', color: 'orange' },
}
const errorText = (error: unknown) => error instanceof Error ? error.message : '请求失败，请重试'

function parseDays(csv: string, businessDate: string): EvidenceDay[] {
  const lines = csv.trim().split(/\r?\n/)
  if (lines.length !== 21) throw new Error('请粘贴恰好 21 行数据，不含表头和空行。')
  const end = new Date(`${businessDate}T00:00:00Z`)
  if (!Number.isFinite(end.getTime())) throw new Error('统计截止日无效。')
  const expectedDates = new Set(Array.from({ length: 21 }, (_, i) => new Date(end.getTime() - i * 86400000).toISOString().slice(0, 10)))
  const seen = new Set<string>()
  const days = lines.map((line, index) => {
    const fields = line.split(',').map(value => value.trim())
    if (fields.length !== 3) throw new Error(`第 ${index + 1} 行应为 date,order_count,quantity 三列。`)
    const [date, count, quantity] = fields
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !expectedDates.has(date)) throw new Error(`第 ${index + 1} 行日期必须在截止日及此前 20 天内，格式为 YYYY-MM-DD。`)
    if (seen.has(date)) throw new Error(`日期 ${date} 重复，请每个日期只填写一行。`)
    if (![count, quantity].every(value => /^\d+$/.test(value) && Number.isSafeInteger(Number(value)))) throw new Error(`第 ${index + 1} 行订单数和件数必须是非负安全整数。`)
    seen.add(date)
    return { date, order_count: Number(count), quantity: Number(quantity) }
  })
  return days.sort((a, b) => a.date.localeCompare(b.date))
}

export default function SalesCoverageEvidence({ profileId, businessDate, refresh, onChanged }: {
  profileId: string; businessDate: string; refresh: number; onChanged: () => void
}) {
  const { user } = useAuth()
  const can = (permission: string) => user?.role === 'admin' || !!user?.permissions.includes(permission)
  const canWrite = can('purchase_agent:write')
  const canApprove = can('purchase_agent:approve')
  const [data, setData] = useState<EvidenceResult>()
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [revision, setRevision] = useState(0)
  const [source, setSource] = useState('')
  const [sha256, setSha256] = useState('')
  const [csv, setCsv] = useState('')
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const [review, setReview] = useState<{ evidence: Evidence; decision: 'approve' | 'revoke' }>()
  const [note, setNote] = useState('')
  const [reviewError, setReviewError] = useState('')
  const path = `/purchase-agent/coverage-evidence/${encodeURIComponent(profileId)}`
  const incompleteDate = !data?.shop_today || businessDate >= data.shop_today

  useEffect(() => {
    let active = true
    setLoading(true); setLoadError(''); setData(undefined)
    request<EvidenceResult>(path, { params: { business_date: businessDate } })
      .then(result => { if (active) setData(result) })
      .catch(e => { if (active) setLoadError(errorText(e)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [path, businessDate, refresh, revision])

  async function submit() {
    if (lock.current) return
    setError(''); setSuccess('')
    try {
      if (!canWrite) throw new Error('需要 purchase_agent:write 权限。')
      if (incompleteDate) throw new Error('店铺当地今天尚未结束，不能提交完整日凭证，请将统计截止日改为店铺当地昨天或更早。')
      const sourceReference = source.trim()
      if (!sourceReference || sourceReference.length > 500) throw new Error('来源引用不能为空且不得超过 500 字符。')
      if (!/^[a-fA-F0-9]{64}$/.test(sha256.trim())) throw new Error('SHA256 必须为 64 位十六进制文件指纹。')
      // Only the manually supplied platform CSV is submitted; expected_days is read-only.
      const days = parseDays(csv, businessDate)
      lock.current = true; setBusy(true)
      await request(path, { method: 'POST', body: { business_date: businessDate, source_reference: sourceReference, source_sha256: sha256.trim().toLowerCase(), days } })
      setSource(''); setSha256(''); setCsv('')
      setSuccess('凭证已提交，等待其他有审批权限的人员人工复核。')
      onChanged()
    } catch (e) { setError(errorText(e)) }
    finally { lock.current = false; setBusy(false) }
  }

  async function submitReview() {
    if (!review || lock.current) return
    setReviewError(''); setSuccess('')
    try {
      if (!canApprove || !user) throw new Error('需要 purchase_agent:approve 权限。')
      if (review.decision === 'approve' && review.evidence.submitted_by === user.id) throw new Error('提交人不能审核自己的凭证。')
      lock.current = true; setBusy(true)
      await request(`${path}/${encodeURIComponent(review.evidence.id)}/review`, { method: 'POST', body: { decision: review.decision, note: note.trim() } })
      setSuccess(review.decision === 'approve' ? '人工凭证已复核，非平台自动认证。' : '凭证已撤销。')
      setReview(undefined); setNote(''); onChanged()
    } catch (e) { setReviewError(errorText(e)) }
    finally { lock.current = false; setBusy(false) }
  }

  return <Card title="21 天订单完整性人工凭证" style={{ marginTop: 16 }} extra={<Button disabled={busy} loading={loading} onClick={() => setRevision(n => n + 1)}>刷新凭证</Button>}>
    <Space direction="vertical" style={{ width: '100%' }}>
      <Alert type="info" showIcon message="人工核对凭证，非平台自动认证" description="平台报表的上传和原始文件保管在系统外部完成。系统仅记录来源引用、文件 SHA256 指纹和人工填写的逐日数量，交由其他人员核对；指纹本身不证明报表真实或完整。" />
      {incompleteDate && <Alert type="warning" showIcon message="今天可以查询，但不能提交今天或未来日期的完整日凭证。请将上方统计截止日改为昨天或更早；最终以 API 日期校验为准。" />}
      {loadError && <Alert type="error" showIcon message={loadError} />}
      {error && <Alert type="error" showIcon message={error} />}
      {success && <Alert type="success" showIcon message={success} />}
      {data && <>
        <Typography.Paragraph>缺实际下单时间的订单：{data.missing_ordered_at_orders} 笔。以下为系统数量，仅供对照，请独立从平台报表填写 CSV，不得将系统数量直接作为平台凭证提交。</Typography.Paragraph>
        <Typography.Paragraph type="secondary" style={{ overflowWrap: 'anywhere' }}>当前系统快照：{data.snapshot_hash}</Typography.Paragraph>
        <Table<EvidenceDay> size="small" rowKey="date" dataSource={data.expected_days} pagination={{ pageSize: 7 }} columns={[
          { title: '系统日期（只读）', dataIndex: 'date' },
          { title: '系统订单数', dataIndex: 'order_count' },
          { title: '系统件数', dataIndex: 'quantity' },
        ]} />
      </>}
      <label htmlFor="coverage-source">来源引用（报表名称、导出范围或外部保管位置，不超过 500 字符）</label>
      <Input id="coverage-source" value={source} maxLength={500} disabled={!canWrite || busy} onChange={e => setSource(e.target.value)} />
      <label htmlFor="coverage-sha256">原始报表文件 SHA256（64 位十六进制）</label>
      <Input id="coverage-sha256" value={sha256} disabled={!canWrite || busy} onChange={e => setSha256(e.target.value)} />
      <label htmlFor="coverage-csv">人工填写的平台报表逐日数量 CSV：date,order_count,quantity</label>
      <Input.TextArea id="coverage-csv" value={csv} rows={10} disabled={!canWrite || busy} onChange={e => setCsv(e.target.value)} placeholder="粘贴 21 行，不含表头；每行为 YYYY-MM-DD,订单数,件数。覆盖统计截止日及此前 20 天，每天一行；确认平台当天为零时才填写 0。" />
      {!canWrite && <Typography.Text type="secondary">录入需要 purchase_agent:write 权限。</Typography.Text>}
      <Button type="primary" disabled={!canWrite || incompleteDate || loading || !data} loading={busy && !review} onClick={submit}>提交人工凭证</Button>
      <Table<Evidence> size="small" rowKey="id" loading={loading} dataSource={data?.items ?? []} scroll={{ x: 1100 }} pagination={{ pageSize: 5 }} columns={[
        { title: '状态', render: (_, item) => { const status = item.effective_status ?? item.status; return <Tag color={statuses[status]?.color}>{statuses[status]?.label ?? status}</Tag> } },
        { title: '凭证区间', render: (_, item) => `${item.start_date} 至 ${item.end_date}` },
        { title: '来源引用', dataIndex: 'source_reference' },
        { title: 'SHA256', dataIndex: 'source_sha256', width: 200, render: (value: string) => <Typography.Text style={{ overflowWrap: 'anywhere' }} copyable>{value}</Typography.Text> },
        { title: '提交人', dataIndex: 'submitted_by' },
        { title: '复核人', dataIndex: 'reviewed_by', render: (value: string | null) => value || '—' },
        { title: '复核备注', dataIndex: 'review_note' },
        { title: '操作', width: 220, render: (_, item) => {
          const self = user?.id === item.submitted_by
          const disabled = !canApprove || !user || busy
          const openReview = (decision: 'approve' | 'revoke') => { setReview({ evidence: item, decision }); setNote(''); setReviewError('') }
          return <Space direction="vertical">
            <Space>
              <Button size="small" disabled={disabled || self || item.status !== 'pending'} onClick={() => openReview('approve')}>审批通过</Button>
              <Button size="small" danger disabled={disabled || item.status === 'revoked'} onClick={() => openReview('revoke')}>撤销</Button>
            </Space>
            {self ? <Typography.Text type="secondary">提交人不能自审</Typography.Text> : !canApprove && <Typography.Text type="secondary">需要 purchase_agent:approve 权限</Typography.Text>}
          </Space>
        } },
      ]} />
    </Space>
    <Modal title={review?.decision === 'approve' ? '人工复核平台报表凭证' : '撤销人工凭证'} open={!!review} onCancel={() => { if (!busy) setReview(undefined) }} onOk={submitReview} confirmLoading={busy} cancelButtonProps={{ disabled: busy }} okButtonProps={{ disabled: !canApprove || !user || (review?.decision === 'approve' && review.evidence.submitted_by === user.id) }} okText={review?.decision === 'approve' ? '确认复核通过' : '确认撤销'} cancelText="取消">
      <Typography.Paragraph>来源：{review?.evidence.source_reference}</Typography.Paragraph>
      <Typography.Paragraph>请在外部核对原始文件、SHA256、完整日期范围和逐日数量。通过审批表示人工凭证已复核，不代表平台自动认证。</Typography.Paragraph>
      {reviewError && <Alert type="error" message={reviewError} />}
      <label htmlFor="coverage-review-note">复核 / 撤销备注</label>
      <Input.TextArea id="coverage-review-note" rows={3} value={note} disabled={busy} onChange={e => setNote(e.target.value)} />
    </Modal>
  </Card>
}
