import { test, expect } from '@playwright/test';

async function show(page) {
  await page.route('**/api/library', route => route.fulfill({ json: { items: [{
    title: 'Harbor Lights', tvdb_id: 81234, media_type: 'show', source: 'Plex · TV Shows',
    original: '??', path: '/shows/HarborLights', audio_langs: ['en', 'ja'], label: 'available',
  }], target_languages: ['en', 'es'], counts: {} } }));
  await page.route('**/api/series/81234/episodes?*', route => route.fulfill({ json: {
    title: 'Harbor Lights', total: 1, downloaded: 1, dubbed: 0, episodes: [
      { id: 2, season: 1, episode: 2, title: 'The Storm Makes Its Move', downloaded: true,
        path: '/shows/HarborLights/e02.mkv', audio_langs: ['en', 'ja'], status: 'needs-dub', dubbed: false }] } }));
  await page.route('**/api/voices', route => route.fulfill({ json: { voices: [] } }));
}

const ANALYSED = {
  analysed: true, names: {}, total_seconds: 10, measured: true, job: null,
  languages: { text: 'en', original: 'ja', original_text: true },
  speakers: [{ speaker: 'SPEAKER_00', share: 0.6 }, { speaker: 'SPEAKER_01', share: 0.4 }],
  lines: [
    { index: 0, start: 1, end: 4, speaker: 'SPEAKER_00', character: '', text: 'Believe it!',
      original_text: 'だってばよ!', relative_db: 6, band: 'intense', pitch_hz: 260, movement_st: 4.4, uncertain: false },
    { index: 1, start: 5, end: 8, speaker: 'SPEAKER_01', character: '', text: 'Kaito.',
      original_text: 'ナルト。', relative_db: 0, band: 'calm', pitch_hz: 290, movement_st: 2.1, uncertain: false },
  ],
};

test('an episode opens on its analysis and a scan is one button away', async ({ page }) => {
  await show(page);
  await page.route('**/api/analysis?*', route => route.fulfill({ json: { analysed: false, job: null } }));
  let queued;
  await page.route('**/api/series/81234/queue', route => {
    queued = route.request().postDataJSON();
    return route.fulfill({ json: { queued: [{ episode_id: 2, job_id: 'a1' }], skipped: [] } });
  });
  await page.goto('/title/tvdb-81234');
  await page.getByRole('link', { name: 'The Storm Makes Its Move' }).click();
  await expect(page).toHaveURL(/\/episode\/2\/analysis$/);
  await page.getByRole('button', { name: 'Analyze episode' }).click();
  await expect.poll(() => queued?.kind).toBe('analyze');
  expect(queued).toMatchObject({ episode_ids: [2], missing_only: false });
});

test('the breakdown names voices, filters training lines and plays a line', async ({ page }) => {
  await show(page);
  let names;
  await page.route('**/api/analysis?*', route => route.fulfill({ json: ANALYSED }));
  await page.route('**/api/analysis/names', route => {
    names = route.request().postDataJSON();
    return route.fulfill({ json: { names: names.names } });
  });
  await page.goto('/title/tvdb-81234/episode/2/analysis');
  await expect(page.locator('.analysis-line')).toHaveCount(2);
  await expect(page.locator('.analysis-line').first()).toContainText('だってばよ!');
  await page.locator('[data-filter-band]').selectOption('intense');
  await expect(page.locator('.analysis-line')).toHaveCount(1);
  await page.getByLabel('Character for SPEAKER_00').fill('Kaito');
  await expect(page.getByRole('option', { name: /New character “Kaito”/ })).toBeVisible();
  await page.keyboard.press('Enter');
  await expect.poll(() => names?.names?.SPEAKER_00).toBe('Kaito');
  const clip = page.waitForRequest(r => r.url().includes('/api/analysis/clip'));
  await page.locator('.analysis-line').first().getByRole('button', { name: 'Voice' }).click();
  expect((await clip).url()).toContain('track=vocals');
});

