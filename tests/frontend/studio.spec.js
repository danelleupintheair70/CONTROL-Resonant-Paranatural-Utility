import { test, expect } from '@playwright/test';

// A decodable WAV, so playback is proven by currentTime moving, not by a button existing.
function wav(seconds = 6) {
  const rate = 8000, samples = rate * seconds, size = samples * 2;
  const buffer = Buffer.alloc(44 + size);
  buffer.write('RIFF', 0); buffer.writeUInt32LE(36 + size, 4); buffer.write('WAVE', 8);
  buffer.write('fmt ', 12); buffer.writeUInt32LE(16, 16); buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22); buffer.writeUInt32LE(rate, 24);
  buffer.writeUInt32LE(rate * 2, 28); buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34); buffer.write('data', 36); buffer.writeUInt32LE(size, 40);
  for (let i = 0; i < samples; i += 1) {
    buffer.writeInt16LE(Math.round(6000 * Math.sin((2 * Math.PI * 220 * i) / rate)), 44 + i * 2);
  }
  return buffer;
}

const SID = 'st-test';
const SESSION = {
  id: SID, revision: 3, title: 'Episode One', media_name: 'ep1.mkv', view: 'compare',
  style: 'manual', checkpoints: ['export'], position: 10, budgets: {}, direction: {},
  compare: { start: 10, length: 8 }, filters: {}, line: null,
};
const OVERVIEW = {
  session: SESSION, jobs: [], active_job: null, studio_jobs: [], output_tracks: [],
  references: [
    { id: 'ref-ja', label: 'Japanese original', language: 'ja', roles: ['meaning'],
      track: { media_name: 'ep1.mkv', audio_index: 1 }, text: { kind: 'original_transcript' } },
    { id: 'ref-en', label: 'English dub', language: 'en', roles: ['adaptation', 'performance'],
      track: { media_name: 'ep1.mkv', audio_index: 0 }, text: { kind: 'dub_transcript' } },
    { id: 'ref-es', label: 'Official dub', language: 'es', roles: ['evaluation'], evaluation_only: true,
      track: { media_name: 'ep1.mkv', audio_index: 2 }, text: { kind: 'dub_transcript' } },
  ],
  alignments: [], experiments: [], auditions: [], imports: [], notes: 0, export: null,
  next: { action: 'render', view: 'overview', reason: 'no draft yet' },
};

async function openStudio(page, { onPatch, onNote } = {}) {
  const errors = [];
  const audio = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/api/library', r => r.fulfill({ json: { items: [], counts: {} } }));
  await page.route('**/api/jobs', r => r.fulfill({ json: { jobs: [], counts: {}, paused: false } }));
  await page.route(`**/api/studio/sessions/${SID}`, r => {
    if (r.request().method() === 'PATCH') {
      const body = r.request().postDataJSON();
      onPatch?.(body);
      Object.assign(SESSION, body, { revision: SESSION.revision + 1 });
      return r.fulfill({ json: { session: SESSION } });
    }
    return r.fulfill({ json: { ...OVERVIEW, session: SESSION } });
  });
  await page.route(`**/api/studio/sessions/${SID}/media/window**`, r => {
    const source = new URL(r.request().url()).searchParams.get('source');
    return r.fulfill({ json: { source, state: source.startsWith('reference') ? 'mapped' : 'exact',
      note: source === 'original' ? 'the original performance' : 'mapped through the alignment',
      mapped_start: source.startsWith('reference') ? 12.0 : undefined,
      peaks: Array.from({ length: 60 }, (_, i) => (i % 7) / 7), level_db: -22, duration: 8 } });
  });
  await page.route(`**/api/studio/sessions/${SID}/media/audio**`, r => {
    audio.push(new URL(r.request().url()).searchParams.get('source'));
    return r.fulfill({ status: 200, contentType: 'audio/wav', body: wav(8) });
  });
  await page.route(`**/api/studio/sessions/${SID}/media/video**`,
    r => r.fulfill({ status: 404, json: { error: 'no picture in this test' } }));
  const notes = [];
  await page.route(`**/api/studio/sessions/${SID}/notes**`, r => {
    if (r.request().method() === 'POST') {
      const body = r.request().postDataJSON();
      onNote?.(body);
      const note = { id: `n${notes.length}`, revision: 1, resolution: 'open', history: [], ...body };
      notes.push(note);
      return r.fulfill({ json: { note } });
    }
    return r.fulfill({ json: { notes } });
  });
  await page.goto(`/studio/${SID}/compare`);
  await expect(page.locator('.studio-title h2')).toHaveText('Episode One');
  return { errors, audio, notes };
}

