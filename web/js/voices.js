import { api } from './api.js';
import { escapeHtml as esc } from './dom.js';
import { library } from './state.js';
import { createOrb } from './orb.js';
import { characterPicker } from './character-picker.js';
import { renderCharacter } from './character-profile.js';
import { characterFor, dotStyle, hearPanel, lighten, mountHear, palette, seedOf, seriesOfShow,
  showOfSeries, voiceFor } from './voice-common.js';

export { lighten, palette };

// The voice catalogue as a cast. A show's characters are the cast: each one
// is a single page (/voices/character:<id>) with the voice it speaks with.
// A voice nobody cast yet has a page of its own (/voices/<catalog key>) to
// hear it and cast it as a character; once cast, that address opens the
// character. Presets and the working clones runs made are filters.

const FILTERS = [['cast', 'Cast'], ['preset', 'Presets'], ['working', 'Working clones'], ['all', 'All']];
const AGES = ['unknown', 'child', 'young', 'adult', 'older'];
const GENDERS = ['unknown', 'male', 'female', 'neutral'];

// A clone made by a run (<file stem>-<16 hex>) or a studio audition.
const isWorking = v => v.kind !== 'preset' && !v.display_name
  && (/-[0-9a-f]{16}$/.test(v.name) || v.name.startsWith('Doblarr studio') || v.name.startsWith('Doblarr audition'));
const isNamed = v => Boolean(v.display_name || v.character || v.show);
const title = v => v.display_name || v.name;

function showTitle(seriesId, fallback = '') {
  const tvdb = showOfSeries(seriesId).slice(5);
  const item = (library.items || []).find(i => (tvdb && String(i.tvdb_id) === tvdb)
    || (seriesId.startsWith('movie:tmdb:') && `movie:tmdb:${i.tmdb_id}` === seriesId));
  return item?.title || fallback || 'No show';
}

const shows = () => (library.items || []).filter(i => (i.media_type === 'show' && i.tvdb_id) || (i.media_type === 'movie' && i.tmdb_id))
  .map(i => ({ id: i.media_type === 'show' ? `show:tvdb:${i.tvdb_id}` : `movie:tmdb:${i.tmdb_id}`, label: i.title }))
  .sort((a, b) => a.label.localeCompare(b.label));

