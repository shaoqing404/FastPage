import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const base = process.env.PAGEINDEX_BASE_PATH || '/'

// https://vite.dev/config/
export default defineConfig({
  base,
  plugins: [react()],
})
