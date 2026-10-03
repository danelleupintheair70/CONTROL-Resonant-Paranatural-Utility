import { defineConfig } from '@playwright/test';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

const localPython = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
const python = process.env.PYTHON || (existsSync(localPython) ? localPython : 'python');
// PW_PORT lets several runs share the machine; UI_DIR tests another build
// than ui/dist (`npm run test:browser` builds ui/dist first).
const port = process.env.PW_PORT || '8766';
const uiDir = resolve(process.env.UI_DIR || 'ui/dist');

export default defineConfig({
  testDir: './tests/frontend',
  testMatch: '*.spec.js',
  workers: 1,
  outputDir: `test-results/${port}`,
  use: { baseURL: `http://127.0.0.1:${port}`, headless: true },
  webServer: {
    command: `"${python}" -m uvicorn browser_app:app --app-dir tests --host 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    env: { ...process.env, DOBLARR_UI_DIR: uiDir },
  },
});
