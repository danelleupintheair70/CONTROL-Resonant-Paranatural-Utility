import { api, apiUrl } from './api.js';
import { escapeHtml as esc, safeGet } from './dom.js';
import { primeAudio } from './orb.js';

// What the voices pages share: a voice's colours, hearing a voice, and which
// catalogue voice speaks for which character. A character of a show is the
// one page a person edits; the catalogue voice (a clone or a preset) is what
// it speaks with, found by its casting or, for voices named before casting
// existed, by the same show and name.

const PALETTES = [['#CADCFC', '#A0B9D1'], ['#F6C6A8', '#E8845C'], ['#C9F2D6', '#7FC8A4'],
  ['#E7D1FA', '#B18AE0'], ['#FCE7A8', '#E9B949'], ['#FAD0DA', '#E47A98']];
export const SAMPLE = '¡Esto es una prueba de voz! A ver cómo suena este personaje.';

// The orb ramps black → first → second → white, so the second is the chosen
// colour lifted toward white.
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

export function seedOf(key) {
  let h = 2166136261;
  for (const c of String(key)) h = Math.imul(h ^ c.charCodeAt(0), 16777619) >>> 0;
  return h;
}

export function dotStyle(v) {
  const [a, b] = palette(v);
  return `background: radial-gradient(circle at 35% 30%, #fff 0%, ${a} 38%, ${b} 100%);`;
}

const fold = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();

// "tvdb-81234" (a voice's show) ↔ "show:tvdb:81234" (a character's series).
export const seriesOfShow = show => (/^tvdb-\d+$/.test(show || '') ? `show:tvdb:${show.slice(5)}` : '');
export const showOfSeries = series => (/^show:tvdb:\d+$/.test(series || '') ? `tvdb-${series.split(':')[2]}` : '');

const namesOf = c => new Set([c.name, ...(c.aliases || [])].map(fold));

// The voice a character speaks with: its cast voice first, else a voice
// named for it in the same show.
export function voiceFor(character, catalog) {
  const cast = catalog.find(v => v.profile_id && (character.voices || []).includes(v.profile_id));
  if (cast) return cast;
  const names = namesOf(character);
  return catalog.find(v => seriesOfShow(v.show) === character.series_id
    && (names.has(fold(v.character)) || names.has(fold(v.display_name)))) || null;
}

// The character a voice speaks for, if any.
export function characterFor(voice, characters) {
  return characters.find(c => voice.profile_id && (c.voices || []).includes(voice.profile_id))
    || characters.find(c => seriesOfShow(voice.show) === c.series_id
      && (namesOf(c).has(fold(voice.character)) || namesOf(c).has(fold(voice.display_name))))
    || null;
}

// "Hear it": a sample in this voice, with the orb following the sound.
export function hearPanel(voice) {
  return `<section class="panel voice-panel" aria-labelledby="voiceHear">
    <h3 id="voiceHear">Hear it</h3>
    <div class="voice-preview-row">
      <textarea class="input voice-text" rows="2" maxlength="300" aria-label="Text to speak">${esc(SAMPLE)}</textarea>
      <label class="review-field">Language <input class="input m voice-lang" value="${esc((voice.language || 'es').slice(0, 2))}" maxlength="2" size="3"></label>
      <button type="button" class="btn btn-primary" data-speak>Generate and play</button>
    </div>
    <audio class="voice-audio" controls hidden></audio>
    <p class="hint" role="status" data-hear-status></p>
  </section>`;
}

export function mountHear(root, voice, orb) {
  const button = root.querySelector('[data-speak]');
  if (!button) return;
  const audio = root.querySelector('.voice-audio');
  const status = root.querySelector('[data-hear-status]');
  let version = 0;
  button.onclick = async () => {
    const mine = ++version;
    try { primeAudio(); } catch { /* no Web Audio: the orb just idles */ }
    audio.pause();
    status.textContent = 'Generating…';
    try {
      const made = await api('voice-catalog/preview', { method: 'POST', json: { key: voice.key,
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
}
