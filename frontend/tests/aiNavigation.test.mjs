import test from 'node:test'
import assert from 'node:assert/strict'
import { SYSTEM_NAV, findSystemNavigation } from '../src/config/menu.ts'

const ai = SYSTEM_NAV.find(system => system.id === 'ai')
const leaves = nodes => nodes.flatMap(node => node.children ? leaves(node.children) : [node])

test('AI navigation has the seven approved business entries without requirement codes', () => {
  assert.deepEqual(ai.nav.map(node => node.label), [
    '经营驾驶舱', 'AI Copilot', '风险与任务中心', '策略决策中心',
    '审批与执行中心', '效果复盘中心', '业务智能应用',
  ])
  assert.ok(leaves(ai.nav).every(node => !/AI-(PG|M)\d*/.test(node.label)))
})

test('each previous AI page stays reachable once under the new navigation', () => {
  const keys = leaves(ai.nav).map(node => node.key)
  assert.equal(new Set(keys).size, keys.length)
  for (const key of ['ai-dashboard', 'ai-copilot', 'ai-risk-center', 'ai-strategy-center',
    'ai-approval-center', 'ai-agent-workbench', 'ai-task-history', 'ai-strategy-templates',
    'ai-effect-overview', 'product-agent', 'operations-agent', 'lim-replenishment',
    'purchase-agent', 'ad-growth', 'profit-finance', 'customer-agent']) {
    assert.ok(keys.includes(key), key)
    assert.equal(findSystemNavigation('/' + key).id, 'ai')
  }
})
