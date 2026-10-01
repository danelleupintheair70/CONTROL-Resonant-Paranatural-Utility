import { api, apiUrl } from './api.js';
import { escapeHtml as esc, safeGet } from './dom.js';
import { library } from './state.js';
import { createOrb, primeAudio } from './orb.js';

// The voice catalogue as a cast: named voices grouped by the show they belong
// to first, then presets, then the working clones a run or an audition made
// (named after a scene and a hash until somebody says who they are).
// /voices lists them; /voices/<key> is one voice with its orb, a preview and
// who it is.

const FILTERS = [['cast', 'Cast'], ['preset', 'Presets'], ['working', 'Working clones'], ['all', 'All']];
const PALETTES = [['#CADCFC', '#A0B9D1'], ['#F6C6A8', '#E8845C'], ['#C9F2D6', '#7FC8A4'],
  ['#E7D1FA', '#B18AE0'], ['#FCE7A8', '#E9B949'], ['#FAD0DA', '#E47A98']];
const AGES = ['unknown', 'child', 'young', 'adult', 'older'];
const GENDERS = ['unknown', 'male', 'female', 'neutral'];
const SAMPLE = '¡Esto es una prueba de voz! A ver cómo suena este personaje.';

// A clone made by a run (<file stem>-<16 hex>) or a studio audition.
const isWorking = v => v.kind !== 'preset' && !v.display_name
  && (/-[0-9a-f]{16}$/.test(v.name) || v.name.startsWith('Doblarr studio') || v.name.startsWith('Doblarr audition'));
const isNamed = v => Boolean(v.display_name || v.character || v.show);

// A voice's colours: the one a person chose for the character, else a stable
// pick from its key. The orb ramps black → first → second → white, so the
// second is the chosen colour lifted toward white.
export function lighten(hex, amount = 0.5) {
  const v = parseInt(hex.slice(1), 16);
  const mix = c => Math.round(c + (255 - c) * amount);
  return '#' + [(v >> 16) & 255, (v >> 8) & 255, v & 255].map(c => mix(c).toString(16).padStart(2, '0')).join('');
}

