import test from 'node:test'
import assert from 'node:assert/strict'
import { splitAssistantTaskReply } from '../src/pages/assistantTaskReply.mjs'

test('separates the conclusion while preserving markdown evidence', () => {
  const reply = '## 结论：未找到 NAVA-001 的记录\n\n### 已核对的查询\n| 查询 | 结果 |\n|---|---|\n| 库存 | 无匹配 |'
  assert.deepEqual(splitAssistantTaskReply(reply), {
    conclusion: '未找到 NAVA-001 的记录',
    details: '### 已核对的查询\n| 查询 | 结果 |\n|---|---|\n| 库存 | 无匹配 |',
  })
})

test('keeps free-form replies intact', () => {
  assert.deepEqual(splitAssistantTaskReply('资料不足，请核对。'), {
    conclusion: null,
    details: '资料不足，请核对。',
  })
})
