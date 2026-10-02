import { test, expect } from '@playwright/test';

// Media knowledge and adaptive audio in the existing pages: analysis evidence,
// title knowledge review, the template catalogue, character profiles and the
// envelope panel in review. Invented show and character names only.

async function show(page) {
  await page.route('**/api/library', route => route.fulfill({ json: { items: [{
    title: 'Harbor Lights', tvdb_id: 81234, media_type: 'show', source: 'Plex · TV Shows',
    original: '??', path: '/shows/HarborLights', audio_langs: ['en', 'ja'], label: 'available',
  }], target_languages: ['en', 'es'], counts: {} } }));
  await page.route('**/api/series/81234/episodes?*', route => route.fulfill({ json: {
    title: 'Harbor Lights', total: 1, downloaded: 1, dubbed: 0, episodes: [
      { id: 2, season: 1, episode: 2, title: 'The Storm', downloaded: true,
        path: '/shows/HarborLights/e02.mkv', audio_langs: ['en', 'ja'], status: 'needs-dub', dubbed: false }] } }));
  await page.route('**/api/voices', route => route.fulfill({ json: { voices: [] } }));
}

const ANALYSED = {
  analysed: true, names: { SPEAKER_00: 'Kaito' }, names_from: 'legacy', total_seconds: 10, measured: true,
  job: null, identity: { series_id: 'show:tvdb:81234', revision_id: 'rev-c1' }, script_match: 'exact',
  languages: { text: 'en', original: 'ja', original_text: false }, cast: [{ name: 'Kaito', lines: 3, episodes: 1 }],
  speakers: [{ speaker: 'Kaito', share: 0.6 }, { speaker: 'SPEAKER_01', share: 0.4 }],
  track_evidence: [{ stream: 2, lang: 'es', title: 'Latino', state: 'verified', offset: 0.02 },
    { stream: 3, lang: 'en', title: 'Commentary', state: 'excluded', reason: 'its title says commentary' }],
  coverage: [
    { stage: 'transcribe', state: 'done', group: 'audio', reason: '' },
    { stage: 'baselines', state: 'stale', group: 'audio', reason: 'diarize changed' },
    { stage: 'faces', state: 'unsupported', group: 'visual', reason: 'OpenCV is not installed' },
    { stage: 'knowledge', state: 'missing', group: 'knowledge', reason: '' }],
  rerunnable: ['baselines'],
  lines: [
    { index: 0, start: 1, end: 4, cue: 'c0', speaker: 'SPEAKER_00', character: 'Kaito', text: 'Wait for me!',
      relative_db: 6, band: 'intense', locked: true, why: { method: 'manual' }, features: { quality: 'ok' } },
    { index: 1, start: 5, end: 5.4, cue: 'c1', speaker: 'SPEAKER_01', character: '', text: 'Huh?',
      relative_db: null, band: 'unmeasured', locked: false,
      why: { method: 'inherited', candidates: [], margin: null },
      features: { quality: 'insufficient', reasons: ['only 0.20s of active speech'] } },
  ],
};

test('the analysis shows what ran, what is stale or unsupported, and why a line got its voice', async ({ page }) => {
  await show(page);
  let rerun, unlocked, moved;
  await page.route('**/api/analysis?*', route => route.fulfill({ json: ANALYSED }));
  await page.route('**/api/analysis/visual?*', route => route.fulfill({ json: { analysed: false,
    capability: { reasons: ['OpenCV is not installed'] } } }));
  await page.route('**/api/analysis/rerun', route => { rerun = route.request().postDataJSON(); return route.fulfill({ json: { job_id: 'r1' } }); });
  await page.route('**/api/analysis/line/unlock', route => { unlocked = route.request().postDataJSON(); return route.fulfill({ json: {} }); });
  await page.route('**/api/analysis/lines', route => { moved = route.request().postDataJSON(); return route.fulfill({ json: {} }); });
  await page.route('**/api/analysis/migration', route => route.fulfill({ json: { fingerprint: 'abc12345', counts: { ready: 1 },
    actions: [{ key: 'speaker-names:e02.mkv', kind: 'names', state: 'ready', reason: '' }] } }));
  await page.goto('/title/tvdb-81234/episode/2/analysis');
  const coverage = page.locator('.analysis-coverage');
  await expect(coverage).toContainText('Speaker baselines: needs a rerun');
  await expect(coverage).toContainText('Faces: not supported here');
  await page.getByRole('button', { name: 'Rerun 1 stage' }).click();
  await expect.poll(() => rerun?.stages).toEqual(['baselines']);
  await expect(page.locator('.analysis-line').nth(1)).toContainText('curve insufficient');
  await expect(page.locator('.analysis-line').nth(1).locator('[title*="took the previous speaker"]')).toHaveCount(2);
  await expect(page.getByText('Dub tracks last time')).toContainText('not used: its title says commentary');
  await page.locator('.analysis-lock').click();
  await expect.poll(() => unlocked?.cue).toBe('c0');
  await page.waitForTimeout(1600);                          // the rerun's reload redraws the page
  await page.waitForLoadState('networkidle');
  await page.getByRole('button', { name: 'Move older names onto this episode' }).click();
  await expect(page.locator('[data-migration]')).toContainText('Episode names');
  await page.getByLabel('Select line at 0:05.0').check();
  await page.getByLabel('Give the selected lines to').fill('Mina');
  await page.keyboard.press('Enter');
  await expect.poll(() => moved).toEqual({ path: '/shows/HarborLights/e02.mkv', cues: ['c1'], character: 'Mina' });
});

