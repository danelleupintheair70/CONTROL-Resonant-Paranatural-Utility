import { api } from './api.js';
import { escapeHtml as esc } from './dom.js';
import { library } from './state.js';

// A character's voice profile, edited a group at a time. Only the fields you
// change are saved, against the revision you loaded, so an older tab or form
// can never erase what it does not know. Locked fields are never changed by
// suggestions from analysis. Nothing here generates speech.

const LEVEL = ['unknown', 'low', 'medium', 'high'];
const GROUPS = [
  ['identity', 'Role', [
    ['identity.role', 'Role', ['unknown', 'lead', 'supporting', 'minor', 'narrator', 'crowd']],
    ['identity.notes', 'Notes', 'text']]],
  ['vocal', 'What the voice is like', [
    ['vocal.perceived_age', 'Sounds', ['unknown', 'child', 'teen', 'young', 'adult', 'older']],
    ['vocal.pitch_range.low', 'Pitch low (Hz)', 'number'], ['vocal.pitch_range.high', 'Pitch high (Hz)', 'number'],
    ['vocal.resonance', 'Resonance', LEVEL], ['vocal.brightness', 'Brightness', ['unknown', 'dark', 'neutral', 'bright']],
    ['vocal.breathiness', 'Breathiness', LEVEL], ['vocal.raspiness', 'Rasp', LEVEL], ['vocal.nasality', 'Nasality', LEVEL],
    ['vocal.articulation', 'Articulation', ['unknown', 'slurred', 'relaxed', 'clear', 'crisp']],
    ['vocal.character_gender', 'Character gender', 'text'],
    ['vocal.vocal_presentation', 'Voice reads as', ['unknown', 'masculine', 'feminine', 'androgynous', 'varies']],
    ['vocal.performer.name', 'Original performer', 'text'], ['vocal.performer.verified', 'Performer verified', 'check'],
    ['vocal.notes', 'Notes', 'text']]],
  ['locale', 'Language and accent', [
    ['locale.desired_locale', 'Dub locale', 'text'], ['locale.accent', 'Accent', 'text'],
    ['locale.languages', 'Languages (comma separated)', 'list']]],
  ['delivery', 'Default delivery', [
    ['delivery.pace', 'Pace', ['unknown', 'slow', 'measured', 'average', 'quick', 'rapid']],
    ['delivery.energy', 'Energy', LEVEL], ['delivery.expressiveness', 'Expressiveness', LEVEL],
    ['delivery.pauses', 'Pauses', ['unknown', 'few', 'some', 'many']],
    ['delivery.speech_register', 'Register', ['unknown', 'casual', 'neutral', 'formal', 'archaic', 'rough']],
    ['delivery.phrasing', 'Phrasing', 'text'], ['delivery.direction', 'Standing direction', 'text']]],
  ['pronunciation', 'Pronunciation and habits', [
    ['pronunciation.catchphrases', 'Catchphrases (comma separated)', 'list'],
    ['pronunciation.speech_register', 'Register notes', 'text'], ['pronunciation.honorifics', 'Honorifics', 'text']]],
  ['dynamics', 'Dynamics', [
    ['dynamics.desired.low', 'Quietest (dB vs. their ordinary)', 'number'],
    ['dynamics.desired.high', 'Loudest (dB vs. their ordinary)', 'number'],
    ['dynamics.max_boost_db', 'Never boost more than (dB)', 'number'], ['dynamics.max_cut_db', 'Never cut more than (dB)', 'number'],
    ['dynamics.envelope_strength', 'Envelope strength (0–1.5)', 'number'],
    ['dynamics.follow_source', 'Follow the original actor', ['unknown', 'follow', 'partly', 'ignore']]]],
];
const VARIATIONS = ['neutral', 'whisper', 'call', 'shout', 'restrained', 'excited', 'sad', 'exhausted', 'nonverbal'];
const VERDICTS = ['untested', 'good', 'acceptable', 'poor', 'failed'];

const get = (obj, path) => path.split('.').reduce((o, k) => (o == null ? o : o[k]), obj);

