import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Dev-only proxy: Core (FastAPI) does not yet send CORS headers, so a
    // browser on the Vite origin cannot call http://localhost:8000
    // cross-origin. Running the dev server with VITE_API_BASE= (empty)
    // makes the app call same-origin /api/... and /health, which Vite
    // forwards to Core here. With the default VITE_API_BASE
    // (http://localhost:8000) the browser calls Core directly and Core
    // must add CORS support (tracked as a backend gap).
    proxy: {
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
