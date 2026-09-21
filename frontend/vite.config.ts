import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: { proxy: { '/api': { target: 'http://127.0.0.1:18003', ws: true } } },
  test: { environment: 'jsdom', include: ['src/**/*.spec.ts'] },
})