function control([path, label, kind], profile, locked) {
  const value = get(profile, path);
  const lock = `<label class="hint profile-lock" title="Locked fields are never changed by suggestions"><input type="checkbox" data-lock="${path}" ${locked(path) ? 'checked' : ''}> lock</label>`;
  let input;
  if (Array.isArray(kind)) {
    input = `<select class="input" data-field="${path}">${kind.map(o => `<option ${o === value ? 'selected' : ''}>${o}</option>`).join('')}</select>`;
  } else if (kind === 'check') {
    input = `<input type="checkbox" data-field="${path}" data-kind="check" ${value ? 'checked' : ''}>`;
  } else if (kind === 'number') {
    input = `<input class="input m" type="number" step="any" data-field="${path}" data-kind="number" value="${value ?? ''}">`;
  } else if (kind === 'list') {
    input = `<input class="input" data-field="${path}" data-kind="list" value="${esc((value || []).join(', '))}">`;
  } else {
    input = `<input class="input" data-field="${path}" value="${esc(value || '')}">`;
  }
  return `<label class="review-field">${label} ${input}${lock}</label>`;
}

function read(field) {
  const kind = field.dataset.kind;
  if (kind === 'check') return field.checked;
  if (kind === 'number') return field.value === '' ? null : Number(field.value);
  if (kind === 'list') return field.value.split(',').map(s => s.trim()).filter(Boolean);
  return field.value;
}

