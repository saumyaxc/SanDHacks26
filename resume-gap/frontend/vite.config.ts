import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Same-origin calls to /api in dev: no CORS config needed on the backend.
    proxy: {
      // API_URL lets a second copy (e.g. a test server) run beside the normal one.
      '/api': process.env.API_URL ?? 'http://localhost:8000',
    },
  },
})
