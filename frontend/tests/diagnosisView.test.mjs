import test from 'node:test'
import assert from 'node:assert/strict'
import { buildDiagnosisView } from '../src/components/diagnosisView.ts'

const sampleDiagnosis = {
  diagnosis_id: 'abc123',
  shop_id: 'shop-1',
  period: { date_from: '2026-10-01', date_to: '2026-10-20' },
  domains: ['orders', 'ads', 'inventory_alignment', 'payments'],
  agents: [
    { domain: 'orders', agent: 'orders_agent', status: 'ok', ref_count: 2, gap_count: 0, finding_count: 0 },
    { domain: 'ads', agent: 'ads_agent', status: 'ok', ref_count: 1, gap_count: 1, finding_count: 0 },
    { domain: 'inventory_alignment', agent: 'inventory_alignment_agent', status: 'ok', ref_count: 1, gap_count: 0, finding_count: 1 },
    { domain: 'payments', agent: 'payments_agent', status: 'denied', ref_count: 0, gap_count: 1, finding_count: 0 },
  ],
  evidence_refs: [{ ref_id: 'r1' }, { ref_id: 'r2' }, { ref_id: 'r3' }, { ref_id: 'r4' }],
  gaps: [
    { code: 'ADS_COVERAGE_UNCONFIRMED' },
    { code: 'PERMISSION_REQUIRED', permission: 'finance_agent:read' },
  ],
  findings: [{ code: 'ADVERTISED_SKU_NO_AVAILABLE_STOCK', severity: 'high' }],
  permission_gaps: [{ domain: 'payments', permission: 'finance_agent:read' }],
  summary: '联合诊断覆盖 4 个领域智能体，共采集 4 条证据引用。',
  supervisor_plan: ['orders_agent', 'ads_agent', 'inventory_alignment_agent', 'payments_agent'],
  generated_at: '2026-10-23T00:00:00Z',
}

test('分离权限缺口与数据缺口，并生成编排拓扑', () => {
  const v = buildDiagnosisView(sampleDiagnosis)
  assert.equal(v.evidenceRefCount, 4)
  assert.equal(v.findings.length, 1)
  assert.equal(v.permissionGaps.length, 1)
  // 非权限缺口只保留 ADS_COVERAGE_UNCONFIRMED
  assert.equal(v.nonPermissionGaps.length, 1)
  assert.equal(v.nonPermissionGaps[0].code, 'ADS_COVERAGE_UNCONFIRMED')
  // 拓扑：supervisor → 四个 agent → synthesis
  assert.equal(v.dag.supervisor, 'supervisor')
  assert.equal(v.dag.synthesis, 'synthesis')
  assert.deepEqual(v.dag.agents, ['orders_agent', 'ads_agent', 'inventory_alignment_agent', 'payments_agent'])
})

test('降级：无效 / 空诊断不抛错，返回空视图', () => {
  const vNull = buildDiagnosisView(null)
  assert.equal(vNull.agents.length, 0)
  assert.equal(vNull.evidenceRefCount, 0)
  assert.equal(vNull.nonPermissionGaps.length, 0)
  assert.equal(vNull.dag.synthesis, 'synthesis')
  assert.deepEqual(vNull.dag.agents, [])

  const vEmpty = buildDiagnosisView({})
  assert.equal(vEmpty.agents.length, 0)
  assert.equal(vEmpty.summary, '')
})

test('降级：缺省 supervisor_plan 时从 agents 推导拓扑', () => {
  const { supervisor_plan, ...rest } = sampleDiagnosis
  const v = buildDiagnosisView(rest)
  assert.deepEqual(v.dag.agents, ['orders_agent', 'ads_agent', 'inventory_alignment_agent', 'payments_agent'])
})
