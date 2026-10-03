import { api, apiUrl } from './api.js';
import { escapeHtml as esc, safeGet } from './dom.js';
import { characterPicker } from './character-picker.js';

// What the episode analysis knows beyond its lines: which stages ran and which
// are stale, failed or not supported here; older names waiting to be moved
// onto this episode's identity; title knowledge extraction; and the optional
// visual evidence (faces on screen, who appears to speak). None of it
// translates, clones or generates speech.

const STATE = { done: 'done', stale: 'needs a rerun', failed: 'failed', unsupported: 'not supported here',
  skipped: 'off', missing: 'not run', running: 'running' };
const STAGE = { probe: 'Read the file', separate: 'Separate dialogue', transcribe: 'Lines', diarize: 'Group voices',
  measure: 'Levels', baselines: 'Speaker baselines', analyze: 'Pitch and words', features: 'Energy curves',
  speaker_memory: 'Teach the show', emotion: 'How lines are said', dub_text: 'Official dub wording', shots: 'Shots', faces: 'Faces', tracks: 'Face tracks',
  active_speaker: 'Mouth movement', association: 'Who speaks (visual)', scenes: 'Scenes', knowledge: 'Title knowledge' };
const SCREEN = { 'onscreen-speaking': 'speaking on screen', 'onscreen-silent': 'face on screen, not speaking',
  offscreen: 'nobody on screen', unknown: 'not analysed' };
const METHOD = { clustered: 'heard and grouped', merged_small: 'a small group folded into a larger voice',
  nearest: 'too short to group; joined the closest voice', inherited: 'no usable voice; took the previous speaker',
  manual: 'assigned by hand' };

export function whyText(why) {
  if (!why) return '';
  const parts = [METHOD[why.method] || why.method];
  if (why.margin != null) parts.push(`margin ${why.margin.toFixed(2)} over the next voice`);
  if (why.candidates?.length > 1) parts.push(`also close: ${why.candidates.slice(1).map(c => `${c.label} ${c.similarity.toFixed(2)}`).join(', ')}`);
  return parts.join(' · ');
}

export const weak = why => why && ['merged_small', 'nearest', 'inherited'].includes(why.method)
  || (why?.method === 'clustered' && why.margin != null && why.margin < 0.05);

function thumbUrl(path, name) {
  const key = safeGet('doblarr_api_key', '');
  return apiUrl(`analysis/visual/thumb?path=${encodeURIComponent(path)}&name=${encodeURIComponent(name)}`)
    + (key ? `&api_key=${encodeURIComponent(key)}` : '');
}

export function mountEvidence(box, data, { path, target, reload, say, visual = null }) {
  const top = box.querySelector('[data-evidence-top]');
  const coverage = data.coverage || [];
  const rerunnable = data.rerunnable || [];
  const groups = [['audio', 'Audio'], ['visual', 'Picture'], ['emotion', 'Emotion'], ['knowledge', 'Knowledge']];
  top.innerHTML = `<details class="analysis-coverage" ${rerunnable.length || data.names_from === 'legacy' ? 'open' : ''}>
    <summary>What has been analysed <span class="hint">${coverage.filter(c => c.state === 'done').length} of ${coverage.length} stages done${rerunnable.length ? ` · ${rerunnable.length} to rerun` : ''}</span></summary>
    ${data.identity ? '' : '<p class="hint">This file cannot be read from here, so it cannot be identified by its content. Names are read the older way, by file name, until it is reachable.</p>'}
    ${['name', 'ambiguous'].includes(data.script_match) ? `<p class="hint">This analysis was found by file name only${data.script_match === 'ambiguous' ? ', and other files share that name' : ''}. Analyse this file again to tie it to its content.</p>` : ''}
    ${groups.map(([group, label]) => `<div class="analysis-stage-group"><strong>${label}</strong>
      ${coverage.filter(c => c.group === group).map(c => `<span class="analysis-stage analysis-stage-${c.state}" title="${esc(c.reason || '')}">${esc(STAGE[c.stage] || c.stage)}: ${esc(STATE[c.state] || c.state)}</span>`).join('')}</div>`).join('')}
    <div class="studio-actions">
      ${rerunnable.length ? `<button type="button" class="btn btn-secondary" data-rerun>Rerun ${rerunnable.length} stage${rerunnable.length === 1 ? '' : 's'}</button>` : ''}
      <button type="button" class="btn btn-ghost" data-visual-run>Analyse the picture</button>
      <button type="button" class="btn btn-ghost" data-emotion-run>Read the emotions</button>
      <button type="button" class="btn btn-ghost" data-knowledge-run>Extract title knowledge</button>
      ${data.names_from === 'legacy' ? '<button type="button" class="btn btn-ghost" data-migrate>Move older names onto this episode</button>' : ''}
    </div>
    <p class="hint">Picture analysis and knowledge extraction are optional. Knowledge extraction asks a language model to read the lines; nothing it proposes is used until you review it under Knowledge.</p>
    <div data-migration></div></details>`;
  const queue = async (body, message) => {
    try {
      await api('analysis/rerun', { method: 'POST', json: { path, target_lang: target, ...body } });
      say(message);
      setTimeout(reload, 1500);
    } catch (error) { say(error.message); }
  };
  top.querySelector('[data-rerun]')?.addEventListener('click', () =>
    queue({ stages: rerunnable }, `Rerunning ${rerunnable.join(', ')}. Earlier stages are reused.`));
  top.querySelector('[data-visual-run]').onclick = () => queue({ stages: ['shots', 'faces', 'tracks', 'active_speaker', 'association', 'scenes'], visual: true },
    'Analysing the picture. Faces are evidence for you to check, never names on their own.');
  top.querySelector('[data-emotion-run]').onclick = () => queue({ stages: ['emotion'] },
    'Reading how each line is said: a still of every line with its words, and the voice. Takes about half a minute per minute of dialogue.');
  top.querySelector('[data-knowledge-run]').onclick = async () => {
    try {
      const result = await api('narrative/extract', { method: 'POST', json: { path, target_lang: target } });
      say(`Extracting with ${result.model}. Review the proposals under Knowledge → Title knowledge.`);
    } catch (error) { say(error.message); }
  };
  top.querySelector('[data-migrate]')?.addEventListener('click', () => migration(top.querySelector('[data-migration]'), reload, say));
  loadVisual(box.querySelector('[data-visual]'), data, { path, reload, say, visual });
}

