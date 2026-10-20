import { Alert, Card, Empty } from 'antd'

const descriptions: Record<string, string> = {
  'ad-campaigns': '广告管理模块尚未接入。接入广告活动、投放表现和广告费用数据后，可在此统一查看。',
  'finance-settlements': '财务结算模块尚未接入。店铺结算、费用核对和利润核算功能将在此提供。',
  statistics: '经营统计模块尚未接入。当前可先在 BI 经营看板查看已接入的销售、库存和采购数据。',
}

export default function ComingSoonPage({ pageKey, title }: { pageKey: string; title: string }) {
  return (
    <Card title={title}>
      <Alert type="info" showIcon message="功能建设中" description={descriptions[pageKey] ?? '该功能尚未接入。'} />
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可展示的数据" style={{ margin: '32px 0' }} />
    </Card>
  )
}