export function palette(v) {
  if (/^#[0-9a-f]{6}$/i.test(v.color || '')) return [v.color, lighten(v.color)];
  let h = 0;
  for (const c of String(v.key)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return PALETTES[h % PALETTES.length];
}

function seedOf(key) {
  let h = 2166136261;
  for (const c of String(key)) h = Math.imul(h ^ c.charCodeAt(0), 16777619) >>> 0;
  return h;
}

const title = v => v.display_name || v.name;
const identity = v => [v.character && v.character.toLowerCase() !== (v.display_name || '').toLowerCase() ? v.character : '', v.show_name || v.show]
  .filter(Boolean).join(' · ');

export function createVoices({ goVoice }) {
  let catalog = null, filter = 'cast', query = '', orb = null, loading = null;

  async function load(refresh = false) {
    if (catalog && !refresh) return catalog;
    loading = loading || api(`voice-catalog${refresh ? '?refresh=true' : ''}`).finally(() => { loading = null; });
    catalog = (await loading).voices || [];
    return catalog;
  }

  async function renderVoices(voiceKey) {
    orb?.destroy(); orb = null;
    const root = document.getElementById('voicesRoot');
    if (!root) return;
    if (voiceKey) return renderDetail(root, voiceKey);
    root.innerHTML = '<p class="hint">Loading voices…</p>';
    try { await load(); } catch (error) { root.textContent = error.message; return; }
    drawList(root);
  }

  function drawList(root) {
    const matches = v => !query || `${title(v)} ${v.name} ${v.character || ''} ${v.show_name || ''} ${v.engine}`
      .toLowerCase().includes(query);
    const shown = catalog.filter(v => matches(v) && (filter === 'all'
      || (filter === 'cast' && isNamed(v))
      || (filter === 'preset' && v.kind === 'preset' && !isNamed(v))
      || (filter === 'working' && isWorking(v))));
    const groups = new Map();
    for (const v of shown.filter(isNamed)) {
      const show = v.show_name || v.show || 'No show';
      if (!groups.has(show)) groups.set(show, []);
      groups.get(show).push(v);
    }
    for (const voices of groups.values()) voices.sort((a, b) => title(a).localeCompare(title(b)));
    const counts = { cast: catalog.filter(isNamed).length,
      preset: catalog.filter(v => v.kind === 'preset' && !isNamed(v)).length,
      working: catalog.filter(isWorking).length, all: catalog.length };
    root.innerHTML = `
      <div class="voices-head">
        <div><h2>Voices</h2>
          <p class="hint">The cast you have named, grouped by show, then presets and the working clones runs made. Open a voice to hear it and say who it is.</p></div>
        <input class="input voices-search" type="search" placeholder="Search voices" aria-label="Search voices" value="${esc(query)}">
      </div>
      <div class="opts voices-filter" role="group" aria-label="Which voices">${FILTERS.map(([id, label]) =>
        `<button type="button" class="opt" data-filter="${id}" aria-pressed="${filter === id}">${label} <span class="m">${counts[id]}</span></button>`).join('')}</div>
      ${filter === 'cast' && !shown.length ? `<div class="panel voices-empty"><p>No named voices yet.</p>
        <p class="hint">Open a working clone (the ones a run made from a scene) and give it a name, a character and a show. It then shows up here with its cast.</p></div>` : ''}
      ${[...groups].map(([show, voices]) => `
        <section class="voices-group"><h3>${esc(show)} <span class="hint">${voices.length} voice${voices.length === 1 ? '' : 's'}</span></h3>
          <div class="voice-grid">${voices.map(card).join('')}</div></section>`).join('')}
      ${filter !== 'cast' && shown.filter(v => !isNamed(v)).length ? `<div class="panel voices-table"><table class="table">
        <thead><tr><th>Voice</th><th>Engine</th><th>Kind</th><th>Language</th></tr></thead>
        <tbody>${shown.filter(v => !isNamed(v)).map(v => `<tr data-voice="${esc(v.key)}" tabindex="0">
          <td><span class="voice-dot" style="${dotStyle(v)}"></span>${esc(title(v))}</td>
          <td class="m">${esc(v.engine || '')}</td><td>${esc(v.kind || '')}</td><td class="m">${esc(v.language || '—')}</td></tr>`).join('')}
        </tbody></table></div>` : ''}`;
    root.querySelector('.voices-search').oninput = e => {
      query = e.target.value.toLowerCase();
      const at = e.target.selectionStart;
      drawList(root);
      const input = root.querySelector('.voices-search');
      input.focus(); input.setSelectionRange(at, at);
    };
    root.querySelectorAll('[data-filter]').forEach(b => b.onclick = () => { filter = b.dataset.filter; drawList(root); });
    root.querySelectorAll('[data-voice]').forEach(el => {
      el.onclick = () => goVoice(el.dataset.voice);
      el.onkeydown = e => { if (e.key === 'Enter') goVoice(el.dataset.voice); };
    });
  }

  function dotStyle(v) {
    const [a, b] = palette(v);
    return `background: radial-gradient(circle at 35% 30%, #fff 0%, ${a} 38%, ${b} 100%);`;
  }

  function card(v) {
    return `<button type="button" class="voice-tile" data-voice="${esc(v.key)}">
      <span class="voice-dot voice-dot-lg" style="${dotStyle(v)}"></span>
      <span class="voice-tile-body"><strong>${esc(title(v))}</strong>
        <span class="hint">${esc(identity(v) || v.engine || '')}</span>
        <span class="voice-tags">${v.gender && v.gender !== 'unknown' ? `<span class="tag tag-neutral">${esc(v.gender)}</span>` : ''}
          ${v.age && v.age !== 'unknown' ? `<span class="tag tag-neutral">${esc(v.age)}</span>` : ''}
          <span class="tag tag-outline">${esc(v.engine || v.kind)}</span></span></span></button>`;
  }

  async function renderDetail(root, key) {
    root.innerHTML = '<p class="hint">Loading the voice…</p>';
    let data;
    try { data = await api(`voice-catalog/voice?key=${encodeURIComponent(key)}`); } catch (error) {
      root.innerHTML = `<p><a href="/voices" data-back>← All voices</a></p><p>${esc(error.message)}</p>`;
      root.querySelector('[data-back]').onclick = e => { e.preventDefault(); goVoice(''); };
      return;
    }
    const v = data.voice;
    document.title = `${title(v)} — Voices — Doblarr`;
    const shows = (library.items || []).filter(i => i.media_type === 'show' && i.tvdb_id);
    root.innerHTML = `
      <p><a href="/voices" data-back>← All voices</a></p>
      <div class="voice-hero">
        <div class="voice-orb-wrap"><canvas class="voice-orb" aria-hidden="true"></canvas></div>
        <div class="voice-hero-body">
          <span class="card-kicker">${esc(v.kind || 'voice')} · ${esc(v.engine || '')}${v.language ? ` · ${esc(v.language)}` : ''}</span>
          <h2>${esc(title(v))}</h2>
          <p class="hint">${esc(identity(v) || 'Not tied to a show or character yet.')}</p>
          ${v.display_name ? `<p class="hint m">${esc(v.name)}</p>` : ''}
          <div class="voice-tags">${v.gender && v.gender !== 'unknown' ? `<span class="tag tag-neutral">${esc(v.gender)}</span>` : ''}
            ${v.age && v.age !== 'unknown' ? `<span class="tag tag-neutral">${esc(v.age)}</span>` : ''}</div>
          ${v.notes ? `<p>${esc(v.notes)}</p>` : ''}
        </div>
      </div>

      <section class="panel voice-panel" aria-labelledby="voiceHear">
        <h3 id="voiceHear">Hear it</h3>
        <div class="voice-preview-row">
          <textarea class="input voice-text" rows="2" maxlength="300" aria-label="Text to speak">${esc(SAMPLE)}</textarea>
          <label class="review-field">Language <input class="input m voice-lang" value="${esc((v.language || 'es').slice(0, 2))}" maxlength="2" size="3"></label>
          <button type="button" class="btn btn-primary" data-speak>Generate and play</button>
        </div>
        <audio class="voice-audio" controls hidden></audio>
        <p class="hint" role="status" data-status></p>
      </section>

      <section class="panel voice-panel" aria-labelledby="voiceWho">
        <h3 id="voiceWho">Who this is</h3>
        <div class="voice-form">
          <label class="review-field">Name <input class="input" data-t="display_name" maxlength="80" value="${esc(v.display_name || '')}" placeholder="${esc(v.name)}"></label>
          <label class="review-field">Character <input class="input" data-t="character" maxlength="80" value="${esc(v.character || '')}" placeholder="MINA"></label>
          <label class="review-field">Show <input class="input" data-t="show" maxlength="200" list="voiceShows" value="${esc(v.show || '')}" placeholder="tvdb-12345"></label>
          <label class="review-field">Show name <input class="input" data-t="show_name" maxlength="200" value="${esc(v.show_name || '')}"></label>
          <label class="review-field">Gender <select class="input" data-t="gender">${GENDERS.map(g => `<option ${g === (v.gender || 'unknown') ? 'selected' : ''}>${g}</option>`).join('')}</select></label>
          <label class="review-field">Age <select class="input" data-t="age">${AGES.map(a => `<option ${a === (v.age || 'unknown') ? 'selected' : ''}>${a}</option>`).join('')}</select></label>
          <div class="review-field voice-color">Colour
            <span class="voice-color-row"><input type="color" class="voice-color-input" aria-label="Character colour" value="${esc(palette(v)[0])}" ${v.color ? 'data-chosen' : ''}>
              <span class="hint" data-color-note>${v.color ? esc(v.color) : 'automatic'}</span>
              <button type="button" class="btn btn-ghost" data-color-auto ${v.color ? '' : 'hidden'}>Automatic</button></span></div>
          <label class="review-field voice-notes">Notes <textarea class="input" data-t="notes" rows="2" maxlength="500">${esc(v.notes || '')}</textarea></label>
        </div>
        <datalist id="voiceShows">${shows.map(s => `<option value="tvdb-${esc(s.tvdb_id)}">${esc(s.title)}</option>`).join('')}</datalist>
        <div class="studio-actions"><button type="button" class="btn btn-secondary" data-save>Save</button>
          <span class="hint" role="status" data-saved></span></div>
      </section>

      <section class="panel voice-panel" aria-labelledby="voiceUsed">
        <h3 id="voiceUsed">Cast in</h3>
        ${data.used_in.length ? `<table class="table"><thead><tr><th>Title</th><th>Speaker</th><th>Shaping</th></tr></thead><tbody>
          ${data.used_in.map(u => `<tr><td>${esc(u.title || u.title_key)}</td><td class="m">${esc(u.label || u.speaker || '')}</td>
            <td class="m">${[u.pitch_semitones ? `${u.pitch_semitones > 0 ? '+' : ''}${u.pitch_semitones} st pitch` : '',
              u.formant_semitones ? `${u.formant_semitones > 0 ? '+' : ''}${u.formant_semitones} st formant` : ''].filter(Boolean).join(' · ') || '—'}</td></tr>`).join('')}
          </tbody></table>` : '<p class="hint">Not cast in any saved title yet.</p>'}
      </section>`;

    root.querySelector('[data-back]').onclick = e => { e.preventDefault(); goVoice(''); };
    const canvas = root.querySelector('.voice-orb');
    const [a, b] = palette(v);
    try { orb = createOrb(canvas, { colors: [a, b], seed: seedOf(v.key) }); } catch (error) {
      canvas.replaceWith(Object.assign(document.createElement('span'), { className: 'voice-dot voice-dot-xl' }));
    }
    const audio = root.querySelector('.voice-audio');
    const status = root.querySelector('[data-status]');
    let version = 0;
    root.querySelector('[data-speak]').onclick = async () => {
      const mine = ++version;
      try { primeAudio(); } catch { /* no Web Audio: the orb just idles */ }
      audio.pause();
      status.textContent = 'Generating…';
      try {
        const made = await api('voice-catalog/preview', { method: 'POST', json: { key: v.key,
          language: root.querySelector('.voice-lang').value.trim().toLowerCase() || 'es',
          text: root.querySelector('.voice-text').value.trim() || SAMPLE } });
        const deadline = Date.now() + 180000;
        for (;;) {
          if (mine !== version || !audio.isConnected) return;
          const state = await api(`voice-catalog/preview/${made.id}`);
          if (['completed', 'done', 'ready', 'success'].includes(state.status)) break;
          if (['failed', 'error', 'cancelled', 'canceled'].includes(state.status)) throw new Error(state.error || 'The sample failed.');
          if (Date.now() > deadline) throw new Error('Still generating in the speech service; try again shortly.');
          await new Promise(r => setTimeout(r, 1200));
        }
        const apiKey = safeGet('doblarr_api_key', '');
        audio.src = apiUrl(`voice-catalog/preview/${made.id}/audio`) + (apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : '');
        audio.hidden = false;
        orb?.follow(audio);
        await audio.play();
        status.textContent = '';
      } catch (error) { if (mine === version) status.textContent = error.message; }
    };
    const picker = root.querySelector('.voice-color-input');
    const note = root.querySelector('[data-color-note]');
    const auto = root.querySelector('[data-color-auto]');
    picker.oninput = () => {
      picker.dataset.chosen = '1';
      note.textContent = picker.value;
      auto.hidden = false;
      orb?.setColors(picker.value, lighten(picker.value));
    };
    auto.onclick = () => {
      delete picker.dataset.chosen;
      const [c1, c2] = palette({ key: v.key });
      picker.value = c1;
      note.textContent = 'automatic';
      auto.hidden = true;
      orb?.setColors(c1, c2);
    };
    root.querySelector('[data-save]').onclick = async () => {
      const body = { key: v.key, color: picker.dataset.chosen ? picker.value : '' };
      root.querySelectorAll('[data-t]').forEach(el => { body[el.dataset.t] = el.value.trim(); });
      const saved = root.querySelector('[data-saved]');
      try {
        await api('voice-catalog/traits', { method: 'PUT', json: body });
        catalog = null;
        saved.textContent = 'Saved.';
        renderVoices(key);
      } catch (error) { saved.textContent = error.message; }
    };
  }

  return { renderVoices };
}
