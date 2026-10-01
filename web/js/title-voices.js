import { api } from './api.js';
import { escapeHtml as esc } from './dom.js';
import { lighten } from './voices.js';

// A show's characters across every episode Doblarr has a script for: how much
// each one talks (the first thing that says whose voice matters), how they
// talk (quiet / calm / intense, from the original actor's level), their most
// intense lines (the material an energetic voice is trained on), and the
// voice they have.

const BANDS = [['quiet', 'quiet'], ['calm', 'calm'], ['intense', 'intense'], ['unmeasured', 'not measured']];

function clock(seconds) {
  const s = Math.round(seconds);
  return s >= 60 ? `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s` : `${s}s`;
}

function openVoice(event, key) {
  event.preventDefault();
  history.pushState({}, '', `/voices/${encodeURIComponent(key)}`);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export async function renderShowVoices(box, item) {
  box.innerHTML = '<p class="hint">Reading the scripts of this show’s episodes…</p>';
  let data;
  try { data = await api(`series/${item.tvdb_id}/voices`); } catch (error) {
    box.innerHTML = `<p class="hint">${esc(error.message)}</p>`;
    return;
  }
  if (!box.isConnected) return;
  if (!data.speakers.length) {
    box.innerHTML = `<p class="hint">No episode of ${esc(data.title)} has been run yet, so nobody has been heard.
      Dub or audition an episode and its characters appear here with how much each one talks.</p>`;
    return;
  }
  const lead = data.speakers[0].share || 1;
  box.innerHTML = `
    <p class="hint">From ${data.analysed.length} of ${data.episode_count} episode${data.episode_count === 1 ? '' : 's'}
      (${data.analysed.map(e => esc(e.label)).join(', ')}) · ${clock(data.total_seconds)} of dialogue.
      ${esc(data.note)}</p>
    <div class="cast-share" role="table" aria-label="Characters by share of dialogue">
      ${data.speakers.map(r => `
        <div class="cast-share-row" role="row">
          <div class="cast-share-who" role="cell">
            <strong>${r.voice?.color ? `<span class="voice-dot" style="background:radial-gradient(circle at 35% 30%, #fff 0%, ${esc(lighten(r.voice.color))} 40%, ${esc(r.voice.color)} 100%)"></span>` : ''}${esc(r.voice?.name || r.label || r.speaker)}</strong>
            <span class="hint m">${esc(r.speaker)} · ${r.lines} line${r.lines === 1 ? '' : 's'} · ${r.episodes.length} ep</span>
          </div>
          <div class="cast-share-bar" role="cell" aria-label="${(r.share * 100).toFixed(1)}% of dialogue">
            <span class="cast-share-fill" style="width:${Math.max(2, (r.share / lead) * 100).toFixed(1)}%${r.voice?.color ? `;background:${esc(r.voice.color)}` : ''}"></span>
            <span class="cast-share-pct m">${(r.share * 100).toFixed(1)}%</span>
            <span class="hint m">${clock(r.seconds)}</span>
          </div>
          <div class="cast-bands" role="cell">${BANDS.filter(([k]) => r.bands[k] > 0).map(([k, label]) =>
            `<span class="cast-band cast-band-${k}" style="flex:${r.bands[k]}" title="${label}: ${Math.round(r.bands[k] * 100)}%">${r.bands[k] >= 0.12 ? label : ''}</span>`).join('')}</div>
          <div class="cast-share-voice" role="cell">${r.voice
            ? `<a href="/voices/${encodeURIComponent(r.voice.key)}" data-voice="${esc(r.voice.key)}">${esc(r.voice.name || 'Open voice')}</a>`
            : '<span class="hint">no voice yet</span>'}</div>
          ${r.highlights.length ? `<details class="cast-highlights"><summary class="hint">${r.highlights.length} intense line${r.highlights.length === 1 ? '' : 's'} to train on</summary>
            <ul>${r.highlights.map(h => `<li><span class="m">${esc(h.episode_label)} ${clock(h.start)} · +${h.relative_db} dB</span> ${esc(h.text)}</li>`).join('')}</ul></details>` : ''}
        </div>`).join('')}
    </div>`;
  box.querySelectorAll('[data-voice]').forEach(a => a.onclick = e => openVoice(e, a.dataset.voice));
}
