import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/trace': { target: 'http://localhost:5000', changeOrigin: true },
      '/audit': { target: 'http://localhost:5000', changeOrigin: true },
      '/session': { target: 'http://localhost:5000', changeOrigin: true },
      '/knowledge': { target: 'http://localhost:5000', changeOrigin: true },
      '/health': { target: 'http://localhost:5000', changeOrigin: true },
      '/socket.io': {
        target: 'http://localhost:5000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
