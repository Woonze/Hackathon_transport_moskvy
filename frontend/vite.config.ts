import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Бэкенд для dev-режима; по умолчанию 8000, другой порт: VITE_API_TARGET=http://127.0.0.1:8010 npm run dev
    proxy: { '/api': { target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000', changeOrigin: true } },
  },
})
