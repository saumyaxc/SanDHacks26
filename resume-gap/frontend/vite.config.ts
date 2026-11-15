import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Same-origin calls to /api in dev: no CORS config needed on the backend.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
