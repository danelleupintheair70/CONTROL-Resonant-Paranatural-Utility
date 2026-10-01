import { api } from './api.js';
import { escapeHtml as esc } from './dom.js';
import { library } from './state.js';
import { openMediaPlayer } from './media-player.js';
import { frameUrl, pickFrames, trackLabel, videoUrl } from './episode-analysis.js';
import { hearPanel, mountHear, voiceFor } from './voice-common.js';
import { colourField, colourValue, mountColour, mountOrb, usedPanel } from './voices.js';

// One character of a show: the single page for who they are and how they
// sound. It carries the voice they speak with (hear it, change it, shape it),
// where they talk in the analysed episodes (stills and their lines), and
// the description a dub reads (pitch, pace, register…), shown as what is
// known and edited a group at a time. Only the fields you change are saved,
// against the revision you loaded, so an older tab can never erase what it
// does not know; locked fields are never changed by suggestions. Nothing
// here generates speech except "Hear it".

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
const clock = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

const get = (obj, path) => path.split('.').reduce((o, k) => (o == null ? o : o[k]), obj);
const known = value => !(value == null || value === '' || value === 'unknown' || value === false
  || (Array.isArray(value) && !value.length));

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

// What is known about the voice, as short facts ("Pace: quick"), group by group.
function described(profile, locked) {
  return GROUPS.map(([, title, list]) => {
    const facts = list.map(([path, label]) => [path, label, get(profile, path)]).filter(([, , v]) => known(v));
    return facts.length ? `<div class="profile-facts"><span class="hint">${title}</span>${facts.map(([path, label, v]) =>
      `<span class="profile-fact${locked(path) ? ' profile-fact-locked' : ''}" title="${locked(path) ? 'Locked: suggestions never change it' : ''}">${esc(label)}: <strong>${esc(Array.isArray(v) ? v.join(', ') : v === true ? 'yes' : String(v))}</strong></span>`).join('')}</div>` : '';
  }).join('');
}

const showOf = seriesId => (library.items || []).find(i => `show:tvdb:${i.tvdb_id}` === seriesId
  || `movie:tmdb:${i.tmdb_id}` === seriesId);

