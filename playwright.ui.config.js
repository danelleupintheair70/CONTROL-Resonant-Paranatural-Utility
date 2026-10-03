// The same browser specs, run against the React build in ui/dist
// (docs/react-migration.md). `npm run test:browser:ui` builds first.
import { defineConfig } from '@playwright/test';
import base from './playwright.config.js';

export default defineConfig({
  ...base,
  outputDir: 'test-results/ui',
  use: { ...base.use, baseURL: 'http://127.0.0.1:8767' },
  webServer: {
    ...base.webServer,
    command: base.webServer.command.replace('--port 8766', '--port 8767'),
    url: 'http://127.0.0.1:8767/api/health',
    env: { ...process.env, DOBLARR_UI: 'react' },
  },
});
