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
