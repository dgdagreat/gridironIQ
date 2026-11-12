import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies /api -> the FastAPI layer (gridiron.api:app on :8000), so
// the client fetches relative paths and there's no CORS dance in development.
// Override the API host with GRIDIRON_API_URL when it runs elsewhere.
const API = process.env.GRIDIRON_API_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: API,
        changeOrigin: true,
        // The API lets browsers reuse GET responses for five minutes. In dev that
        // would hide an API change behind a cached response, so turn it off here.
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['cache-control'] = 'no-store'
          })
        },
      },
    },
  },
})
