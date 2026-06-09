import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8788",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://127.0.0.1:8788",
        ws: true,
        changeOrigin: true,
      },
      "/health": {
        target: "http://127.0.0.1:8788",
        changeOrigin: true,
      },
      "/preview": {
        target: "http://127.0.0.1:8788",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