export async function renderCharacter(root, characterId, { goVoice }) {
  root.innerHTML = '<p class="hint">Loading the character…</p>';
  let data;
  try { data = await api(`characters/${encodeURIComponent(characterId)}/profile`); }
  catch (error) { root.innerHTML = `<p><a href="/voices" data-back>← All voices</a></p><p>${esc(error.message)}</p>`;
    root.querySelector('[data-back]').onclick = e => { e.preventDefault(); goVoice(''); }; return; }
  const { character, profile } = data;
  const fields = profile.meta?.fields || {};
  const locked = path => Boolean(fields[path]?.locked);
  const original = new Map();
  let catalog = [];
  let templates = [];
  try { catalog = (await api('voice-catalog')).voices || []; } catch { /* assignments show ids */ }
  try { templates = (await api('templates?kind=voice')).templates; } catch { /* preferences show ids */ }
  const show = (library.items || []).find(i => `show:tvdb:${i.tvdb_id}` === character.series_id
    || `movie:tmdb:${i.tmdb_id}` === character.series_id);
  document.title = `${character.name} — Voices — Doblarr`;
  root.innerHTML = `
    <p><a href="/voices" data-back>← All voices</a></p>
    <div class="voice-hero"><div class="voice-hero-body">
      <span class="card-kicker">Character${show ? ` · ${esc(show.title)}` : ''}</span>
      <h2>${esc(character.name)}</h2>
      <p class="hint">${character.aliases?.length ? `Also called ${character.aliases.map(esc).join(', ')}. ` : ''}Profile revision ${profile.revision}.
        References: ${data.references.approved} approved${data.references.neutral ? '' : ', no neutral one yet'}${data.references.expressive ? '' : ', no expressive one yet'}.</p>
    </div></div>
    <p class="hint" role="status" data-status></p>
    ${GROUPS.map(([key, title, list]) => `<section class="panel voice-panel"><h3>${title}</h3>
      <div class="voice-form">${list.map(spec => control(spec, profile, locked)).join('')}</div></section>`).join('')}
    <section class="panel voice-panel"><h3>Performance range</h3>
      <p class="hint">What you want, what the assigned engine can be asked for, and what an audition proved, kept apart.</p>
      <table class="table"><thead><tr><th>State</th><th>Wanted</th><th>Engine can be asked</th><th>Auditioned</th></tr></thead><tbody>
      ${VARIATIONS.map(v => {
        const row = profile.variations[v] || {};
        const support = (data.assignments[0]?.variations || {})[v] || 'unknown';
        return `<tr><td>${v}</td>
          <td><select class="input" data-field="variations.${v}.desired" data-kind="tri">${['', 'yes', 'no'].map(o => `<option value="${o}" ${(row.desired === true && o === 'yes') || (row.desired === false && o === 'no') || (row.desired == null && o === '') ? 'selected' : ''}>${o || 'unknown'}</option>`).join('')}</select></td>
          <td class="m">${esc(support)}</td>
          <td><select class="input" data-field="variations.${v}.auditioned">${VERDICTS.map(o => `<option ${o === row.auditioned ? 'selected' : ''}>${o}</option>`).join('')}</select></td></tr>`;
      }).join('')}</tbody></table></section>
    <section class="panel voice-panel"><h3>Templates</h3>
      <p class="hint">Envelope templates this character tends to suit, or should avoid. Recommendations weigh them; they never force one.</p>
      <div class="voice-form">
        <label class="review-field">Favoured<select class="input" multiple size="5" data-templates="favored">${templates.map(t => `<option value="${esc(t.id)}" ${(profile.templates.favored || []).some(p => p.template === t.id) ? 'selected' : ''}>${esc(t.title)}</option>`).join('')}</select></label>
        <label class="review-field">Avoid<select class="input" multiple size="5" data-templates="discouraged">${templates.map(t => `<option value="${esc(t.id)}" ${(profile.templates.discouraged || []).some(p => p.template === t.id) ? 'selected' : ''}>${esc(t.title)}</option>`).join('')}</select></label>
      </div></section>
    <div class="studio-actions"><button type="button" class="btn btn-primary" data-save>Save changes</button>
      <span class="hint">Only what you changed is saved. Saving never generates speech.</span></div>
    <section class="panel voice-panel"><h3>Suggestions from analysis</h3><div data-proposals><p class="hint">Reading analysed lines…</p></div></section>
    <section class="panel voice-panel"><h3>References</h3>
      ${profile.references.length ? `<table class="table"><thead><tr><th>Kind</th><th>Line</th><th>Quality</th><th>State</th><th></th></tr></thead><tbody>
        ${profile.references.map(r => `<tr><td>${esc(r.kind)} · ${esc(r.variation)}</td>
          <td>${esc(r.transcript || '')}<br><span class="hint m">${r.source.start.toFixed(1)}–${r.source.end.toFixed(1)} s · ${esc(r.provenance || '')}</span></td>
          <td class="hint">${r.quality.duration ? `${r.quality.duration} s` : ''}${r.quality.relative_db != null ? ` · ${r.quality.relative_db > 0 ? '+' : ''}${r.quality.relative_db} dB` : ''}</td>
          <td>${r.retired ? 'retired' : r.approved ? 'approved' : 'not approved'}</td>
          <td>${r.retired ? '' : `<button type="button" class="btn btn-ghost" data-ref="${esc(r.id)}" data-approve="${r.approved ? 'false' : 'true'}">${r.approved ? 'Unapprove' : 'Approve'}</button>
            <button type="button" class="btn btn-ghost" data-ref="${esc(r.id)}" data-retire="true">Retire</button>`}</td></tr>`).join('')}
      </tbody></table>` : '<p class="hint">No references yet. Approve suggested lines above, or pick lines on an episode’s Analysis tab.</p>'}
    </section>
    <section class="panel voice-panel"><h3>Voice assignments</h3>
      <p class="hint">Which voice speaks for this character in each language. One voice can serve several characters.</p>
      ${data.assignments.length ? `<table class="table"><thead><tr><th>Locale</th><th>Variant</th><th>Voice</th><th>Engine can do</th><th></th></tr></thead><tbody>
        ${data.assignments.map(a => `<tr><td class="m">${esc(a.locale || 'any')}</td><td>${esc(a.variant || 'any')}</td>
          <td>${esc(catalog.find(v => v.profile_id === a.voice || v.key === a.voice)?.display_name || catalog.find(v => v.profile_id === a.voice)?.name || a.voice)}</td>
          <td class="hint">${esc((a.capabilities?.supported_controls || []).join(', ') || 'unknown')}${a.capabilities?.unsupported?.length ? `; cannot: ${esc(a.capabilities.unsupported.join(', '))}` : ''}</td>
          <td><button type="button" class="btn btn-ghost" data-unassign="${esc(a.locale || '')}" data-variant="${esc(a.variant || '')}">Remove</button></td></tr>`).join('')}
      </tbody></table>` : '<p class="hint">No voice assigned yet.</p>'}
      <div class="voice-form">
        <label class="review-field">Voice<select class="input" data-assign-voice><option value="">Choose a voice</option>
          ${catalog.map(v => `<option value="${esc(v.profile_id || '')}" data-engine="${esc(v.engine || '')}" ${v.profile_id ? '' : 'disabled'}>${esc(v.display_name || v.name)} · ${esc(v.engine || '')}</option>`).join('')}</select></label>
        <label class="review-field">Locale<input class="input m" data-assign-locale placeholder="any, or es-MX"></label>
        <label class="review-field">Variant<select class="input" data-assign-variant><option value="">any</option>
          ${(character.variants || []).map(v => `<option value="${esc(v.id)}">${esc(v.label)}</option>`).join('')}</select></label>
        <button type="button" class="btn btn-secondary" data-assign>Assign</button>
      </div></section>
    <section class="panel voice-panel"><h3>Auditions</h3>
      ${profile.auditions.length ? profile.auditions.map(a => `<p class="hint">${esc(a.at)} · ${esc(a.language)} · ${esc(a.verdict)} · ${esc(a.context || '')}</p>`).join('')
        : '<p class="hint">No verdicts recorded. Studio auditions record them here.</p>'}</section>`;
  const say = msg => { root.querySelector('[data-status]').textContent = msg; };
  root.querySelector('[data-back]').onclick = e => { e.preventDefault(); goVoice(''); };
  root.querySelectorAll('[data-field]').forEach(f => original.set(f.dataset.field, JSON.stringify(f.dataset.kind === 'tri' ? f.value : read(f))));
  root.querySelector('[data-save]').onclick = async () => {
    const set = {};
    root.querySelectorAll('[data-field]').forEach(f => {
      const value = f.dataset.kind === 'tri' ? f.value : read(f);
      if (JSON.stringify(value) === original.get(f.dataset.field)) return;
      set[f.dataset.field] = f.dataset.kind === 'tri' ? (value === '' ? null : value === 'yes') : value;
    });
    ['favored', 'discouraged'].forEach(kind => {
      const box = root.querySelector(`[data-templates="${kind}"]`);
      const picked = [...box.selectedOptions].map(o => o.value);
      const before = (profile.templates[kind] || []).map(p => p.template);
      if (JSON.stringify(picked) !== JSON.stringify(before)) {
        set[`templates.${kind}`] = picked.map(id => (profile.templates[kind] || []).find(p => p.template === id) || { template: id });
      }
    });
    const lock = [], unlock = [];
    root.querySelectorAll('[data-lock]').forEach(b => {
      if (b.checked && !locked(b.dataset.lock)) lock.push(b.dataset.lock);
      if (!b.checked && locked(b.dataset.lock)) unlock.push(b.dataset.lock);
    });
    if (!Object.keys(set).length && !lock.length && !unlock.length) { say('Nothing changed.'); return; }
    try {
      await api(`characters/${encodeURIComponent(characterId)}/profile`, { method: 'PATCH',
        json: { base_revision: profile.revision, set, lock, unlock } });
      await renderCharacter(root, characterId, { goVoice });
      say('Saved.');
    } catch (error) {
      say(error.status === 409 ? 'Someone changed this profile in the meantime. Reload it and apply your change again.' : error.message);
    }
  };
  root.querySelectorAll('[data-ref]').forEach(b => b.onclick = async () => {
    try {
      await api(`characters/${encodeURIComponent(characterId)}/references/${encodeURIComponent(b.dataset.ref)}`, {
        method: 'PATCH', json: { base_revision: profile.revision,
          ...(b.dataset.retire ? { retired: true } : { approved: b.dataset.approve === 'true' }) } });
      await renderCharacter(root, characterId, { goVoice });
    } catch (error) { say(error.message); }
  });
  const assign = async body => {
    try {
      await api(`characters/${encodeURIComponent(characterId)}/assignments`, { method: 'PUT', json: body });
      await renderCharacter(root, characterId, { goVoice });
      say('Assignment saved. Lines already rendered keep their voice until you re-render them.');
    } catch (error) { say(error.message); }
  };
  root.querySelector('[data-assign]').onclick = () => {
    const voice = root.querySelector('[data-assign-voice]');
    if (!voice.value) { say('Choose a voice first.'); return; }
    assign({ voice: voice.value, engine: voice.selectedOptions[0].dataset.engine || '',
      locale: root.querySelector('[data-assign-locale]').value.trim(),
      variant: root.querySelector('[data-assign-variant]').value });
  };
  root.querySelectorAll('[data-unassign]').forEach(b => b.onclick = () =>
    assign({ clear: true, locale: b.dataset.unassign, variant: b.dataset.variant }));
  loadProposals(root.querySelector('[data-proposals]'), characterId, profile.revision, () => renderCharacter(root, characterId, { goVoice }));
}

