import { test, expect } from '@playwright/test';

const variant = (id, tag, title, tracks, extra = {}) => ({
  id, tag, title, channels: '2.0', kind: '', mismatch: false, tracks, titles: 1,
  where: [{ label: 'Harbor Lights', tracks }], ...extra });

const SCAN = {
  scanned_at: '2026-10-03T12:00:00', dry_run: false, writer: 'ffmpeg', apply: { state: 'idle' },
  totals: { tracks: 9, to_fix: 6, und: 2, mismatched_tag: 0, inconsistent_titles: 4, wrong_default: 0 },
  languages: [{ id: 'ja', name: 'Japanese', code: 'jpn' }, { id: 'es-419', name: 'Spanish (Latin America)', code: 'spa' }],
  buckets: [
    { lang: 'und', name: 'Unknown language', code: 'und', tracks: 2, variants: [variant('u1', 'und', 'Stereo', 2)] },
    { lang: 'es-419', name: 'Spanish (Latin America)', code: 'spa', tracks: 7, variants: [
      variant('l1', 'spa', 'Latino', 4), variant('l2', 'spa', 'Spanish (Latin America) 2.0', 3)] },
  ],
};

test('tracks are renamed to one style and unknown ones get a language picked', async ({ page }) => {
  let sent;
  await page.route('**/api/audio-languages', route => route.fulfill({ json: SCAN }));
  await page.route('**/api/audio-languages/apply', route => {
    if (route.request().method() === 'POST') {
      sent = route.request().postDataJSON();
      return route.fulfill({ json: { state: 'done', files: 1, tracks: 4, done: 1, failed: [], message: 'Every picked track was rewritten.' } });
    }
    return route.fulfill({ json: { state: 'idle' } });
  });
  await page.goto('/library/audio');
  await expect(page.getByRole('heading', { name: 'Audio languages' })).toBeVisible();

  // Unknown tracks change only once someone says what they are.
  await expect(page.getByRole('button', { name: 'Nothing selected' })).toBeDisabled();
  await page.getByLabel('What language this is').selectOption('ja');
  await expect(page.getByRole('button', { name: 'Normalize 2 tracks' })).toBeEnabled();

  await page.getByRole('button', { name: /Spanish \(Latin America\)/ }).first().click();
  await expect(page.getByText('already named this way')).toBeVisible();
  await page.getByRole('button', { name: 'English', exact: true }).click();
  await expect(page.getByText('Spanish (Latin America)', { exact: true }).last()).toBeVisible();
  await page.getByRole('button', { name: 'English 5.1' }).click();
  await page.getByRole('button', { name: 'Normalize 4 tracks' }).click();
  await expect.poll(() => sent).toMatchObject({
    scanned_at: SCAN.scanned_at,
    changes: [{ id: 'l1', language: 'es-419', title: 'Spanish (Latin America) 2.0' }] });
  await expect(page.getByRole('status')).toContainText('Every picked track was rewritten.');
});
