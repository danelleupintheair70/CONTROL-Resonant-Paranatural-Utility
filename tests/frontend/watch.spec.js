import { test, expect } from '@playwright/test';

const INFO = {
  job: { id: 'j1', title: 'Harbor Lights e02', status: 'done', target: 'es-419', input: 'e02.mkv', output: 'e02.mkv' },
  state: 'ready',
  tracks: [
    { stream: 1, lang: 'ja', title: '', default: true, codec: 'aac', ours: false, original: true },
    { stream: 7, lang: 'es', title: 'Spanish AI', default: false, codec: 'aac', ours: true, original: false }],
  subtitles: [],
  loudness: { window: 0.25, offset_db: 0, spans: [{ start: 64.5, end: 66.3, quieter_db: 13 }], curves: { original: [], ours: [] } },
  notes: [],
};

test('a dub has its own page: languages switch in place and notes are saved', async ({ page }) => {
  let note;
  await page.route('**/api/watch/j1', route => route.fulfill({ json: INFO }));
  await page.route('**/api/watch/j1/audio/*.mp4', route => route.fulfill({ status: 404, body: '' }));
  await page.route('**/api/watch/j1/notes', route => {
    note = route.request().postDataJSON();
    return route.fulfill({ json: { note: { ...note, id: 'n1', revision: 1, resolution: 'open' } } });
  });
  await page.goto('/watch/j1');
  const video = page.locator('video');
  await expect(video).toHaveAttribute('src', /audio\/7\.mp4/);
  await expect(page.getByRole('button', { name: 'Spanish AI (Doblarr)' })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'ja', exact: true }).click();
  await expect(video).toHaveAttribute('src', /audio\/1\.mp4/);
  await expect(page.locator('.watch-quiet-list li')).toHaveCount(1);
  await page.getByLabel('Note', { exact: true }).fill('the laugh is gone');
  await page.getByLabel('What is wrong').selectOption('lost sound');
  await page.getByRole('button', { name: 'Save note' }).click();
  await expect.poll(() => note).toMatchObject({ note: 'the laugh is gone', category: 'lost sound', track: 'ja' });
});

test('J and K step through the quieter spots and a reviewed run shows its lines', async ({ page }) => {
  const info = { ...INFO, job: { ...INFO.job, has_review: true, version: 'names test' },
    loudness: { ...INFO.loudness, spans: [...INFO.loudness.spans, { start: 120, end: 121.5, quieter_db: 27 }] } };
  await page.route('**/api/watch/j1', route => route.fulfill({ json: info }));
  await page.route('**/api/watch/j1/audio/*.mp4', route => route.fulfill({ status: 404, body: '' }));
  await page.route('**/api/jobs/j1/review', route => route.fulfill({ json: { segments: [
    { start: 1, end: 3, speaker: 'Mara', text_src: 'Where were you?', text_translated: '¿Dónde estabas?' }] } }));
  await page.goto('/watch/j1');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('names test');
  await page.locator('body').press('k');
  await expect(page.locator('.watch-row-near')).toContainText('1:04');
  await page.locator('body').press('k');
  await expect(page.locator('.watch-row-near')).toContainText('2:00');
  await page.locator('body').press('j');
  await expect(page.locator('.watch-row-near')).toContainText('1:04');
  await page.getByRole('button', { name: /≥ 25 dB/ }).click();
  await expect(page.locator('.watch-quiet-list li')).toHaveCount(1);
  await page.getByRole('tab', { name: 'Lines' }).click();
  await expect(page.locator('.watch-lines')).toContainText('¿Dónde estabas?');
  await expect(page.locator('.watch-now')).toContainText('Mara');
});
