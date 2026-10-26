export const stages = [
  { key: 'risk', label: '风险详情' }, { key: 'strategy', label: '策略生成' },
  { key: 'simulation', label: '仿真对比' }, { key: 'approval', label: '审批' },
  { key: 'execution', label: '受控执行' }, { key: 'result', label: '结果记录' },
]
export function createRequestGuard() {
  let generation = 0
  return {
    invalidate: () => { generation += 1 },
    capture: () => { const current = generation; return () => generation === current },
  }
}
export function nextStage(status: string, versions: number): string {
  return ({ SUBMITTED: 'approval', APPROVED: 'execution', EXECUTED: 'result', CONFIRMED: 'result', REJECTED: 'strategy' } as Record<string, string>)[status] ?? (versions ? 'simulation' : 'strategy')
}
export function safeOrigin(origin: string | null): string {
  return ['/ai-risk-center', '/ai-strategy-center', '/ai-approval-center', '/ai-execution-center'].includes(origin ?? '') ? origin! : '/ai-strategy-center'
}
export function taskUrl(id: string, stage: string, origin: string, versionId?: string): string {
  const query = new URLSearchParams({ tab: stage, from: safeOrigin(origin) })
  if (versionId) query.set('versionId', versionId)
  return `/ai/tasks/${encodeURIComponent(id)}?${query}`
}
export function selectedVersion(status: string, selected: string | null, versions: { id: string }[], requested?: string | null): string | undefined {
  if (['SUBMITTED', 'APPROVED', 'EXECUTED', 'CONFIRMED'].includes(status)) return selected ?? undefined
  return versions.find(v => v.id === requested)?.id ?? versions[0]?.id
}