async function migration(box, reload, say) {
  box.innerHTML = '<p class="hint">Checking older names…</p>';
  let plan;
  try { plan = await api('analysis/migration'); } catch (error) { box.innerHTML = `<p class="hint">${esc(error.message)}</p>`; return; }
  const kind = { names: 'Episode names', prints: 'Show voice memory', traits: 'Voice identity', cast: 'Title cast',
    series_link: 'Same show?' };
  const actionable = plan.actions.filter(a => ['ready', 'confirm'].includes(a.state));
  box.innerHTML = `<p class="hint">Nothing changes until you apply. Ambiguous items stay as they are.</p>
    <table class="table"><thead><tr><th></th><th>What</th><th>State</th><th>Why</th></tr></thead><tbody>
    ${plan.actions.map(a => `<tr><td>${['ready', 'confirm'].includes(a.state) ? `<input type="checkbox" data-key="${esc(a.key)}" ${a.state === 'ready' ? 'checked' : ''}>` : ''}</td>
      <td>${esc(kind[a.kind] || a.kind)} <span class="hint">${esc(a.key.split(':').slice(1).join(':').slice(0, 60))}</span></td>
      <td>${esc(a.state)}</td><td class="hint">${esc(a.reason || '')}</td></tr>`).join('')}</tbody></table>
    <button type="button" class="btn btn-secondary" data-apply ${actionable.length ? '' : 'disabled'}>Apply selected</button>`;
  box.querySelector('[data-apply]').onclick = async () => {
    const keys = [...box.querySelectorAll('[data-key]:checked')].map(i => i.dataset.key);
    try {
      const result = await api('analysis/migration', { method: 'POST', json: { fingerprint: plan.fingerprint, keys } });
      say(`Moved ${result.applied.length} item${result.applied.length === 1 ? '' : 's'}.`);
      reload();
    } catch (error) { say(error.message); }
  };
}

