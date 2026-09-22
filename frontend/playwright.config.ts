import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  use: { baseURL: 'http://127.0.0.1:4175', browserName: 'chromium', headless: true },
  webServer: [
    {
      command: 'python -m uvicorn app.main:app --host 127.0.0.1 --port 18003',
      cwd: '../backend',
      url: 'http://127.0.0.1:18003/health',
      reuseExistingServer: false,
      env: { ...process.env, YUEKE_ENV: 'test', YUEKE_ALLOW_DEV_IDENTITY_HEADERS: '1' },
    },
    { command: 'npm run dev -- --host 127.0.0.1 --port 4175', url: 'http://127.0.0.1:4175', reuseExistingServer: false },
  ],
})
