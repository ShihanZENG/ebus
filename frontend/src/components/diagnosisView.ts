import type { LimDiagnosis } from '../api/lim'

/** 把后端返回的 LimDiagnosis 归一化为前端展示结构。
 *
 * 纯函数、零运行时依赖（仅 type-only 引用 LimDiagnosis），可被 node:test 直接覆盖。
 */
export interface DiagnosisView {
  agents: LimDiagnosis['agents']
  evidenceRefs: Array<Record<string, unknown>>
  evidenceRefCount: number
  findings: LimDiagnosis['findings']
  permissionGaps: LimDiagnosis['permission_gaps']
  /** 排除 PERMISSION_REQUIRED 后的「数据缺口」，用于「数据缺口（非权限）」表。 */
  nonPermissionGaps: Array<Record<string, unknown>>
  /** LangGraph 编排拓扑：supervisor → agents → synthesis。 */
  dag: { supervisor: string; agents: string[]; synthesis: string }
  summary: string
}

export function buildDiagnosisView(diagnosis: LimDiagnosis | null | undefined): DiagnosisView {
  const d = (diagnosis ?? {}) as LimDiagnosis
  const gaps = Array.isArray(d.gaps) ? d.gaps : []
  const permissionGaps = Array.isArray(d.permission_gaps) ? d.permission_gaps : []
  const findings = Array.isArray(d.findings) ? d.findings : []
  const agents = Array.isArray(d.agents) ? d.agents : []
  const evidenceRefs = Array.isArray(d.evidence_refs) ? d.evidence_refs : []
  const supervisorPlan =
    Array.isArray(d.supervisor_plan) && d.supervisor_plan.length
      ? d.supervisor_plan
      : agents.map((a) => a.agent)
  return {
    agents,
    evidenceRefs,
    evidenceRefCount: evidenceRefs.length,
    findings,
    permissionGaps,
    nonPermissionGaps: gaps.filter((g) => (g as Record<string, unknown>).code !== 'PERMISSION_REQUIRED'),
    dag: { supervisor: 'supervisor', agents: supervisorPlan, synthesis: 'synthesis' },
    summary: d.summary ?? '',
  }
}