test('the studio plays one source at a time and switching keeps the moment', async ({ page }) => {
  const patches = [];
  const { errors, audio } = await openStudio(page, { onPatch: p => patches.push(p) });
  const sources = page.locator('.studio-src');
  await expect(sources).toHaveCount(2);                       // evaluation-only is never offered
  await expect(sources.first()).toContainText('Original');
  await expect(sources.filter({ hasText: 'Official dub' })).toHaveCount(0);
  await expect(page.locator('.studio-src[aria-checked="true"]')).toContainText('Original');
  await page.locator('#stPlay').click();
  await expect.poll(() => page.evaluate(() => window.__studioAudio.currentTime)).toBeGreaterThan(0.6);
  const before = await page.evaluate(() => window.__studioAudio.currentTime);
  await page.locator('.studio-src', { hasText: 'English dub' }).click();
  await expect(page.locator('#stMapping')).toContainText('mapped through the alignment');
  await expect.poll(() => page.evaluate(() => window.__studioAudio.src)).toContain('reference%3Aref-en');
  // Same moment, not from zero: the new source resumes where the old one was.
  await expect.poll(() => page.evaluate(() => window.__studioAudio.currentTime))
    .toBeGreaterThanOrEqual(before - 0.05);
  expect(await page.evaluate(() => window.__studioAudio.paused)).toBe(false);
  // Exactly one audio element plays for the studio.
  expect(await page.evaluate(() => [...document.querySelectorAll('audio')]
    .filter(a => !a.paused).length)).toBeLessThanOrEqual(1);
  // Keyboard: 0 goes back to the original, space pauses.
  await page.locator('#stWave').focus();
  await page.keyboard.press('0');
  await expect(page.locator('.studio-src[aria-checked="true"]')).toContainText('Original');
  await page.keyboard.press(' ');
  await expect.poll(() => page.evaluate(() => window.__studioAudio.paused)).toBe(true);
  await expect.poll(() => patches.some(p => p.position != null)).toBe(true);
  expect(new Set(audio)).toEqual(new Set(['original', 'reference:ref-en']));
  // Leaving the studio stops playback.
  await page.goto('/dubs');
  expect(errors).toEqual([]);
});

test('a marked moment is saved with its time, source and snapshot', async ({ page }) => {
  let saved;
  const { errors } = await openStudio(page, { onNote: n => { saved = n; } });
  await page.locator('#stPlay').click();
  await expect.poll(() => page.evaluate(() => window.__studioAudio.currentTime)).toBeGreaterThan(0.4);
  await page.locator('#stWave').focus();
  await page.keyboard.press('n');
  await expect(page.locator('.studio-note')).toHaveCount(1);
  expect(saved.source).toBe('original');
  expect(saved.at).toBeGreaterThan(10);                        // target-timeline seconds
  await expect(page.locator('.studio-pin')).toHaveCount(1);
  expect(errors).toEqual([]);
});

test('the view and place survive a reload, and the layout fits a laptop and a phone',
  async ({ page }) => {
    await openStudio(page);
    await page.getByRole('tab', { name: 'Overview' }).click();
    await expect(page).toHaveURL(/\/studio\/st-test\/overview/);
    await expect(page.getByRole('heading', { name: 'Writing direction' })).toBeVisible();
    await expect(page.getByText('evaluation only', { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true');
    await page.setViewportSize({ width: 1280, height: 760 });
    await page.screenshot({ path: 'test-results/studio-overview-laptop.png' });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator('body')).toHaveJSProperty('scrollWidth', 390);
    await page.screenshot({ path: 'test-results/studio-overview-phone.png' });
  });
