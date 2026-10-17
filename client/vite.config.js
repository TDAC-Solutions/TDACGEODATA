import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The SPA is served on :5173 and the API on :8000. Without this proxy a
    // request to /api/... resolves against :5173 and 404s, which is exactly
    // what happens to an <img src="/api/attachments/.../content"> — a media
    // element never goes through the fetch wrapper that could add a base
    // URL. Proxying /api makes development behave like the single-origin
    // production topology behind NGINX or an ingress.
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
