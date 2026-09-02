import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Прокси /api -> локальный бэкенд в dev-режиме (npm run dev), чтобы не настраивать
// CORS и работать с теми же относительными путями, что и в проде — там собранный
// dist/ раздаётся самим FastAPI с того же origin (см. backend/app/api/system.py).
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
