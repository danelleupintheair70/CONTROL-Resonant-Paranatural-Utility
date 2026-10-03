// The same browser specs, run against the React build in ui/dist
// (docs/react-migration.md). `npm run test:browser:ui` builds first.
// UI_PORT and UI_DIR let several builds be tested side by side.
import { defineConfig } from '@playwright/test';
import { resolve } from 'node:path';
import base from './playwright.config.js';

const port = process.env.UI_PORT || '8767';
const dir = resolve(process.env.UI_DIR || 'ui/dist');

export default defineConfig({
  ...base,
  outputDir: `test-results/ui-${port}`,
  use: { ...base.use, baseURL: `http://127.0.0.1:${port}` },
  webServer: {
    ...base.webServer,
    command: base.webServer.command.replace(/--port \d+/, `--port ${port}`),
    url: `http://127.0.0.1:${port}/api/health`,
    env: { ...process.env, DOBLARR_UI: 'react', DOBLARR_UI_DIR: dir },
  },
});