test('unnamed voices show the closest named voice and the lines can be regrouped', async ({ page }) => {
  await show(page);
  let analysis = { ...ANALYSED, model: 'wespeaker-resnet34', names: { SPEAKER_00: 'Kaito' },
    cast: [{ name: 'Kaito', lines: 43, episodes: 3 }, { name: 'Mina', lines: 30, episodes: 3 }],
    suggestions: { SPEAKER_01: [{ name: 'Mina', similarity: 0.61, lines: 30, episodes: 3 },
      { name: 'Kaito', similarity: 0.42, lines: 43, episodes: 3 }] } };
  await page.route('**/api/analysis?*', route => route.fulfill({ json: analysis }));
  let names;
  await page.route('**/api/analysis/names', route => {
    names = route.request().postDataJSON().names;
    analysis = { ...analysis, names };
    return route.fulfill({ json: { names } });
  });
  await page.route('**/api/voice-models', route => route.fulfill({ json: { models: [
    { id: 'wespeaker-resnet34', name: 'WeSpeaker ResNet34', family: 'WeSpeaker', size_mb: 26, note: '', ready: true, scores: { recognise: 0.88, group: 0.76 } },
    { id: '3dspeaker-eres2netv2', name: 'ERes2NetV2', family: '3D-Speaker (Alibaba)', size_mb: 71, note: '', ready: false, scores: {} }] } }));
  let regroup;
  await page.route('**/api/analysis/regroup', route => {
    regroup = route.request().postDataJSON();
    analysis = { ...analysis, model: 'wespeaker-resnet34+3dspeaker-eres2netv2' };
    return route.fulfill({ json: { model: analysis.model, voices: 2, names: { SPEAKER_00: 'Kaito' } } });
  });
  await page.goto('/title/tvdb-81234/episode/2/analysis');
  await page.getByRole('button', { name: /closest to Mina/ }).click();
  await expect.poll(() => names?.SPEAKER_01).toBe('Mina');
  await expect(page.getByLabel('Character for SPEAKER_01')).toHaveValue('Mina');
  await page.locator('.analysis-models summary').click();
  await page.getByLabel(/ERes2NetV2/).check();
  await page.getByRole('button', { name: 'Regroup voices' }).click();
  await expect.poll(() => regroup?.models).toEqual(['wespeaker-resnet34', '3dspeaker-eres2netv2']);
  await expect(page.locator('[data-status]')).toContainText('2 voices found');
  await expect(page.locator('.analysis-models summary')).toContainText('3dspeaker-eres2netv2');
});

test('typing a name the cast already has picks it instead of making a twin', async ({ page }) => {
  await show(page);
  let names;
  await page.route('**/api/analysis?*', route => route.fulfill({ json: { ...ANALYSED,
    names: { SPEAKER_00: 'Kaito' }, cast: [{ name: 'Kaito', lines: 43, episodes: 3 }] } }));
  await page.route('**/api/analysis/names', route => {
    names = route.request().postDataJSON().names;
    return route.fulfill({ json: { names } });
  });
  await page.goto('/title/tvdb-81234/episode/2/analysis');
  const picker = page.getByLabel('Character for SPEAKER_01');
  await picker.fill('kaitto');
  await expect(page.getByRole('option').first()).toContainText('Kaito');
  await expect(page.getByRole('option').first()).toContainText('joins SPEAKER_00');
  await page.keyboard.press('Enter');
  await expect.poll(() => names?.SPEAKER_01).toBe('Kaito');
  await picker.fill('Somebody');
  await page.keyboard.press('Escape');
  await expect(picker).not.toHaveValue('Somebody');        // nothing typed is kept unless picked
});

test('watching a voice plays only its lines and can switch the audio language', async ({ page }) => {
  await show(page);
  await page.route('**/api/analysis?*', route => route.fulfill({ json: { ...ANALYSED, names: { SPEAKER_00: 'Kaito' } } }));
  await page.route('**/api/analysis/tracks?*', route => route.fulfill({ json: { default: 2, tracks: [
    { stream: 1, lang: 'en', title: '[Group] 2.0 ENG - FLAC' }, { stream: 2, lang: 'ja', title: '2.0 JPN - FLAC' },
    { stream: 5, lang: 'es', title: 'Latino' }] } }));
  const asked = [];
  await page.route('**/api/analysis/video?*', route => {
    asked.push(new URL(route.request().url()).searchParams.get('audio'));
    return route.fulfill({ status: 200, contentType: 'video/mp4', body: Buffer.alloc(16) });
  });
  await page.goto('/title/tvdb-81234/episode/2/analysis');
  await page.getByRole('button', { name: 'Watch Kaito' }).click();
  const player = page.getByRole('dialog');
  await expect(player.getByRole('heading', { name: 'Kaito' })).toBeVisible();
  await expect(player.locator('.mp-item')).toHaveCount(1);              // only Kaito's line
  await expect(player.locator('.mp-caption')).toHaveText('Believe it!');
  await expect.poll(() => asked[0]).toBe('2');                           // the original language first
  const language = player.getByLabel('Audio language');
  await expect(language.locator('option')).toHaveText(['English', 'Japanese', 'Spanish · Latino']);
  await language.selectOption({ label: 'Spanish · Latino' });
  await expect.poll(() => asked.includes('5')).toBe(true);
  await page.keyboard.press('Escape');
  await expect(player).toHaveCount(0);
});