test('title knowledge is reviewed with its evidence and activated as a revision', async ({ page }) => {
  await show(page);
  let review, activated;
  await page.route('**/api/narrative?*', route => route.fulfill({ json: {
    series_id: 'show:tvdb:81234', revision: 0, claims: [], conflicted: [], retired: [], external: [],
    characters: { 'chr-1': 'Kaito', 'chr-2': 'Mina' },
    coverage: [{ media_id: 'ep:1', draft_id: 'd'.repeat(64), draft_revision: 1, state: 'complete', order: [1, 2],
      candidates: 1, needs_review: 1, stale: 0, conflicts: 0, active_claims: 0, model: 'ollama/model' }] } }));
  await page.route('**/api/narrative/draft/*', route => route.fulfill({ json: { draft_id: 'd'.repeat(64), revision: 1,
    state: 'complete', model: 'ollama/model', candidates: [{ candidate_id: 'c'.repeat(64), review_revision: 0,
      needs_review: true, stale: false, review: null,
      proposal: { kind: 'relationship', statement: "Mina is Kaito's sister.", subjects: ['character:chr-2', 'character:chr-1'],
        confidence: 0.7, uncertainties: ['she says big brother'], conflict_group: '' },
      evidence: [{ start_ms: 5000, text: 'Big brother, wait!' }] }] } }));
  await page.route('**/api/narrative/review', route => { review = route.request().postDataJSON(); return route.fulfill({ json: { review_revision: 1 } }); });
  await page.route('**/api/narrative/activate', route => { activated = route.request().postDataJSON();
    return route.fulfill({ json: { revision: 1, claims: 1, note: 'Jobs already queued keep the revision they froze.' } }); });
  await page.goto('/knowledge');
  await page.getByRole('button', { name: 'Title knowledge' }).click();
  await page.locator('[data-series]').selectOption('show:tvdb:81234');
  await page.getByRole('button', { name: 'Review', exact: true }).click();
  await expect(page.locator('.narrative-claim')).toContainText("Mina is Kaito's sister.");
  await expect(page.locator('.narrative-claim')).toContainText('Mina, Kaito');
  await page.locator('.narrative-claim').getByRole('button', { name: 'Correct' }).click();
  await page.locator('.narrative-correction').fill("Mina is Kaito's younger sister.");
  await page.locator('.narrative-claim').getByRole('button', { name: 'Correct' }).click();
  await expect.poll(() => review?.correction).toBe("Mina is Kaito's younger sister.");
  expect(review.decision).toBe('edit');
  await page.getByRole('button', { name: 'Activate reviewed knowledge' }).click();
  await expect.poll(() => activated?.base_revision).toBe(0);
});

test('the template catalogue lists built-ins, saves a new curve as data and previews it', async ({ page }) => {
  await page.goto('/knowledge');
  await page.getByRole('button', { name: 'Audio templates' }).click();
  await expect(page.locator('.templates-panel')).toContainText('Late emphasis');
  await expect(page.locator('.templates-panel')).toContainText('Preserve');
  await page.getByRole('button', { name: 'New template' }).click();
  const json = page.locator('[data-json]');
  const draft = JSON.parse(await json.inputValue());
  draft.id = 'voice/harbor-swell';
  draft.title = 'Harbor swell';
  await json.fill(JSON.stringify(draft));
  await page.getByRole('button', { name: 'Hear it on a test phrase' }).click();
  await expect(page.locator('[data-edit-status]')).toContainText('A test phrase, not a dubbed line');
  await page.getByRole('button', { name: 'Create' }).click();
  await expect(page.locator('.templates-panel')).toContainText('Harbor swell');
  await expect(page.locator('[data-status]')).toContainText('version 1');
});

