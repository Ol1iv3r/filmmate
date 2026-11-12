import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base './' so the Tauri production build can load assets from relative paths.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    port: 5173,
    strictPort: false,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
})