export async function renderCharacter(root, characterId, { goVoice, invalidate = () => {}, editing = false }) {
  root.innerHTML = '<p class="hint">Loading the character…</p>';
  const back = () => {
    root.querySelector('[data-back]').onclick = e => { e.preventDefault(); goVoice(''); };
  };
  let data;
  try { data = await api(`characters/${encodeURIComponent(characterId)}/profile`); }
  catch (error) { root.innerHTML = `<p><a href="/voices" data-back>← All voices</a></p><p>${esc(error.message)}</p>`; back(); return; }
  const { character, profile } = data;
  const fields = profile.meta?.fields || {};
  const locked = path => Boolean(fields[path]?.locked);
  const original = new Map();
  let catalog = [];
  let templates = [];
  try { catalog = (await api('voice-catalog')).voices || []; } catch { /* assignments show ids */ }
  try { templates = (await api('templates?kind=voice')).templates; } catch { /* preferences show ids */ }
  const cast = data.assignments.map(a => a.voice).filter(Boolean);
  const voice = voiceFor({ ...character, voices: cast }, catalog);
  const firm = Boolean(voice && cast.includes(voice.profile_id));
  let used = [];
  if (voice) { try { used = (await api(`voice-catalog/voice?key=${encodeURIComponent(voice.key)}`)).used_in; } catch { /* none */ } }
  const show = showOf(character.series_id);
  const facts = described(profile, locked);
  const rerender = () => renderCharacter(root, characterId, { goVoice, invalidate,
    editing: Boolean(root.querySelector('[data-profile-edit]')?.open) });
  document.title = `${character.name} — Voices — Doblarr`;
  root.innerHTML = `
    <p><a href="/voices" data-back>← All voices</a></p>
    <div class="voice-hero">
      <div class="voice-orb-wrap">${voice ? '<canvas class="voice-orb" aria-hidden="true"></canvas>' : '<span class="voice-orb-empty" aria-hidden="true"></span>'}</div>
      <div class="voice-hero-body">
        <span class="card-kicker">Character${show ? ` · ${esc(show.title)}` : ''}</span>
        <h2 data-name>${esc(character.name)}</h2>
        <form class="character-rename" data-rename-form hidden><input class="input" data-rename value="${esc(character.name)}" maxlength="80" aria-label="Name">
          <button type="submit" class="btn btn-secondary">Rename</button><button type="button" class="btn btn-ghost" data-rename-cancel>Cancel</button></form>
        ${character.aliases?.length ? `<p class="hint">Also called ${character.aliases.map(esc).join(', ')}.</p>` : ''}
        <p class="character-voice-line">${voice
          ? `Speaks with <strong>${esc(voice.display_name || voice.name)}</strong> <span class="hint">${voice.kind === 'preset' ? 'preset' : 'clone'} · ${esc(voice.engine || '')}${voice.language ? ` · ${esc(voice.language)}` : ''}</span>
            ${firm ? '' : '<button type="button" class="btn btn-ghost" data-make-firm title="This voice carries the character’s name; casting it makes dubs use it">Cast it</button>'}`
          : '<span class="hint">No voice yet. Choose one under Voice below.</span>'}</p>
        <div class="voice-tags">${voice?.gender && voice.gender !== 'unknown' ? `<span class="tag tag-neutral">${esc(voice.gender)}</span>` : ''}
          ${voice?.age && voice.age !== 'unknown' ? `<span class="tag tag-neutral">${esc(voice.age)}</span>` : ''}</div>
        ${voice?.notes ? `<p>${esc(voice.notes)}</p>` : ''}
        <button type="button" class="btn btn-ghost character-rename-open" data-rename-open>Rename</button>
      </div>
    </div>
    <p class="hint" role="status" data-status></p>
    ${voice ? hearPanel(voice) : ''}

    <section class="panel voice-panel" aria-labelledby="charTalks"><h3 id="charTalks">Where they talk</h3>
      <div data-appearances><p class="hint">Reading the analysed episodes…</p></div></section>

    <section class="panel voice-panel" aria-labelledby="charVoice"><h3 id="charVoice">Voice</h3>
      ${voice ? `<div class="voice-form">
          <label class="review-field">Gender <select class="input" data-t="gender">${['unknown', 'male', 'female', 'neutral'].map(g => `<option ${g === (voice.gender || 'unknown') ? 'selected' : ''}>${g}</option>`).join('')}</select></label>
          <label class="review-field">Age <select class="input" data-t="age">${['unknown', 'child', 'young', 'adult', 'older'].map(a => `<option ${a === (voice.age || 'unknown') ? 'selected' : ''}>${a}</option>`).join('')}</select></label>
          ${colourField(voice)}
          <label class="review-field voice-notes">Notes <textarea class="input" data-t="notes" rows="2" maxlength="500">${esc(voice.notes || '')}</textarea></label>
        </div>
        <div class="studio-actions"><button type="button" class="btn btn-secondary" data-save-voice>Save</button>
          <span class="hint" role="status" data-saved-voice></span></div>` : ''}
      <h4 class="voice-subhead">Which voice, per language</h4>
      ${data.assignments.length ? `<table class="table"><thead><tr><th>Locale</th><th>Variant</th><th>Voice</th><th>Engine can do</th><th></th></tr></thead><tbody>
        ${data.assignments.map(a => `<tr><td class="m">${esc(a.locale || 'any')}</td><td>${esc(a.variant || 'any')}</td>
          <td>${esc(catalog.find(v => v.profile_id === a.voice || v.key === a.voice)?.display_name || catalog.find(v => v.profile_id === a.voice)?.name || a.voice)}</td>
          <td class="hint">${esc((a.capabilities?.supported_controls || []).join(', ') || 'unknown')}${a.capabilities?.unsupported?.length ? `; cannot: ${esc(a.capabilities.unsupported.join(', '))}` : ''}</td>
          <td><button type="button" class="btn btn-ghost" data-unassign="${esc(a.locale || '')}" data-variant="${esc(a.variant || '')}">Remove</button></td></tr>`).join('')}
      </tbody></table>` : `<p class="hint">${voice ? 'Not cast yet: the voice above is matched by its name only.' : 'No voice cast yet.'}</p>`}
      <div class="voice-assign">
        <label class="review-field">Voice<select class="input" data-assign-voice><option value="">Choose a voice</option>
          ${catalog.map(v => `<option value="${esc(v.profile_id || '')}" data-engine="${esc(v.engine || '')}" ${v.profile_id ? '' : 'disabled'}>${esc(v.display_name || v.name)} · ${esc(v.engine || '')}</option>`).join('')}</select></label>
        <label class="review-field">Locale<input class="input m" data-assign-locale placeholder="any, or es-MX"></label>
        <label class="review-field">Variant<select class="input" data-assign-variant><option value="">any</option>
          ${(character.variants || []).map(v => `<option value="${esc(v.id)}">${esc(v.label)}</option>`).join('')}</select></label>
        <button type="button" class="btn btn-secondary" data-assign>Cast</button>
      </div></section>
    ${voice ? usedPanel(used) : ''}

    <section class="panel voice-panel" aria-labelledby="charDescribe"><h3 id="charDescribe">How they sound</h3>
      ${facts || '<p class="hint">Nothing described yet. Approve suggestions from analysed lines below, or describe the voice yourself.</p>'}
      <details class="profile-edit" data-profile-edit ${editing ? 'open' : ''}>
        <summary>Edit the description</summary>
        ${GROUPS.map(([, title, list]) => `<h4 class="voice-subhead">${title}</h4>
          <div class="voice-form">${list.map(spec => control(spec, profile, locked)).join('')}</div>`).join('')}
        <h4 class="voice-subhead">Performance range</h4>
        <p class="hint">What you want, what the cast engine can be asked for, and what an audition proved, kept apart.</p>
        <table class="table"><thead><tr><th>State</th><th>Wanted</th><th>Engine can be asked</th><th>Auditioned</th></tr></thead><tbody>
        ${VARIATIONS.map(v => {
          const row = profile.variations[v] || {};
          const support = (data.assignments[0]?.variations || {})[v] || 'unknown';
          return `<tr><td>${v}</td>
            <td><select class="input" data-field="variations.${v}.desired" data-kind="tri">${['', 'yes', 'no'].map(o => `<option value="${o}" ${(row.desired === true && o === 'yes') || (row.desired === false && o === 'no') || (row.desired == null && o === '') ? 'selected' : ''}>${o || 'unknown'}</option>`).join('')}</select></td>
            <td class="m">${esc(support)}</td>
            <td><select class="input" data-field="variations.${v}.auditioned">${VERDICTS.map(o => `<option ${o === row.auditioned ? 'selected' : ''}>${o}</option>`).join('')}</select></td></tr>`;
        }).join('')}</tbody></table>
        <h4 class="voice-subhead">Templates</h4>
        <p class="hint">Envelope templates this character tends to suit, or should avoid. Recommendations weigh them; they never force one.</p>
        <div class="voice-form">
          <label class="review-field">Favoured<select class="input" multiple size="5" data-templates="favored">${templates.map(t => `<option value="${esc(t.id)}" ${(profile.templates.favored || []).some(p => p.template === t.id) ? 'selected' : ''}>${esc(t.title)}</option>`).join('')}</select></label>
          <label class="review-field">Avoid<select class="input" multiple size="5" data-templates="discouraged">${templates.map(t => `<option value="${esc(t.id)}" ${(profile.templates.discouraged || []).some(p => p.template === t.id) ? 'selected' : ''}>${esc(t.title)}</option>`).join('')}</select></label>
        </div>
        <div class="studio-actions"><button type="button" class="btn btn-primary" data-save>Save changes</button>
          <span class="hint">Only what you changed is saved. Saving never generates speech.</span></div>
      </details>
      <h4 class="voice-subhead">Suggestions from analysed lines</h4>
      <div data-proposals><p class="hint">Reading analysed lines…</p></div>
    </section>

    <section class="panel voice-panel" aria-labelledby="charRefs"><h3 id="charRefs">References</h3>
      <p class="hint">Lines of the original actor a clone learns from. ${data.references.approved} approved${data.references.neutral ? '' : ', no neutral one yet'}${data.references.expressive ? '' : ', no expressive one yet'}.</p>
      ${profile.references.length ? `<table class="table"><thead><tr><th>Kind</th><th>Line</th><th>Quality</th><th>State</th><th></th></tr></thead><tbody>
        ${profile.references.map(r => `<tr><td>${esc(r.kind)} · ${esc(r.variation)}</td>
          <td>${esc(r.transcript || '')}<br><span class="hint m">${r.source.start.toFixed(1)}–${r.source.end.toFixed(1)} s · ${esc(r.provenance || '')}</span></td>
          <td class="hint">${r.quality.duration ? `${r.quality.duration} s` : ''}${r.quality.relative_db != null ? ` · ${r.quality.relative_db > 0 ? '+' : ''}${r.quality.relative_db} dB` : ''}</td>
          <td>${r.retired ? 'retired' : r.approved ? 'approved' : 'not approved'}</td>
          <td>${r.retired ? '' : `<button type="button" class="btn btn-ghost" data-ref="${esc(r.id)}" data-approve="${r.approved ? 'false' : 'true'}">${r.approved ? 'Unapprove' : 'Approve'}</button>
            <button type="button" class="btn btn-ghost" data-ref="${esc(r.id)}" data-retire="true">Retire</button>`}</td></tr>`).join('')}
      </tbody></table>` : ''}
      ${profile.auditions.length ? `<h4 class="voice-subhead">Auditions</h4>${profile.auditions.map(a => `<p class="hint">${esc(a.at)} · ${esc(a.language)} · ${esc(a.verdict)} · ${esc(a.context || '')}</p>`).join('')}` : ''}
    </section>`;

  const say = msg => { root.querySelector('[data-status]').textContent = msg; };
  back();
  const orb = voice ? mountOrb(root, voice) : null;
  if (voice) {
    mountHear(root, voice, orb);
    mountColour(root, voice, orb);
    root.querySelector('[data-save-voice]').onclick = async () => {
      const body = { key: voice.key, color: colourValue(root) };
      root.querySelectorAll('[data-t]').forEach(el => { body[el.dataset.t] = el.value.trim(); });
      try {
        await api('voice-catalog/traits', { method: 'PUT', json: body });
        invalidate();
        root.querySelector('[data-saved-voice]').textContent = 'Saved.';
      } catch (error) { root.querySelector('[data-saved-voice]').textContent = error.message; }
    };
  }

  // Rename (fixes "MINA" from an older import to "Mina"; the old name stays an alias).
  const form = root.querySelector('[data-rename-form]');
  root.querySelector('[data-rename-open]').onclick = () => { form.hidden = false; form.querySelector('input').focus(); };
  root.querySelector('[data-rename-cancel]').onclick = () => { form.hidden = true; };
  form.onsubmit = async e => {
    e.preventDefault();
    const name = form.querySelector('input').value.trim();
    if (!name || name === character.name) { form.hidden = true; return; }
    try {
      await api(`characters/${encodeURIComponent(characterId)}`, { method: 'PATCH', json: { base_revision: character.revision, name } });
      invalidate();
      await rerender();
    } catch (error) { say(error.message); }
  };

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
      await rerender();
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
      await rerender();
    } catch (error) { say(error.message); }
  });
  const assign = async body => {
    try {
      await api(`characters/${encodeURIComponent(characterId)}/assignments`, { method: 'PUT', json: body });
      invalidate();
      await rerender();
      say('Cast. Lines already rendered keep their voice until you re-render them.');
    } catch (error) { say(error.message); }
  };
  root.querySelector('[data-make-firm]')?.addEventListener('click', () =>
    assign({ voice: voice.profile_id, engine: voice.engine || '' }));
  root.querySelector('[data-assign]').onclick = () => {
    const picked = root.querySelector('[data-assign-voice]');
    if (!picked.value) { say('Choose a voice first.'); return; }
    assign({ voice: picked.value, engine: picked.selectedOptions[0].dataset.engine || '',
      locale: root.querySelector('[data-assign-locale]').value.trim(),
      variant: root.querySelector('[data-assign-variant]').value });
  };
  root.querySelectorAll('[data-unassign]').forEach(b => b.onclick = () =>
    assign({ clear: true, locale: b.dataset.unassign, variant: b.dataset.variant }));
  loadAppearances(root.querySelector('[data-appearances]'), character, voice);
  loadProposals(root.querySelector('[data-proposals]'), characterId, profile.revision, rerender);
}

