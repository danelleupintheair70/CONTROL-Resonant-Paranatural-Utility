import { test, expect } from '@playwright/test';

const KAITO = {
  key: 'profile:vb-n', profile_id: 'vb-n', name: 'HarborLights-S01E02-scene-3-0f1e2d3c',
  engine: 'chatterbox', kind: 'cloned', language: 'es', gender: 'male', age: 'young',
  display_name: 'Kaito', character: 'KAITO', show: 'tvdb-81234', show_name: 'Harbor Lights',
};
const CLONE = { key: 'profile:vb-x', profile_id: 'vb-x', name: 'Episode-0123456789abcdef',
  engine: 'chatterbox', kind: 'cloned', language: 'es', gender: 'unknown', age: 'unknown' };
const PRESET = { key: 'preset:kokoro:em', preset_id: 'em', name: 'Alex', engine: 'kokoro',
  kind: 'preset', language: 'es', gender: 'male', age: 'unknown' };

async function routes(page) {
  await page.route('**/api/library', route => route.fulfill({ json: { items: [], counts: {} } }));
  await page.route('**/api/voice-catalog', route => route.fulfill({ json: { voices: [KAITO, CLONE, PRESET], warnings: [] } }));
  await page.route('**/api/voice-catalog/voice?*', route => route.fulfill({ json: {
    voice: KAITO, used_in: [{ title_key: 'e02', title: 'S01E02', speaker: 'KAITO', label: 'Kaito',
      pitch_semitones: 0, formant_semitones: 2 }] } }));
}

test('the voices page lists the named cast by show and hides working clones behind a filter', async ({ page }) => {
  await routes(page);
  await page.goto('/voices');
  await expect(page.locator('.voices-group h3')).toContainText('Harbor Lights');
  await expect(page.locator('.voice-tile')).toHaveCount(1);
  await page.getByRole('button', { name: /Working clones/ }).click();
  await expect(page.locator('.voices-table tbody tr')).toHaveCount(1);
  await expect(page.locator('.voices-table')).toContainText('Episode-0123456789abcdef');
  await page.getByRole('button', { name: /^Cast/ }).click();
  await page.locator('.voice-tile').click();
  await expect(page).toHaveURL(/\/voices\/profile%3Avb-n$/);
});

test('one voice has its own page with an orb, a preview and who it is', async ({ page }) => {
  await routes(page);
  let saved = null;
  await page.route('**/api/voice-catalog/traits', async route => {
    saved = route.request().postDataJSON();
    await route.fulfill({ json: { ok: true } });
  });
  await page.goto('/voices/profile%3Avb-n');
  await expect(page.locator('.voice-hero h2')).toHaveText('Kaito');
  await expect(page.locator('.voice-orb, .voice-dot-xl')).toBeVisible();
  await expect(page.locator('#voiceUsed').locator('..')).toContainText('+2 st formant');
  await page.locator('[data-t="notes"]').fill('Loud and excitable.');
  await page.locator('.voice-color-input').fill('#f08a24');
  await page.getByRole('button', { name: 'Save' }).click();
  await expect.poll(() => saved?.notes).toBe('Loud and excitable.');
  expect(saved).toMatchObject({ key: 'profile:vb-n', display_name: 'Kaito', show: 'tvdb-81234',
    color: '#f08a24' });
  await page.getByRole('link', { name: '← All voices' }).click();
  await expect(page).toHaveURL(/\/voices$/);
});
