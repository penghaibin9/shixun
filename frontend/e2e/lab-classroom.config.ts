import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: ['lab-classroom.spec.ts', 'lab-classroom-live.spec.ts'],
  use: { baseURL: 'http://127.0.0.1:4185', browserName: 'chromium', headless: true },
  webServer: [
    { command: 'python -m uvicorn app.main:app --host 127.0.0.1 --port 18013', cwd: '../../backend', url: 'http://127.0.0.1:18013/health', reuseExistingServer: false },
    { command: 'npm run dev -- --host 127.0.0.1 --port 4185', cwd: '..', url: 'http://127.0.0.1:4185', reuseExistingServer: false },
  ],
})
