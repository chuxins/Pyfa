import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// The build output lands in web/static, which is what FastAPI serves.
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: '../static',
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    // npm run dev talks to the API running on 8080
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: false,
      },
      '/img': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: false,
      },
    },
  },
})
