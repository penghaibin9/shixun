import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  use: { baseURL: 'http://127.0.0.1:4185', browserName: 'chromium', headless: true },
  webServer: [
    {
      command: 'python -m uvicorn app.main:app --host 127.0.0.1 --port 18013',
      cwd: '../backend',
      url: 'http://127.0.0.1:18013/health',
      reuseExistingServer: false,
      env: { ...process.env, YUEKE_ENV: 'test', YUEKE_ALLOW_DEV_IDENTITY_HEADERS: '1' },
    },
    { command: 'npx vite --config e2e/grading-vite.config.ts --host 127.0.0.1 --port 4185', url: 'http://127.0.0.1:4185', reuseExistingServer: false },
  ],
})
