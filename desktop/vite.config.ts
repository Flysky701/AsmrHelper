import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    // Optional loopback proxy for isolated frontend previews on a different port.
    // Production API routing and backend CORS policy remain unchanged.
    proxy: process.env.ASMR_PREVIEW_BACKEND ? {
      '/api/v1': { target: process.env.ASMR_PREVIEW_BACKEND, changeOrigin: true },
    } : undefined,
    watch: {
      // Cargo continuously writes PDB and object files here during `tauri dev`.
      // Watching those files on Windows can terminate Vite with EBUSY.
      ignored: ['**/src-tauri/target/**'],
    },
  },
  build: {
    outDir: 'dist',
  },
})
