import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { loadAdminCredentials } from './scripts/demoCredentials.mjs'

// 后端默认监听 127.0.0.1:18080，前端通过 /api 代理转发，避免跨域与端口硬编码。
//
// 预构建缓存默认放在 node_modules/.vite，Vite 重新优化依赖时会删除其中的临时目录；
// 本机安全策略拦截项目内的删除操作，会导致 dev server 崩溃。这里改为放到系统临时目录，
// 可用 VITE_CACHE_DIR 覆盖。
const cacheDir = process.env.VITE_CACHE_DIR || path.join(os.tmpdir(), 'crossborder-erp-vite')

export default defineConfig(({ command }) => ({
  plugins: [react()],
  cacheDir,
  // 演示凭据只进入本地 dev server 的内存构建，永不注入生产 bundle。
  define: {
    __LOCAL_DEMO_CREDENTIALS__: command === 'serve'
      ? JSON.stringify(loadAdminCredentials(fileURLToPath(new URL('../backend/.env', import.meta.url))))
      : 'null',
  },
  // 提前声明依赖，避免运行时发现新依赖触发二次预构建。
  optimizeDeps: {
    include: [
      'react',
      'react-dom',
      'react-dom/client',
      'react-router-dom',
      'antd',
      'antd/locale/zh_CN',
      '@ant-design/icons',
      'axios',
      'dayjs',
      'dayjs/locale/zh-cn',
    ],
  },
  server: {
    host: '127.0.0.1',
    port: 15173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:18080',
        changeOrigin: true,
      },
    },
  },
}))
