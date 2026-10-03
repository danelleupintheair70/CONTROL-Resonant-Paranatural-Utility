import { defineConfig } from '@playwright/test';
import { existsSync } from 'node:fs';

const localPython = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
const python = process.env.PYTHON || (existsSync(localPython) ? localPython : 'python');
// PW_PORT lets several runs share the machine.
const port = process.env.PW_PORT || '8766';

export default defineConfig({
  testDir: './tests/frontend',
  testMatch: '*.spec.js',
  workers: 1,
  use: { baseURL: `http://127.0.0.1:${port}`, headless: true },
  webServer: {
    command: `"${python}" -m uvicorn browser_app:app --app-dir tests --host 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
  },
});