// Each analysed episode the character speaks in: how much, stills from
// their lines (click to watch from there) and the lines themselves.
async function loadAppearances(box, character, voice) {
  let data;
  try { data = await api(`characters/${encodeURIComponent(character.id)}/appearances`); }
  catch (error) { box.innerHTML = `<p class="hint">${esc(error.message)}</p>`; return; }
  if (!data.episodes.length) {
    box.innerHTML = '<p class="hint">No analysed episode names this character yet. Name their voice on an episode’s Analysis tab.</p>';
    return;
  }
  const colour = voice?.color || 'var(--color-accent)';
  box.innerHTML = `<p class="hint">${data.lines} line${data.lines === 1 ? '' : 's'} in ${data.episodes.length} analysed episode${data.episodes.length === 1 ? '' : 's'}.</p>
    ${data.episodes.map((e, n) => `<div class="appear-episode">
      <div class="appear-head"><strong>${esc(e.episode || e.revision_id)}</strong>
        <span class="hint"><span class="m">${e.lines.length}</span> lines · <span class="m">${clock(e.seconds)}</span></span>
        ${e.reachable ? `<button type="button" class="btn btn-ghost" data-watch-episode="${n}">Watch their lines</button>` : '<span class="hint">video not reachable from here</span>'}</div>
      ${e.reachable ? `<div class="cast-frames">${pickFrames(e.lines, {}, 6).map(l => `<button type="button" class="cast-frame" style="--tint:${esc(colour)}"
          data-watch-episode="${n}" data-from="${esc(l.cue)}" title="${clock(l.start)} · ${esc(l.text)}">
          <img src="${frameUrl(e.path, (l.start + l.end) / 2)}" alt="The picture at ${clock(l.start)}" width="160" height="90" decoding="async">
          <span class="cast-frame-time m">${clock(l.start)}</span></button>`).join('')}</div>` : ''}
      <details class="appear-lines"><summary>Their lines</summary><ol>${e.lines.map(l => `<li><span class="m hint">${clock(l.start)}</span> ${esc(l.text)}${l.original_text ? ` <span class="hint">${esc(l.original_text)}</span>` : ''}</li>`).join('')}</ol></details>
    </div>`).join('')}`;
  box.querySelectorAll('[data-watch-episode]').forEach(b => b.onclick = async () => {
    const e = data.episodes[Number(b.dataset.watchEpisode)];
    let found;
    try { found = await api(`analysis/tracks?path=${encodeURIComponent(e.path)}`); } catch (error) { b.title = error.message; return; }
    const clips = e.lines.map(l => {
      const start = Math.max(0, l.start - 0.35);
      const end = Math.min(start + 29.5, l.end + 0.45);
      return { start, end, label: clock(l.start), text: l.text, detail: l.original_text || '', cue: l.cue,
        url: stream => videoUrl(e.path, start, end, stream) };
    });
    openMediaPlayer({ title: character.name, colour, subtitle: `${e.episode} · ${e.lines.length} lines, back to back`,
      clips, tracks: found.tracks.map(t => ({ key: t.stream, label: trackLabel(t) })), track: found.default,
      startAt: Math.max(0, e.lines.findIndex(l => l.cue === b.dataset.from)) });
  });
}

const LABELS = Object.fromEntries(GROUPS.flatMap(([, , list]) => list.map(([path, label]) => [path, label])));
const fieldLabel = path => LABELS[path] || ({ 'vocal.pitch_range': 'Pitch range', 'dynamics.measured': 'How loud they get (measured)' })[path]
  || (/^variations\.(\w+)\.desired$/.test(path) ? `Wanted: ${path.split('.')[1]}` : path);
function fieldValue(value) {
  if (value === true) return 'yes';
  if (value === false) return 'no';
  if (value && typeof value === 'object' && 'low' in value) {
    const unit = value.units === 'Hz' ? ' Hz' : value.units ? ` ${value.units.replace(' relative', '')}` : '';
    return `${value.low} to ${value.high}${unit}`;
  }
  return Array.isArray(value) ? value.join(', ') : String(value);
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
      <span><strong>${esc(p.kind === 'reference' ? `Reference line: ${p.value.kind}, ${p.value.variation}` : fieldLabel(p.field))}</strong>
      ${p.kind === 'reference' ? `“${esc(p.value.transcript)}”` : esc(fieldValue(p.value))}
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