test('a character profile saves only what changed and refuses a stale save', async ({ page, request }) => {
  const made = await (await request.post('/api/characters', { data: { series_id: 'show:tvdb:81234', name: 'Tomoe' } })).json();
  await page.goto(`/voices/character:${made.id}`);
  await expect(page.getByRole('heading', { name: 'Tomoe' })).toBeVisible();
  await page.getByText('Edit the description').click();
  await page.locator('[data-field="delivery.pace"]').selectOption('quick');
  await page.locator('[data-lock="delivery.pace"]').check();
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.locator('[data-status]')).toHaveText('Saved.');
  const saved = await (await request.get(`/api/characters/${made.id}/profile`)).json();
  expect(saved.profile.delivery.pace).toBe('quick');
  expect(saved.profile.meta.fields['delivery.pace'].locked).toBe(true);
  expect(saved.profile.vocal.brightness).toBe('unknown');
  // Someone else saves in the meantime: this tab's next save is refused.
  await request.patch(`/api/characters/${made.id}/profile`, { data: { base_revision: saved.profile.revision, set: { 'delivery.energy': 'high' } } });
  await page.locator('[data-field="vocal.brightness"]').selectOption('bright');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.locator('[data-status]')).toContainText('changed this profile in the meantime');
});

test('review shows the envelope decision, its real effect and changes it without new speech', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/api/library', route => route.fulfill({ json: { items: [], counts: {} } }));
  await page.route('**/api/jobs', route => route.fulfill({ json: {
    jobs: [{ id: 'env-1', title: 'Harbor Lights', status: 'done', source_lang: 'ja', target_lang: 'es',
      has_review: true, review_count: 1, progress: 100 }], counts: { done: 1 }, paused: false } }));
  await page.route('**/api/voices', route => route.fulfill({ json: { voices: [] } }));
  await page.route('**/api/jobs/env-1/review', route => route.fulfill({ json: { title: 'Harbor Lights', flagged: 1,
    editable: true, cue_schema: 5, revision: 'rev-1', segments: [{ index: 0, start: 1, end: 3, speaker: 'Kaito',
      text_src: 'Wait!', text_translated: '¡Espera!', has_audio: true, issues: ['review'],
      cue: { cue_id: 'cue-k', source: { spans: [] }, preparation: {}, audio: { takes: [], renders: [] } } }] } }));
  await page.route('**/api/adaptive/recommendations?*', route => route.fulfill({ json: { job_id: 'env-1', mode: 'apply',
    judge: 'retrieval', judge_is_model: false, states: { rule: 1 }, edits: {}, lines: [{ cue: 'cue-k', locked: false,
      envelope: { template: { id: 'voice/late-emphasis', version: 1 }, origin: 'retrieval', outcome: 'applied',
        requested: 1, applied: 0.6, preserved: 0.4, range_db: 3.2, peak: 0.71 },
      candidates: [{ template: { id: 'voice/late-emphasis', version: 1 }, title: 'Late emphasis', score: 0.72,
        support: ["the original actor's emphasis has this shape (0.81)"], conflicts: [] },
        { template: { id: 'voice/preserve', version: 1 }, title: 'Preserve', score: 0.41, support: [], conflicts: [] }],
      warnings: [] }] } }));
  await page.route('**/api/templates?*', route => route.fulfill({ json: { templates: [
    { id: 'voice/preserve', title: 'Preserve' }, { id: 'voice/late-emphasis', title: 'Late emphasis' },
    { id: 'voice/gradual-rise', title: 'Gradual rise' }] } }));
  let selected;
  await page.route('**/api/adaptive/select', route => { selected = route.request().postDataJSON();
    return route.fulfill({ json: { job: 'next', work: 'processing', speech: false,
      note: 'Reprocesses the existing take and remixes. No speech.' } }); });
  await page.goto('/dubs');
  await page.getByRole('button', { name: 'Review (1)' }).click();
  const panel = page.locator('.envelope-panel');
  await expect(panel).toContainText('retrieval (rule)');
  await expect(panel).toContainText('40% of the shape was already in the take');
  await expect(panel).toContainText('(a rule, not a model)');
  await expect(panel.getByRole('button', { name: 'With envelope, level-matched' })).toBeVisible();
  await panel.locator('[data-env-template]').selectOption('voice/gradual-rise');
  await panel.locator('[data-env-strength]').fill('0.8');
  await panel.getByRole('button', { name: 'Render this envelope' }).click();
  await expect.poll(() => selected).toEqual({ job_id: 'env-1', cue: 'cue-k', template: 'voice/gradual-rise', strength: 0.8 });
  await expect(panel).toContainText('No speech.');
  expect(errors).toEqual([]);
});
