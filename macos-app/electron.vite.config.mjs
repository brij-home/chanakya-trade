import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
  },
  renderer: {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8765',
          changeOrigin: true,
        },
        '/skills': {
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
      postcss: './postcss.config.js',
    },
  },
})
