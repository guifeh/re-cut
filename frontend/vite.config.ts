import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// em dev, /api e /files vão para o server.py (porta 8000); changeOrigin: o server só aceita Host localhost:8000
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  server: { proxy: {
    '/api': { target: 'http://localhost:8000', changeOrigin: true },
    '/files': { target: 'http://localhost:8000', changeOrigin: true },
  } },
})
