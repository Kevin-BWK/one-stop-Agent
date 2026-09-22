import { fileURLToPath, URL } from 'node:url'

import uni from '@dcloudio/vite-plugin-uni'
import { defineConfig } from 'vite'

const BACKEND = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [uni()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    host: '127.0.0.1',
    // H5 仅用于调试：把后端接口代理过来，避免跨域
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/scenarios': { target: BACKEND, changeOrigin: true },
      '/apply': { target: BACKEND, changeOrigin: true },
      '/ws': { target: BACKEND.replace('http', 'ws'), ws: true }
    }
  }
})
