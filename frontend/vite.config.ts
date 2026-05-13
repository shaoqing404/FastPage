import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const base = process.env.PAGEINDEX_BASE_PATH || '/'

// https://vite.dev/config/
export default defineConfig({
  base,
  plugins: [react()],
  server: {
    proxy: {
      '/api/v1': {
        target: 'http://127.0.0.1:22223',
        changeOrigin: true,
      }
    }
  }
})
