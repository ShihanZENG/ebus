import type { ThemeConfig } from 'antd'

/**
 * 参考领星 ERP 的视觉：深色分组侧边导航 + 浅色内容区 + 蓝色主色。
 * 主色与圆角集中在这里，改一处即可整体换肤。
 */
export const erpTheme: ThemeConfig = {
  token: {
    colorPrimary: '#2b5cff',
    borderRadius: 6,
    fontSize: 14,
    colorBgLayout: '#f2f4f7',
  },
  components: {
    Layout: {
      siderBg: '#141b2b',
      headerBg: '#ffffff',
      headerHeight: 56,
      bodyBg: '#f2f4f7',
    },
    Menu: {
      darkItemBg: '#141b2b',
      darkSubMenuItemBg: '#0f1524',
      darkItemSelectedBg: '#2b5cff',
      darkItemHoverBg: 'rgba(43,92,255,0.18)',
    },
    Table: {
      headerBg: '#fafafa',
    },
    Card: {
      paddingLG: 20,
    },
  },
}
