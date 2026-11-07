import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  root: resolve(__dirname, 'src/renderer'),
  plugins: [react()],
  server: {
    port: 5173,
    host: '127.0.0.1',
    watch: {
      usePolling: true,
      interval: 100,
    },
    headers: {
      'Cache-Control': 'no-store, no-cache, must-revalidate',
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
      '/skills': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
      '/stream': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
      '/auth': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
      '/broker-login': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
      '/mstock': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
  },
  css: {
    postcss: resolve(__dirname, 'postcss.config.js'),
  },
})