export function createVoices({ goVoice }) {
  let catalog = null, characters = [], filter = 'cast', query = '', orb = null, loading = null;

  async function load(refresh = false) {
    if (catalog && !refresh) return catalog;
    loading = loading || Promise.all([api(`voice-catalog${refresh ? '?refresh=true' : ''}`),
      api('characters').catch(() => ({ characters: [] }))]).finally(() => { loading = null; });
    const [found, cast] = await loading;
    catalog = found.voices || [];
    characters = cast.characters || [];
    return catalog;
  }

  const invalidate = () => { catalog = null; };

  async function renderVoices(voiceKey) {
    orb?.destroy(); orb = null;
    const root = document.getElementById('voicesRoot');
    if (!root) return;
    if (voiceKey?.startsWith('character:')) return renderCharacter(root, voiceKey.slice(10), { goVoice, invalidate });
    if (voiceKey) return renderDetail(root, voiceKey);
    root.innerHTML = '<p class="hint">Loading voices…</p>';
    try { await load(); } catch (error) { root.textContent = error.message; return; }
    drawList(root);
  }

  function drawList(root) {
    const matches = (...words) => !query || words.join(' ').toLowerCase().includes(query);
    const linked = new Set();
    const groups = new Map();
    const add = (series, label, tile) => {
      if (!groups.has(series)) groups.set(series, { label, tiles: [] });
      groups.get(series).tiles.push(tile);
    };
    if (filter === 'cast' || filter === 'all') {
      for (const c of characters) {
        const voice = voiceFor(c, catalog);
        if (voice) linked.add(voice.key);
        if (!matches(c.name, ...(c.aliases || []), voice ? title(voice) : '', voice?.engine || '')) continue;
        add(c.series_id, showTitle(c.series_id, voice?.show_name), { name: c.name, voice, character: c });
      }
      for (const v of catalog.filter(x => isNamed(x) && !linked.has(x.key) && !characterFor(x, characters))) {
        if (!matches(title(v), v.character || '', v.show_name || '', v.engine)) continue;
        const series = seriesOfShow(v.show) || `voice-show:${v.show_name || ''}`;
        add(series, v.show_name || showTitle(series), { name: title(v), voice: v });
      }
    }
    for (const g of groups.values()) g.tiles.sort((x, y) => x.name.localeCompare(y.name));
    const loose = catalog.filter(v => !isNamed(v) && matches(title(v), v.engine)
      && (filter === 'all' || (filter === 'preset' && v.kind === 'preset') || (filter === 'working' && isWorking(v))));
    const counts = { cast: characters.length + catalog.filter(v => isNamed(v) && !characterFor(v, characters)).length,
      preset: catalog.filter(v => v.kind === 'preset' && !isNamed(v)).length,
      working: catalog.filter(isWorking).length, all: catalog.length };
    root.innerHTML = `
      <div class="voices-head">
        <div><h2>Voices</h2>
          <p class="hint">Every show’s characters and the voice each one speaks with. Open one to hear it, see where it talks and describe it.</p></div>
        <input class="input voices-search" type="search" placeholder="Search characters and voices" aria-label="Search voices" value="${esc(query)}">
      </div>
      <div class="opts voices-filter" role="group" aria-label="Which voices">${FILTERS.map(([id, label]) =>
        `<button type="button" class="opt" data-filter="${id}" aria-pressed="${filter === id}">${label} <span class="m">${counts[id]}</span></button>`).join('')}</div>
      ${filter === 'cast' && !groups.size ? `<div class="panel voices-empty"><p>No characters yet.</p>
        <p class="hint">Name the voices on an episode’s Analysis tab, or open a working clone and cast it as a character.</p></div>` : ''}
      ${[...groups.values()].sort((x, y) => x.label.localeCompare(y.label)).map(g => `
        <section class="voices-group"><h3>${esc(g.label)} <span class="hint">${g.tiles.length} character${g.tiles.length === 1 ? '' : 's'}</span></h3>
          <div class="voice-grid">${g.tiles.map(card).join('')}</div></section>`).join('')}
      ${loose.length ? `<div class="panel voices-table"><table class="table">
        <thead><tr><th>Voice</th><th>Engine</th><th>Kind</th><th>Language</th></tr></thead>
        <tbody>${loose.map(v => `<tr data-voice="${esc(v.key)}" tabindex="0">
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
    root.querySelectorAll('[data-voice], [data-character]').forEach(el => {
      const go = () => goVoice(el.dataset.character ? `character:${el.dataset.character}` : el.dataset.voice);
      el.onclick = go;
      el.onkeydown = e => { if (e.key === 'Enter') go(); };
    });
  }

  function card({ name, voice, character }) {
    return `<button type="button" class="voice-tile${voice ? '' : ' voice-tile-silent'}" ${character ? `data-character="${esc(character.id)}"` : `data-voice="${esc(voice.key)}"`}>
      <span class="voice-dot voice-dot-lg" style="${voice ? dotStyle(voice) : ''}"></span>
      <span class="voice-tile-body"><strong>${esc(name)}</strong>
        <span class="hint">${voice ? `${voice.kind === 'preset' ? 'preset' : 'clone'} · ${esc(voice.engine || '')}${voice.language ? ` · ${esc(voice.language)}` : ''}` : 'No voice yet'}</span>
        <span class="voice-tags">${voice?.gender && voice.gender !== 'unknown' ? `<span class="tag tag-neutral">${esc(voice.gender)}</span>` : ''}
          ${voice?.age && voice.age !== 'unknown' ? `<span class="tag tag-neutral">${esc(voice.age)}</span>` : ''}</span></span></button>`;
  }

  // A voice of the catalogue. Cast as a character, its page is the
  // character's; otherwise: hear it, say what it is, cast it.
  async function renderDetail(root, key) {
    root.innerHTML = '<p class="hint">Loading the voice…</p>';
    let data;
    try {
      [data] = await Promise.all([api(`voice-catalog/voice?key=${encodeURIComponent(key)}`), load()]);
    } catch (error) {
      root.innerHTML = `<p><a href="/voices" data-back>← All voices</a></p><p>${esc(error.message)}</p>`;
      root.querySelector('[data-back]').onclick = e => { e.preventDefault(); goVoice(''); };
      return;
    }
    const v = data.voice;
    const owner = characterFor(v, characters);
    if (owner) {
      history.replaceState({}, '', `/voices/character:${encodeURIComponent(owner.id)}`);
      return renderCharacter(root, owner.id, { goVoice, invalidate });
    }
    document.title = `${title(v)} — Voices — Doblarr`;
    root.innerHTML = `
      <p><a href="/voices" data-back>← All voices</a></p>
      <div class="voice-hero">
        <div class="voice-orb-wrap"><canvas class="voice-orb" aria-hidden="true"></canvas></div>
        <div class="voice-hero-body">
          <span class="card-kicker">${esc(v.kind || 'voice')} · ${esc(v.engine || '')}${v.language ? ` · ${esc(v.language)}` : ''}</span>
          <h2>${esc(title(v))}</h2>
          ${v.display_name ? `<p class="hint m">${esc(v.name)}</p>` : ''}
          <p class="hint">Not cast as a character yet. Cast it below and this page becomes that character’s.</p>
          ${v.notes ? `<p>${esc(v.notes)}</p>` : ''}
        </div>
      </div>
      ${hearPanel(v)}
      <section class="panel voice-panel" aria-labelledby="voiceCastAs">
        <h3 id="voiceCastAs">Cast as a character</h3>
        <div class="voice-cast-as">
          <label class="review-field">Show or film <select class="input" data-cast-series><option value="">Choose one</option>
            ${shows().map(s => `<option value="${esc(s.id)}" ${s.id === seriesOfShow(v.show) ? 'selected' : ''}>${esc(s.label)}</option>`).join('')}</select></label>
          <span data-cast-picker></span>
        </div>
        <p class="hint" role="status" data-cast-status></p>
      </section>
      <section class="panel voice-panel" aria-labelledby="voiceWho">
        <h3 id="voiceWho">About this voice</h3>
        <div class="voice-form">
          <label class="review-field">Name <input class="input" data-t="display_name" maxlength="80" value="${esc(v.display_name || '')}" placeholder="${esc(v.name)}"></label>
          <label class="review-field">Gender <select class="input" data-t="gender">${GENDERS.map(g => `<option ${g === (v.gender || 'unknown') ? 'selected' : ''}>${g}</option>`).join('')}</select></label>
          <label class="review-field">Age <select class="input" data-t="age">${AGES.map(a => `<option ${a === (v.age || 'unknown') ? 'selected' : ''}>${a}</option>`).join('')}</select></label>
          ${colourField(v)}
          <label class="review-field voice-notes">Notes <textarea class="input" data-t="notes" rows="2" maxlength="500">${esc(v.notes || '')}</textarea></label>
        </div>
        <div class="studio-actions"><button type="button" class="btn btn-secondary" data-save>Save</button>
          <span class="hint" role="status" data-saved></span></div>
      </section>
      ${usedPanel(data.used_in)}`;

    root.querySelector('[data-back]').onclick = e => { e.preventDefault(); goVoice(''); };
    orb = mountOrb(root, v);
    mountHear(root, v, orb);
    mountColour(root, v, orb);
    const castStatus = root.querySelector('[data-cast-status]');
    const series = root.querySelector('[data-cast-series]');
    const drawPicker = () => {
      const slot = root.querySelector('[data-cast-picker]');
      const cast = characters.filter(c => c.series_id === series.value).map(c => ({ name: c.name, lines: 0, episodes: 0 }));
      slot.replaceChildren(characterPicker({ label: 'Cast as', value: '', placeholder: series.value ? 'Pick or type a character' : 'Choose a show first',
        cast, suggestions: [], onPick: name => name && castAs(series.value, name) }));
    };
    series.onchange = drawPicker;
    drawPicker();
    const castAs = async (seriesId, name) => {
      if (!seriesId) { castStatus.textContent = 'Choose the show first.'; return; }
      castStatus.textContent = `Casting ${title(v)} as ${name}…`;
      try {
        const chosen = v.profile_id ? { profile_id: v.profile_id, engine: v.engine }
          : await api('voice-catalog/select', { method: 'POST', json: { key: v.key } });
        const made = await api('characters', { method: 'POST', json: { series_id: seriesId, name } });
        await api(`characters/${encodeURIComponent(made.id)}/assignments`, { method: 'PUT',
          json: { voice: chosen.profile_id, engine: chosen.engine || v.engine || '' } });
        await api('voice-catalog/traits', { method: 'PUT', json: { key: v.key, character: made.name,
          show: showOfSeries(seriesId) || v.show || '', show_name: shows().find(s => s.id === seriesId)?.label || v.show_name || '',
          display_name: v.display_name || made.name } });
        invalidate();
        goVoice(`character:${made.id}`);
      } catch (error) { castStatus.textContent = error.message; }
    };
    root.querySelector('[data-save]').onclick = async () => {
      const body = { key: v.key, color: colourValue(root) };
      root.querySelectorAll('[data-t]').forEach(el => { body[el.dataset.t] = el.value.trim(); });
      const saved = root.querySelector('[data-saved]');
      try {
        await api('voice-catalog/traits', { method: 'PUT', json: body });
        invalidate();
        saved.textContent = 'Saved.';
        renderVoices(key);
      } catch (error) { saved.textContent = error.message; }
    };
  }

  return { renderVoices };
}

// ---- Pieces the character page shares ----

export function colourField(v) {
  return `<div class="review-field voice-color">Colour
    <span class="voice-color-row"><input type="color" class="voice-color-input" aria-label="Character colour" value="${esc(palette(v)[0])}" ${v.color ? 'data-chosen' : ''}>
      <span class="hint" data-color-note>${v.color ? esc(v.color) : 'automatic'}</span>
      <button type="button" class="btn btn-ghost" data-color-auto ${v.color ? '' : 'hidden'}>Automatic</button></span></div>`;
}

export const colourValue = root => {
  const picker = root.querySelector('.voice-color-input');
  return picker?.dataset.chosen ? picker.value : '';
};

export function mountColour(root, v, orb) {
  const picker = root.querySelector('.voice-color-input');
  if (!picker) return;
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
}

export function mountOrb(root, v) {
  const canvas = root.querySelector('.voice-orb');
  if (!canvas) return null;
  const [a, b] = palette(v);
  try { return createOrb(canvas, { colors: [a, b], seed: seedOf(v.key) }); } catch {
    canvas.replaceWith(Object.assign(document.createElement('span'), { className: 'voice-dot voice-dot-xl' }));
    return null;
  }
}

export function usedPanel(used) {
  return `<section class="panel voice-panel" aria-labelledby="voiceUsed">
    <h3 id="voiceUsed">Cast in</h3>
    ${used?.length ? `<table class="table"><thead><tr><th>Title</th><th>Speaker</th><th>Shaping</th></tr></thead><tbody>
      ${used.map(u => `<tr><td>${esc(u.title || u.title_key)}</td><td class="m">${esc(u.label || u.speaker || '')}</td>
        <td class="m">${[u.pitch_semitones ? `${u.pitch_semitones > 0 ? '+' : ''}${u.pitch_semitones} st pitch` : '',
          u.formant_semitones ? `${u.formant_semitones > 0 ? '+' : ''}${u.formant_semitones} st formant` : ''].filter(Boolean).join(' · ') || '—'}</td></tr>`).join('')}
      </tbody></table>` : '<p class="hint">Not used in any saved dub yet.</p>'}
  </section>`;
}