async function loadProposals(box, characterId, revision, refresh) {
  let data;
  try { data = await api(`characters/${encodeURIComponent(characterId)}/proposals`); }
  catch (error) { box.innerHTML = `<p class="hint">${esc(error.message)}</p>`; return; }
  if (!data.proposals.length) {
    box.innerHTML = `<p class="hint">${data.lines ? `${data.lines} analysed lines, nothing confident enough to suggest.` : 'No analysed lines are identified as this character yet.'}</p>`;
    return;
  }
  box.innerHTML = `<p class="hint">From ${data.lines} analysed lines. Tick what you agree with and approve them together.</p>
    ${data.proposals.map(p => `<label class="profile-proposal"><input type="checkbox" data-proposal="${esc(p.id)}" ${p.locked ? 'disabled' : ''}>
      <span><strong>${esc(p.kind === 'reference' ? `Reference: ${p.value.kind}, ${p.value.variation}` : p.field)}</strong>
      ${p.kind === 'reference' ? `“${esc(p.value.transcript)}”` : esc(JSON.stringify(p.value))}
      <span class="hint">${esc(p.evidence)}${p.locked ? ' · locked, will not change' : ''}</span></span></label>`).join('')}
    <button type="button" class="btn btn-secondary" data-approve-all>Approve selected</button>
    <p class="hint" role="status" data-proposal-status></p>`;
  box.querySelector('[data-approve-all]').onclick = async () => {
    const ids = [...box.querySelectorAll('[data-proposal]:checked')].map(i => i.dataset.proposal);
    if (!ids.length) return;
    try {
      await api(`characters/${encodeURIComponent(characterId)}/proposals/approve`, { method: 'POST',
        json: { base_revision: revision, ids } });
      await refresh();
    } catch (error) { box.querySelector('[data-proposal-status]').textContent = error.message; }
  };
}

