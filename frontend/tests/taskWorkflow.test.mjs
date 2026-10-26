import test from 'node:test'
import assert from 'node:assert/strict'
import { nextStage, taskUrl, safeOrigin, selectedVersion, createRequestGuard } from '../src/pages/taskWorkflow.ts'

test('next stage follows server state and available simulation', () => {
  for (const [state, versions, stage] of [['DRAFT',0,'strategy'],['DRAFT',1,'simulation'],['REJECTED',1,'strategy'],['SUBMITTED',1,'approval'],['APPROVED',1,'execution'],['EXECUTED',1,'result'],['CONFIRMED',1,'result']]) {
    assert.equal(nextStage(state, versions), stage)
  }
})

test('late results cannot replace a different task or reopen a closed drawer', () => {
  const guard = createRequestGuard()
  const taskA = guard.capture()
  guard.invalidate()
  const taskB = guard.capture()
  assert.equal(taskA(), false)
  assert.equal(taskB(), true)
  guard.invalidate()
  assert.equal(taskB(), false)
})
test('links carry task, stage and version and reject external return targets', () => {
  const url = new URL(taskUrl('task 1', 'simulation', '/ai-strategy-center', 'v2'), 'https://local.test')
  assert.equal(url.pathname, '/ai/tasks/task%201')
  assert.equal(url.searchParams.get('versionId'), 'v2')
  assert.equal(url.searchParams.get('tab'), 'simulation')
  assert.equal(safeOrigin('//evil.test'), '/ai-strategy-center')
  assert.equal(safeOrigin('/ai-approval-center'), '/ai-approval-center')
})
test('locked workflow always displays approved selection; draft prefers requested or newest version', () => {
  const versions = [{id:'v2'}, {id:'v1'}]
  assert.equal(selectedVersion('APPROVED', 'v1', versions, 'v2'), 'v1')
  assert.equal(selectedVersion('DRAFT', 'v1', versions), 'v2')
  assert.equal(selectedVersion('DRAFT', null, versions, 'v1'), 'v1')
  assert.equal(selectedVersion('DRAFT', null, versions, 'missing'), 'v2')
})