test('a watched line can be given to another character from its menu', async ({ page }) => {
  await show(page);
  const lines = ANALYSED.lines.map((l, i) => ({ ...l, cue: `c${i}` }));
  await page.route('**/api/analysis?*', route => route.fulfill({ json: { ...ANALYSED, lines,
    names: { SPEAKER_00: 'Doran' }, cast: [{ name: 'Doran', lines: 30, episodes: 1 }, { name: 'Ryo', lines: 9, episodes: 1 }] } }));
  await page.route('**/api/analysis/tracks?*', route => route.fulfill({ json: { default: 2, tracks: [{ stream: 2, lang: 'ja', title: '' }] } }));
  await page.route('**/api/analysis/video?*', route => route.fulfill({ status: 200, contentType: 'video/mp4', body: Buffer.alloc(16) }));
  let moved;
  await page.route('**/api/analysis/line', route => {
    moved = route.request().postDataJSON();
    return route.fulfill({ json: { speaker: 'SPEAKER_02', character: moved.character, new_voice: true } });
  });
  await page.goto('/title/tvdb-81234/episode/2/analysis');
  await page.getByRole('button', { name: 'Watch Doran' }).click();
  const player = page.getByRole('dialog');
  await player.getByRole('button', { name: /More for 0:01/ }).click();
  await expect(player.getByText(/Who says “Believe it!”/)).toBeVisible();
  await expect(player.getByLabel('Who says this line')).toBeFocused();
  await page.keyboard.type('Harbor guard');
  await page.getByRole('option', { name: /New character “Harbor guard”/ }).click();
  await expect.poll(() => moved).toEqual({ path: '/shows/HarborLights/e02.mkv', cue: 'c0', character: 'Harbor guard' });
  await expect(player.locator('.mp-tag')).toHaveText('→ Harbor guard');
  await expect(player.locator('.mp-menu')).toHaveCount(0);
  await expect(player).toBeVisible();                                   // the reel keeps playing
});

test('a voice whose name the dialogue contradicts says so and can be renamed in one click', async ({ page }) => {
  await show(page);
  let names;
  await page.route('**/api/analysis?*', route => route.fulfill({ json: { ...ANALYSED,
    names: { SPEAKER_00: 'Kaito' }, cast: [{ name: 'Kaito', lines: 43, episodes: 3 }],
    dialogue: { SPEAKER_00: { answers: [{ name: 'Ren', count: 3, cues: ['c0'] }], calls: [{ name: 'Mina', count: 1 }], suggests: 'Ren' } } } }));
  await page.route('**/api/analysis/names', route => {
    names = route.request().postDataJSON().names;
    return route.fulfill({ json: { names } });
  });
  await page.goto('/title/tvdb-81234/episode/2/analysis');
  await expect(page.locator('.cast-clue').first()).toContainText('answers to “Ren” 3× · calls Mina');
  await expect(page.locator('.cast-clue-warn')).toContainText('Named Kaito, but the dialogue says this is Ren');
  await page.getByRole('button', { name: 'Name it Ren' }).click();
  await expect.poll(() => names?.SPEAKER_00).toBe('Ren');
});

test('the episode asks who says the doubtful lines, and an answer names the voice', async ({ page }) => {
  await show(page);
  let names;
  await page.route('**/api/analysis?*', route => route.fulfill({ json: { ...ANALYSED,
    names: {}, cast: [{ name: 'Kaito', lines: 43, episodes: 3 }],
    doubts: [{ kind: 'voice', voice: 'SPEAKER_00', lines: 1, line: ANALYSED.lines[0],
      hints: [{ name: 'Kaito', why: 'answers when Kaito is called (3×)' }] }] } }));
  await page.route('**/api/analysis/names', route => {
    names = route.request().postDataJSON().names;
    return route.fulfill({ json: { names } });
  });
  await page.goto('/title/tvdb-81234/episode/2/analysis');
  await expect(page.locator('.ask')).toContainText('Who is this voice?');
  await page.locator('.ask').getByRole('button', { name: 'Kaito' }).click();
  await expect.poll(() => names?.SPEAKER_00).toBe('Kaito');
});
