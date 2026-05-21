import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Vite dev server 把 /api 与 /ws 代理到 BFF（默认 :8788），
 * 这样前端代码里直接写相对路径即可，部署后由 BFF 同源托管。
 */
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
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
