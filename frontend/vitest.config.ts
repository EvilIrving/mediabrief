import { defineConfig } from 'vitest/config'
import { fileURLToPath, URL } from 'node:url'

// 前端单元测试配置：jsdom 环境 + @ 别名，与 vite.config.ts 的 alias 保持一致。
export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
