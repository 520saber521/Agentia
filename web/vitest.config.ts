import { defineConfig } from "vitest/config";

/**
 * Vitest 配置：与 vite.config.ts 解耦，避免把 dev server 的 proxy 一起拖进来。
 *
 * Day5 只跑纯函数 / store 层单测，jsdom 是给未来的组件测试预留的环境。
 */
export default defineConfig({
  test: {
    environment: "jsdom",
    globals: false,
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
