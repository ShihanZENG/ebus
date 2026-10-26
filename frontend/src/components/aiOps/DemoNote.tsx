import { Alert } from 'antd'

/**
 * 设计演示 / 虚构样例 隔离横幅。
 * 凡使用 aiOps.ts 中 source: 'demo' 的构造数据，页面必须挂此横幅，
 * 确保演示数据不伪装成真实接口返回（项目硬约定）。
 */
export default function DemoNote({ scope, compact = false }: { scope?: string; compact?: boolean }) {
  return (
    <Alert
      role="status"
      type="warning"
      showIcon
      message="设计演示 · 虚构样例"
      description={
        <span>
          本页{scope ? `「${scope}」` : ''}数据为前端构造的演示样例，用于展示功能形态与交互，并非真实接口返回。
          真实业务数据需后端对应能力上线后接入，标注「演示」的内容不构成经营结论。
        </span>
      }
      style={{ marginBottom: compact ? 12 : 16 }}
    />
  )
}