export async function renderCharacterList(root, { goVoice, seriesId, onSeries }) {
  const shows = (library.items || []).filter(i => (i.media_type === 'show' && i.tvdb_id) || (i.media_type === 'movie' && i.tmdb_id))
    .map(i => ({ id: i.media_type === 'show' ? `show:tvdb:${i.tvdb_id}` : `movie:tmdb:${i.tmdb_id}`, label: i.title }))
    .sort((a, b) => a.label.localeCompare(b.label));
  const box = document.createElement('div');
  box.className = 'panel voice-panel';
  box.innerHTML = `<label class="review-field">Show or film<select class="input" data-pick-series><option value="">Choose one</option>
    ${shows.map(s => `<option value="${esc(s.id)}" ${s.id === seriesId ? 'selected' : ''}>${esc(s.label)}</option>`).join('')}</select></label>
    <div data-character-list></div>`;
  root.append(box);
  box.querySelector('[data-pick-series]').onchange = e => onSeries(e.target.value);
  const list = box.querySelector('[data-character-list]');
  if (!seriesId) { list.innerHTML = '<p class="hint">Characters are kept per show. Name voices on an episode’s Analysis tab and they appear here.</p>'; return; }
  try {
    const data = await api(`characters?series_id=${encodeURIComponent(seriesId)}`);
    list.innerHTML = data.characters.length ? `<table class="table"><thead><tr><th>Character</th><th>References</th><th>Voices</th></tr></thead><tbody>
      ${data.characters.map(c => `<tr data-character="${esc(c.id)}" tabindex="0"><td><strong>${esc(c.name)}</strong>${c.aliases?.length ? ` <span class="hint">${c.aliases.map(esc).join(', ')}</span>` : ''}</td>
        <td class="hint">${c.references.approved} approved</td><td class="m">${c.assignments}</td></tr>`).join('')}</tbody></table>`
      : '<p class="hint">No characters for this show yet.</p>';
    list.querySelectorAll('[data-character]').forEach(row => {
      row.onclick = () => goVoice(`character:${row.dataset.character}`);
      row.onkeydown = e => { if (e.key === 'Enter') goVoice(`character:${row.dataset.character}`); };
    });
  } catch (error) { list.innerHTML = `<p class="hint">${esc(error.message)}</p>`; }
}
