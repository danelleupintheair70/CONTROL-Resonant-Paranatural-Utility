import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The React UI (see docs/react-migration.md). `npm run dev:ui` serves it with
// /api proxied to a running `doblarr serve`; `npm run build:ui` writes
// ui/dist, which the server serves when DOBLARR_UI=react.
export default defineConfig({
  root: import.meta.dirname,
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 5363,
    proxy: { '/api': { target: process.env.DOBLARR_API || 'http://127.0.0.1:6363', changeOrigin: true } },
  },
});
