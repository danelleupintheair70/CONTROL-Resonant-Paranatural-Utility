import { test, expect } from '@playwright/test';
import { mockLibraryItems } from './title-mocks.js';

const LIBRARY = { items: [{ title: 'Harbor Lights', tmdb_id: 77, original: 'ja', source: 'Radarr', path: '/local/harbor.mkv',
  media_type: 'movie', label: 'needs-dub', audio_langs: ['ja'] }], target_languages: ['es'], counts: {} };

const CAST = {
  series_id: 'movie:tmdb:77', title: 'Harbor Lights', conflicts: [{ name: 'Oren Pask', field: 'gender', values: { anilist: 'Male', ann: 'Female' } }],
  sources: [{ source: 'anilist' }, { source: 'ann' }],
  links: [{ id: 'movie:tmdb:77', source: 'anilist', title: 'Harbor Lights', url: 'https://anilist.co/anime/1', characters: 2, complete: true, why: '' },
    { id: 'movie:tmdb:77#ann', source: 'ann', title: 'Harbor Lights', url: 'https://www.animenewsnetwork.com/encyclopedia/anime.php?id=77', characters: 2, complete: true, why: 'same title, same year' }],
  characters: [
    { name: 'Mira Tavel', role: 'MAIN', sources: ['anilist', 'ann'], conflicts: [], voice_actors: [
      { name: 'Aki Sora', language: 'Japanese', sources: ['anilist', 'ann'] },
      { name: 'Lucia Prado', language: 'Spanish', sources: ['ann'] },
      { name: 'Dana Wells', language: 'English', sources: ['ann'] }] },
    { name: 'Oren Pask', role: 'SUPPORTING', sources: ['anilist', 'ann'], conflicts: ['gender'], voice_actors: [
      { name: 'Ren Tomoe', language: 'Japanese', sources: ['anilist'] }] },
  ],
};

const RUN = {
  id: 'rr-1', series_id: 'movie:tmdb:77', question: 'What does the dub call the guild?', sent: 'What does the dub call the guild? (about the film "Harbor Lights")',
  model: 'ollama/fake', depth: 'quick', cost: 0, answer: '## Names\nThe Spanish dub calls it **la Cofradía** [1].',
  sources: [{ n: 1, url: 'https://wiki.example/guild', title: 'Guild', cited: true }], gaps: [], claim_id: 'ext-1',
  terms: [{ source_form: '港組合', phrase: 'la Cofradía', usage: '[1]', entry_id: 'e1' }],
  leads: [{ character: 'Mira Tavel', matches: 'Mira Tavel', language: 'Spanish', voice_actor: 'Ana Ruiz', urls: ['https://wiki.example/guild'], state: 'open' }],
};

async function mockResearch(page, { enabled = true } = {}) {
  const posted = [];
  await page.route('**/api/published-cast/catalogues', route => route.fulfill({ json: { enabled, catalogues: [
    { name: 'anilist', label: 'AniList', host: 'anilist.co' }, { name: 'ann', label: 'Anime News Network', host: 'animenewsnetwork.com' },
    { name: 'jikan', label: 'MyAnimeList (Jikan)', host: 'api.jikan.moe' }] } }));
  await page.route('**/api/published-cast?*', route => route.fulfill({ json: CAST }));
  await page.route('**/api/research/runs?*', route => route.fulfill({ json: { runs: [
    { id: 'rr-1', question: RUN.question, created_at: '2026-10-03T10:00:00+00:00', sources: 1, terms: 1, open_leads: 1 }] } }));
  await page.route('**/api/research/runs/rr-1', route => route.fulfill({ json: RUN }));
  await page.route('**/api/research/scripts?*', route => route.fulfill({ json: { scripts: [
    { id: 'ts-1', source: 'imsdb', url: 'https://imsdb.com/scripts/Harbor-Lights.html', kind: 'screenplay', title: 'Harbor Lights', lines: 812, speakers: 14, language: 'en', episode: null }] } }));
  await page.route('**/api/research/titles?*', route => route.fulfill({ json: { known: { tmdb_film: '77' }, info: {
    external_ids: { tmdb_film: '77', ann: '77' }, aliases: [{ title: 'Luces del Puerto', language: 'es', region: 'MX' }] } } }));
  await page.route('**/api/research/leads', async route => {
    posted.push(route.request().postDataJSON());
    await route.fulfill({ json: { leads: [{ ...RUN.leads[0], state: 'accepted' }] } });
  });
  return posted;
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/library', route => route.fulfill({ json: LIBRARY }));
  await mockLibraryItems(page, LIBRARY);
});

test('the research tab shows the merged cast, cited answers and found scripts', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const posted = await mockResearch(page);
  await page.goto('/title/tmdb-77/research');
  const table = page.locator('#researchMergedCast');
  await expect(table.locator('th')).toHaveText(['Character', 'Role', 'Listed by', 'Japanese', 'Spanish', 'English']);
  await expect(table).toContainText('Lucia Prado');
  await expect(table).toContainText('sources disagree on gender');
  await expect(page.locator('#researchLinks')).toContainText('same title, same year');
  await expect(page.locator('#researchCastSearch')).toBeVisible();

  await page.getByRole('button', { name: /What does the dub call the guild/ }).click();
  const cite = page.locator('.research-answer a.research-cite');
  await expect(cite).toHaveText('[1]');
  await expect(cite).toHaveAttribute('href', 'https://wiki.example/guild');
  await expect(page.locator('.research-terms')).toContainText('inactive until you review them');
  await page.getByRole('button', { name: 'Accept' }).click();
  await expect.poll(() => posted.length).toBe(1);
  expect(posted[0]).toEqual({ run_id: 'rr-1', index: 0, decision: 'accept' });

  await expect(page.locator('#researchScripts')).toContainText('812');
  await expect(page.locator('#researchIds')).toContainText('ann 77');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('body')).toHaveJSProperty('scrollWidth', 390);
  await page.screenshot({ path: 'test-results/research-mobile.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('with research off nothing can reach the internet, but found data still shows', async ({ page }) => {
  await mockResearch(page, { enabled: false });
  await page.goto('/title/tmdb-77/research');
  await expect(page.locator('#researchOff')).toContainText('Title research is off');
  await expect(page.locator('#researchMergedCast')).toContainText('Aki Sora');
  await expect(page.locator('#researchCastSearch')).toHaveCount(0);
  await expect(page.locator('#researchAsk')).toHaveCount(0);
  await expect(page.locator('#researchScriptsFind')).toHaveCount(0);
});