async function loadVisual(box, data, { path, reload, say, visual = null }) {
  if (!box) return;
  if (!visual) {
    try { visual = await api(`analysis/visual?path=${encodeURIComponent(path)}`); } catch { box.innerHTML = ''; return; }
  }
  if (!visual.analysed) {
    const why = visual.capability?.reasons?.length ? ` Not available here: ${visual.capability.reasons.join('; ')}.` : '';
    box.innerHTML = `<p class="hint">The picture has not been analysed.${esc(why)}</p>`;
    return;
  }
  const byCue = Object.fromEntries((visual.associations || []).map(a => [a.cue, a]));
  document.querySelectorAll('[data-screen-cue]').forEach(slot => {
    const row = byCue[slot.dataset.screenCue];
    if (!row) return;
    slot.textContent = SCREEN[row.screen] || row.screen;
    if (row.decision?.state === 'proposal') slot.textContent += ` · picture suggests ${row.decision.name || 'another character'}`;
    if (row.conflicts?.length) slot.textContent += ' · voice and face disagree';
  });
  // Named and proposed faces first, then the longest appearances: a person
  // names the faces that matter, not every passing glimpse.
  const rank = t => (t.assigned ? 0 : t.matches?.some(m => m.proposed) ? 1 : 2);
  const ordered = (visual.tracks || []).filter(t => t.frames >= 2)
    .sort((a, b) => rank(a) - rank(b) || b.frames - a.frames);
  const shown = box.dataset.allFaces ? ordered : ordered.slice(0, 24);
  const tracks = shown.sort((a, b) => rank(a) - rank(b) || a.start - b.start);
  const cast = data.cast || [];
  box.innerHTML = `<details class="analysis-visual">
    <summary>Faces on screen <span class="hint">${visual.tracks.length} face tracks · ${visual.shots} shots · ${visual.scenes.length} scenes · ${esc((visual.backend?.detectors || []).join(', '))}</span></summary>
    <p class="hint">A face track is the same face across a few frames. Naming one keeps it as a reference for this show; the picture never names a line by itself, and an off-screen voice is normal.</p>
    <div class="analysis-faces">${tracks.map(t => `<figure class="analysis-face" data-track="${esc(t.id)}">
      ${t.thumbnail ? `<img src="${thumbUrl(path, t.thumbnail)}" alt="Face at ${t.start.toFixed(1)} s" width="72" height="72">` : ''}
      <figcaption><span class="m">${t.start.toFixed(1)}–${t.end.toFixed(1)} s</span>
        <span>${esc(t.character_name || (t.assigned ? 'unknown (by hand)' : ''))}</span>
        ${!t.assigned && t.matches?.find(m => m.proposed) ? `<span class="hint">looks like ${esc(t.matches.find(m => m.proposed).name)} (${t.matches.find(m => m.proposed).similarity.toFixed(2)})</span>` : ''}
        <span data-face-picker="${esc(t.id)}"></span>
        <button type="button" class="btn btn-ghost" data-unknown="${esc(t.id)}">Not a character</button></figcaption></figure>`).join('')}</div>
    ${ordered.length > tracks.length ? `<button type="button" class="btn btn-ghost" data-all-faces>Show all ${ordered.length} faces</button>` : ''}
  </details>`;
  const assign = async (track, name) => {
    try {
      await api('analysis/visual/tracks', { method: 'POST', json: { path, assign: { [track]: name } } });
      say(name ? `That face is ${name} now, and a reference for the show.` : 'Marked as not a character.');
      reload();
    } catch (error) { say(error.message); }
  };
  box.querySelectorAll('[data-face-picker]').forEach(slot => slot.replaceWith(characterPicker({
    label: 'Who is this', value: '', placeholder: 'Name this face', cast, suggestions: [],
    onPick: name => name && assign(slot.dataset.facePicker, name) })));
  box.querySelectorAll('[data-unknown]').forEach(b => b.onclick = () => assign(b.dataset.unknown, ''));
  box.querySelector('[data-all-faces]')?.addEventListener('click', () => {
    box.dataset.allFaces = '1';
    loadVisual(box, data, { path, reload, say, visual }).then(() => { box.querySelector('details').open = true; });
  });
}

export function mountSelection(box, data, { path, reload, say }) {
  const bar = box.querySelector('[data-selection]');
  if (!bar) return;
  const update = () => {
    const picked = [...box.querySelectorAll('[data-select-line]:checked')].map(i => i.dataset.selectLine);
    bar.hidden = !picked.length;
    bar.querySelector('[data-count]').textContent = `${picked.length} line${picked.length === 1 ? '' : 's'} selected`;
    return picked;
  };
  box.querySelectorAll('[data-select-line]').forEach(i => i.onchange = update);
  const slot = bar.querySelector('[data-selection-picker]');
  slot.replaceWith(characterPicker({
    label: 'Give the selected lines to', value: '', placeholder: 'Pick or type a name', cast: data.cast || [],
    suggestions: [], onPick: async name => {
      const cues = update();
      if (!cues.length || !name) return;
      try {
        await api('analysis/lines', { method: 'PUT', json: { path, cues, character: name } });
        say(`${cues.length} line${cues.length === 1 ? '' : 's'} given to ${name}; speaker baselines were recomputed.`);
        reload();
      } catch (error) { say(error.message); }
    } }));
  box.querySelectorAll('[data-unlock]').forEach(b => b.onclick = async () => {
    try {
      await api('analysis/line/unlock', { method: 'POST', json: { path, cue: b.dataset.unlock } });
      say('The grouping decides this line again at the next regroup.');
      reload();
    } catch (error) { say(error.message); }
  });
}
