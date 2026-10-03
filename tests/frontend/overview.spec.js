import { test, expect } from '@playwright/test';

const LIBRARY = {
  target_languages: ['es'], counts: { needs_dub: 2 }, warnings: [],
  items: [
    { title: 'Harbor Lights', year: 2021, tvdb_id: 7, media_type: 'show', source: 'Sonarr', status: 'needs-dub', label: 'needs-dub' },
    { title: 'Test Film', year: 2024, tmdb_id: 42, original: 'ko', path: '/m/film.mkv', source: 'Radarr', status: 'needs-dub', label: 'needs-dub' }],
};
const JOBS = { counts: { done: 1, failed: 1 }, paused: false, jobs: [
  { id: 'd1', title: 'Harbor Lights S01E02', status: 'done', has_file: true, kind: 'full', source_lang: 'ja',
    target_lang: 'es', target_locale: 'es-419', version_name: 'names test', updated_at: '2026-10-03T21:11:00' },
  { id: 'f1', title: 'Test Film', status: 'failed', kind: 'full', source: 'radarr', source_lang: 'ko', target_lang: 'es',
    input_file: '/m/film.mkv', stage: 'mix', message: 'stems shorter than video', updated_at: '2026-10-03T20:53:00' }] };

test('overview leads with what is ready and what needs a hand', async ({ page }) => {
  let retried;
  await page.route('**/api/library', route => route.fulfill({ json: LIBRARY }));
  await page.route('**/api/audio-languages', route => route.fulfill({ status: 404, json: { error: 'no Plex' } }));
  await page.route('**/api/jobs', route => {
    if (route.request().method() === 'POST') { retried = route.request().postDataJSON(); return route.fulfill({ json: { ok: true } }); }
    return route.fulfill({ json: JOBS });
  });
  await page.goto('/');
  await expect(page.locator('h1')).toHaveText('1 dub ready to hear, 1 thing needs you');
  await expect(page.getByRole('link', { name: 'Review next dub' })).toHaveAttribute('href', '/watch/d1');
  await expect(page.getByRole('link', { name: 'Watch & compare' })).toBeVisible();
  await expect(page.getByLabel('Audio tracks across your library')).toHaveCount(0);
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect.poll(() => retried).toMatchObject({ title: 'Test Film', path: '/m/film.mkv', target_lang: 'es' });
  // A show is queued episode by episode, so only the film can be ticked here.
  await expect(page.getByLabel('Queue Harbor Lights')).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Select titles' })).toBeDisabled();
  await page.getByLabel('Queue Test Film').check();
  await expect(page.getByRole('button', { name: 'Queue 1 selected' })).toBeEnabled();
});

test('the audio band reports the track scan when Plex answers', async ({ page }) => {
  await page.route('**/api/library', route => route.fulfill({ json: LIBRARY }));
  await page.route('**/api/jobs', route => route.fulfill({ json: { counts: {}, jobs: [] } }));
  await page.route('**/api/audio-languages', route => route.fulfill({ json: { totals: {
    tracks: 3412, to_fix: 1106, und: 412, mismatched_tag: 0, inconsistent_titles: 406, wrong_default: 97 }, buckets: [] } }));
  await page.goto('/');
  const band = page.getByLabel('Audio tracks across your library');
  await expect(band).toContainText('1,106 of 3,412 audio tracks are named inconsistently');
  await expect(band).toContainText('Wrong default track');
  await expect(band).not.toContainText('Tag ≠ what’s heard');
  await expect(band.getByRole('link', { name: 'Review audio languages' })).toHaveAttribute('href', '/library/audio');
});
