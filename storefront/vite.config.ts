import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 15174, strictPort: true,
    proxy: { '/api/storefront': { target: 'http://127.0.0.1:18081', changeOrigin: true } } },
})
