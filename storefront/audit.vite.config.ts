import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Isolated audit server: never proxies to the usual demo backend.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 15184,
    strictPort: true,
    proxy: { '/api/storefront': { target: 'http://127.0.0.1:18181', changeOrigin: true } },
  },
})
