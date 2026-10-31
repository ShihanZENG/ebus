import { Card, Collapse, Space, Tag, Typography } from 'antd'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { splitAssistantTaskReply } from './assistantTaskReply.mjs'
import './assistantTaskResult.css'

function Markdown({ text }: { text: string }) {
  return <div className="assistant-task-markdown">
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
      a: ({ children }) => <span>{children}</span>,
      img: () => null,
    }}>{text}</ReactMarkdown>
  </div>
}

export default function AssistantTaskResult({ reply, sources = [] }: { reply: string; sources?: string[] }) {
  const { conclusion, details } = splitAssistantTaskReply(reply)
  const sourceTags = sources.length ? <Space wrap className="assistant-task-sources">
    {[...new Set(sources)].map(source => <Tag key={source}>{source}</Tag>)}
  </Space> : null
  return <Card size="small" className="assistant-task-result" title="只读查询结果">
    {conclusion ? <>
      <Typography.Paragraph className="assistant-task-conclusion">{conclusion}</Typography.Paragraph>
      {details && <Collapse ghost size="small" items={[{
        key: 'details', label: '查看查询证据与限制',
        children: <><Markdown text={details} />{sourceTags}</>,
      }]} />}
      {!details && sourceTags}
    </> : <><Markdown text={details} />{sourceTags}</>}
  </Card>
}
