import { api, apiUrl } from './api.js';
import { escapeHtml as esc, safeGet } from './dom.js';
import { openMediaPlayer } from './media-player.js';
import { characterPicker } from './character-picker.js';
import { mountEvidence, mountSelection, weak, whyText } from './episode-evidence.js';

// One episode broken down line by line: the voices found in it (with how much
// each talks, and who they are once picked from the show's cast), then every
// line with its speaker, both languages, how it was performed and a way to
// watch it. The analysis is a queued run; this page starts it and follows it.
// Unnamed voices show the named characters they sound like (voice tags, kept
// for the show), and the lines can be grouped again with other voice models
// and the episode's dub tracks in seconds.

const BANDS = { quiet: 'quiet', calm: 'calm', intense: 'intense', unmeasured: '—' };
const PALETTE = ['#F08A24', '#5B8DEF', '#E0567A', '#3BAA7C', '#9B6CD6', '#E8B33A', '#4FB6C9', '#B5674D'];
const PAD_BEFORE = 0.35, PAD_AFTER = 0.45;      // a breath of context around a watched line
let audio = null;
let modelsCache = null;

async function voiceModels() {
  if (!modelsCache) modelsCache = api('voice-models').then(r => r.models).catch(() => []);
  return modelsCache;
}

const clock = s => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`;

function withKey(url) {
  const key = safeGet('doblarr_api_key', '');
  return url + (key ? `&api_key=${encodeURIComponent(key)}` : '');
}

function clipUrl(path, start, end, track) {
  return withKey(apiUrl(`analysis/clip?path=${encodeURIComponent(path)}&start=${start.toFixed(2)}&end=${end.toFixed(2)}&track=${track}`));
}

export function videoUrl(path, start, end, stream) {
  return withKey(apiUrl(`analysis/video?path=${encodeURIComponent(path)}&start=${start.toFixed(2)}&end=${end.toFixed(2)}`
    + (stream === null || stream === undefined ? '' : `&audio=${stream}`)));
}

function play(path, start, end, track) {
  audio?.pause();
  audio = new Audio(clipUrl(path, start, end, track));
  audio.play().catch(() => {});
}

export function trackLabel(track) {
  let language = track.lang;
  try { language = new Intl.DisplayNames(['en'], { type: 'language' }).of(track.lang) || track.lang; } catch { /* keep the code */ }
  // "Spanish · Latino" and "Spanish · Castellano" are two tracks, not one.
  const title = (track.title || '').replace(/\[[^\]]*\]/g, '').replace(/\b\d\.\d\b|FLAC|AAC|AC3|DTS|-/gi, '').replace(/\s+/g, ' ').trim();
  return title && fold(title) !== fold(language) && !/^(eng|jpn|spa|english|japanese|spanish)$/i.test(title)
    ? `${language} · ${title}` : language;
}
const fold = s => String(s || '').toLowerCase();

export async function renderEpisodeAnalysis(box, item, { target = 'es' } = {}) {
  const path = item.path;
  const tvdb = item.parent?.tvdb_id || item.tvdb_id;
  let speakerFilter = '', bandFilter = '', timer = null, tracks = null;
  box.innerHTML = '<p class="hint">Reading this episode’s analysis…</p>';

  async function start() {
    const status = box.querySelector('[data-status]');
    box.querySelectorAll('[data-analyze]').forEach(b => { b.disabled = true; });
    try {
      const result = await api(`series/${tvdb}/queue`, { method: 'POST', json: {
        episode_ids: [item.episode_id], target_lang: target, kind: 'analyze', missing_only: false } });
      if (!result.queued.length) throw new Error(result.skipped[0]?.reason || 'Not queued');
      if (status) status.textContent = 'Queued. Separating the dialogue comes first; it is the long part.';
      follow();
    } catch (error) {
      if (status) status.textContent = error.message;
      box.querySelectorAll('[data-analyze]').forEach(b => { b.disabled = false; });
    }
  }

  function follow() {
    clearTimeout(timer);
    timer = setTimeout(load, 4000);
  }

  async function episodeTracks() {
    if (!tracks) {
      tracks = api(`analysis/tracks?path=${encodeURIComponent(path)}`)
        .catch(error => { tracks = null; throw error; });
    }
    return tracks;
  }

  async function load() {
    if (!box.isConnected) return;
    let data;
    try { data = await api(`analysis?path=${encodeURIComponent(path)}`); } catch (error) {
      box.innerHTML = `<p class="hint">${esc(error.message)}</p>`; return;
    }
    if (!box.isConnected) return;
    if (data.job) {
      box.innerHTML = `<div class="analysis-empty">
        <div class="analysis-pulse" aria-hidden="true"></div>
        <h3>Analysing this episode</h3>
        <p class="hint">${esc(data.job.status)}${data.job.stage ? ` · ${esc(data.job.stage)}` : ''}${data.job.progress ? ` · ${data.job.progress}%` : ''}</p>
        <p class="hint">Separating the dialogue, cutting every line, grouping the voices and measuring how each line was said. Nothing is translated or dubbed.</p></div>`;
      follow();
      return;
    }
    if (!data.analysed) {
      box.innerHTML = `<div class="analysis-empty">
        <h3>Break this episode down</h3>
        <p class="hint">Every line: who says it, when, what in both languages, and how (quiet, calm or intense, pitch and how much it moves). The voices it finds can be named once and become the show’s cast.</p>
        <button type="button" class="btn btn-primary analysis-go" data-analyze>Analyze episode</button>
        <p class="hint" role="status" data-status></p></div>`;
      box.querySelector('[data-analyze]').onclick = start;
      return;
    }
    const [models, found] = await Promise.all([voiceModels(), episodeTracks().catch(() => null)]);
    draw(data, models, found);
  }

  function say(text) {
    const status = box.querySelector('[data-status]');
    if (status) status.textContent = text;
  }

  async function saveNames(data, names, message) {
    try {
      await api('analysis/names', { method: 'PUT', json: { path, names } });
      await load();
      say(message);
    } catch (error) { say(error.message); }
  }

  async function regroup(models, found) {
    const button = box.querySelector('[data-regroup]');
    const picked = [...box.querySelectorAll('[data-model]:checked')].map(i => i.value);
    if (!picked.length) { say('Pick at least one voice model.'); return; }
    const dubs = found ? [...box.querySelectorAll('[data-dub]:checked')].map(i => Number(i.value)) : null;
    button.disabled = true;
    say(`Grouping the voices with ${picked.map(id => models.find(m => m.id === id)?.name || id).join(' + ')}`
      + `${dubs?.length ? `, hearing ${dubs.length} dub track${dubs.length === 1 ? '' : 's'} too` : ''}… (the first use of a model downloads it)`);
    try {
      const result = await api('analysis/regroup', { method: 'POST', json: { path, models: picked, tracks: dubs } });
      modelsCache = null;
      const kept = Object.keys(result.names).length;
      await load();
      say(`${result.voices} voices found with ${result.model}${result.tracks?.length ? ` and ${result.tracks.length} dub track${result.tracks.length === 1 ? '' : 's'}` : ''}${kept ? ` · ${kept} kept their names` : ''}.`);
    } catch (error) {
      say(error.message);
      button.disabled = false;
    }
  }

  function watch(data, found, label, fromLine, colour) {
    if (!found?.tracks?.length) { say('The episode’s video is not reachable from here, so only the dialogue can be heard.'); return; }
    const name = data.names[label] || label;
    const lines = data.lines.filter(l => l.speaker === label);
    const share = data.speakers.find(s => s.speaker === name)?.share || 0;
    const clips = lines.map(l => {
      const start = Math.max(0, l.start - PAD_BEFORE);
      const end = Math.min(start + 29.5, l.end + PAD_AFTER);
      return { start, end, label: clock(l.start), text: l.text, detail: l.original_text || '',
        cue: l.cue, tag: l.moved ? 'moved here' : '', url: stream => videoUrl(path, start, end, stream) };
    });
    let changed = false;
    const lineMenu = (clip, i, { close, update }) => {
      const box = document.createElement('div');
      box.className = 'line-menu';
      box.innerHTML = `<p class="line-menu-title">Who says “${esc(clip.text.slice(0, 60))}${clip.text.length > 60 ? '…' : ''}”?</p>
        <p class="hint line-menu-hint">The grouping filed it under ${esc(name)}. Pick who it really is, or add them.</p>`;
      const moveTo = async character => {
        try {
          const result = await api('analysis/line', { method: 'PUT', json: { path, cue: clip.cue, character } });
          changed = true;
          update(i, { tag: character ? `→ ${character}` : `→ new voice ${result.speaker}` });
          close();
        } catch (error) { say(error.message); close(); }
      };
      const picker = characterPicker({
        label: 'Who says this line', value: '', placeholder: 'Pick or type a name',
        cast: (data.cast || []).filter(c => c.name !== name), suggestions: [], onPick: name => name && moveTo(name),
      });
      box.append(picker);
      const unnamed = document.createElement('button');
      unnamed.type = 'button';
      unnamed.className = 'btn btn-ghost line-menu-new';
      unnamed.textContent = 'A new voice, name it later';
      unnamed.onclick = () => moveTo('');
      box.append(unnamed);
      setTimeout(() => picker.querySelector('input')?.focus(), 0);
      return box;
    };
    openMediaPlayer({
      title: name, colour,
      subtitle: `${lines.length} line${lines.length === 1 ? '' : 's'} · ${(share * 100).toFixed(1)}% of this episode’s dialogue · only their lines, back to back`,
      clips, tracks: found.tracks.map(t => ({ key: t.stream, label: trackLabel(t) })), track: found.default,
      startAt: Math.max(0, lines.findIndex(l => l.index === fromLine)),
      menu: lineMenu,
      onClose: () => { if (changed) load().then(() => say('Moved lines are saved and tagged for the show; the shares below include them.')); },
    });
  }

  function draw(data, models = [], found = null) {
    const colour = {};
    data.speakers.forEach((s, i) => { colour[s.speaker] = PALETTE[i % PALETTE.length]; });
    const tint = label => colour[data.names[label] || label] || colour[label] || '#999';
    // Most talk first: the voices worth naming are at the top.
    const heard = {};
    data.lines.forEach(l => { heard[l.speaker] = (heard[l.speaker] || 0) + (l.end - l.start); });
    const groups = Object.keys(heard).sort((a, b) => heard[b] - heard[a]);
    const shareOf = label => data.speakers.find(s => s.speaker === (data.names[label] || label));
    const lead = data.speakers[0]?.share || 1;
    const visible = data.lines.filter(l => (!speakerFilter || l.speaker === speakerFilter)
      && (!bandFilter || l.band === bandFilter));
    const languages = [data.languages.text, data.languages.original_text ? data.languages.original : '']
      .filter(Boolean).map(l => l.toUpperCase()).join(' + ');
    const dubs = (found?.tracks || []).filter(t => t.stream !== found.default);
    const heardDubs = new Set(data.grouped_tracks || []);
    box.innerHTML = `
      <div class="analysis-head">
        <div><h3>Analysis</h3>
          <p class="hint">${data.lines.length} lines · ${groups.length} voices found · ${clock(data.total_seconds)} of dialogue · ${esc(languages)}</p></div>
        <button type="button" class="btn btn-ghost" data-analyze>Analyze again</button>
      </div>
      ${models.length ? `<details class="analysis-models">
        <summary>Voice model · <span class="m">${esc(data.model || 'unknown')}</span>${heardDubs.size ? ` <span class="hint">+ ${heardDubs.size} dub track${heardDubs.size === 1 ? '' : 's'}</span>` : ''}</summary>
        <p class="hint">Which model tells the voices apart. Pick one, or several to combine them. Regrouping reuses the separated dialogue, so it takes seconds; names follow their lines.</p>
        <div class="analysis-model-list">${models.map(m => `<label class="analysis-model">
          <input type="checkbox" data-model value="${esc(m.id)}" ${(data.model || '').split('+').includes(m.id) ? 'checked' : ''}>
          <span><strong>${esc(m.name)}</strong> <span class="hint">${esc(m.family)}${m.size_mb ? ` · ${m.size_mb} MB` : ''}${m.ready ? '' : ' · downloads on first use'}</span>
            <span class="hint analysis-model-note">${esc(m.note)}${m.scores?.recognise ? ` Anime test episode: recognises ${Math.round(m.scores.recognise * 100)}% of lines, groups ${m.scores.group.toFixed(2)}.` : ''}</span></span>
        </label>`).join('')}</div>
        ${dubs.length ? `<p class="hint">Also listen to the dubs: each has its own cast, so voices one language confuses another often keeps apart.</p>
        <div class="analysis-dubs">${dubs.map(t => `<label class="analysis-model"><input type="checkbox" data-dub value="${t.stream}" ${heardDubs.has(t.stream) ? 'checked' : ''}> ${esc(trackLabel(t))}</label>`).join('')}</div>` : ''}
        ${(data.track_evidence || []).length ? `<p class="hint">Dub tracks last time: ${data.track_evidence.map(t => `${esc(trackLabel(t))} ${t.state === 'verified' ? `lined up (offset ${(t.offset ?? 0).toFixed(2)} s)` : `not used: ${esc(t.reason || t.state)}`}`).join('; ')}.</p>` : ''}
        <button type="button" class="btn btn-secondary" data-regroup>Regroup voices</button>
      </details>` : ''}
      <p class="hint" role="status" data-status></p>
      <div data-evidence-top></div>
      <section class="analysis-voices" aria-label="Voices in this episode">
        ${groups.map(label => {
          const share = shareOf(label);
          const lines = data.lines.filter(l => l.speaker === label).length;
          return `<div class="analysis-voice">
            <span class="voice-dot" style="background:${tint(label)}"></span>
            <span class="analysis-naming"><span data-picker="${esc(label)}"></span>
              ${data.names[label] ? '' : (data.suggestions?.[label] || []).slice(0, 2).map((s, i) => `<button type="button" class="analysis-suggest${i ? ' analysis-suggest-alt' : ''}" data-suggest="${esc(label)}" data-suggest-name="${esc(s.name)}" title="Of the named voices, the closest is ${esc(s.name)} (tagged on ${s.lines} line${s.lines === 1 ? '' : 's'}${s.episodes > 1 ? ` across ${s.episodes} episodes` : ''})${s.margin != null ? `, ${Math.round(s.margin * 100)} points ahead of the next${s.margin < 0.05 ? ', a weak lead' : ''}` : ''}. Click to name this voice ${esc(s.name)}.">${i ? '' : 'Closest: '}${esc(s.name)} <span class="m">${Math.round(s.similarity * 100)}%</span></button>`).join('')}</span>
            <span class="cast-share-bar"><span class="cast-share-fill" style="width:${Math.max(3, ((share?.share || 0) / lead) * 100).toFixed(0)}%;background:${tint(label)}"></span>
              <span class="m">${((share?.share || 0) * 100).toFixed(1)}%</span></span>
            <span class="hint m">${lines} line${lines === 1 ? '' : 's'}</span>
            <button type="button" class="btn btn-ghost analysis-watch" data-watch="${esc(label)}" aria-label="Watch ${esc(data.names[label] || label)}">Watch</button>
          </div>`;
        }).join('')}
        <p class="hint">Pick each voice from the show’s cast, or add a new character. Two voices given the same character are joined (someone shouting and calm can be found as two). Named voices are remembered for the show and suggested for the rest.</p>
      </section>
      <div class="analysis-filters">
        <label>Speaker <select class="input" data-filter-speaker><option value="">Everyone</option>
          ${groups.map(g => `<option value="${esc(g)}" ${g === speakerFilter ? 'selected' : ''}>${esc(data.names[g] || g)}</option>`).join('')}</select></label>
        <label>How <select class="input" data-filter-band><option value="">Every line</option>
          ${['intense', 'calm', 'quiet'].map(b => `<option value="${b}" ${b === bandFilter ? 'selected' : ''}>${b}${b === 'intense' ? ' (training lines)' : ''}</option>`).join('')}</select></label>
        <span class="hint">${visible.length} line${visible.length === 1 ? '' : 's'}</span>
      </div>
      <div class="analysis-selection" data-selection hidden><span class="hint" data-count></span><span data-selection-picker></span></div>
      <div class="analysis-lines" role="table" aria-label="Every line of the episode">
        ${visible.map(l => `<div class="analysis-line" role="row">
          <span class="m" role="cell"><input type="checkbox" data-select-line="${esc(l.cue)}" aria-label="Select line at ${clock(l.start)}"> ${clock(l.start)}</span>
          <span role="cell"><span class="analysis-who" style="border-color:${tint(l.speaker)}" title="${esc(whyText(l.why))}">${esc(data.names[l.speaker] || l.speaker)}</span>${l.uncertain || weak(l.why) ? `<span class="hint" title="${esc(whyText(l.why) || 'Too short to be sure of the voice')}">?</span>` : ''}${l.locked ? `<button type="button" class="analysis-lock" data-unlock="${esc(l.cue)}" title="You assigned this line; it stays with this character when voices are regrouped. Click to let the grouping decide again.">assigned</button>` : ''}
            <span class="hint analysis-screen" data-screen-cue="${esc(l.cue)}"></span></span>
          <span role="cell" class="analysis-text">${esc(l.text)}${l.original_text ? `<span class="analysis-original">${esc(l.original_text)}</span>` : ''}</span>
          <span role="cell"><span class="cast-band cast-band-${l.band} analysis-band">${BANDS[l.band]}</span></span>
          <span role="cell" class="m hint">${l.pitch_hz ? `${Math.round(l.pitch_hz)} Hz` : ''}${l.movement_st ? ` · ${l.movement_st} st` : ''}${l.features?.quality && l.features.quality !== 'ok' ? `<br><span title="${esc((l.features.reasons || []).join('; '))}">curve ${esc(l.features.quality)}</span>` : ''}</span>
          <span role="cell" class="analysis-play">
            <button type="button" class="btn btn-ghost" data-watch-line="${l.index}" data-watch="${esc(l.speaker)}" title="This line on screen, then the rest of this voice’s lines">Watch</button>
            <button type="button" class="btn btn-ghost" data-play="${l.start},${l.end}" data-track="vocals" title="The separated dialogue only">Voice</button></span>
        </div>`).join('')}
      </div>
      <div data-visual></div>`;

    const usedBy = {};
    Object.entries(data.names).forEach(([label, name]) => { (usedBy[name] ||= []).push(label); });
    box.querySelectorAll('[data-picker]').forEach(slot => {
      const label = slot.dataset.picker;
      const sharedWith = {};
      Object.entries(usedBy).forEach(([name, labels]) => { sharedWith[name] = labels.filter(l => l !== label); });
      slot.replaceWith(characterPicker({
        label: `Character for ${label}`, value: data.names[label] || '', placeholder: label,
        cast: data.cast || [], suggestions: data.suggestions?.[label] || [], sharedWith,
        onPick: name => {
          const names = { ...data.names };
          if (name) names[label] = name; else delete names[label];
          saveNames(data, names, name ? `${label} is ${name}${sharedWith[name]?.length ? `, joined with ${sharedWith[name].join(', ')}` : ''}. Tagged for the show.` : `${label} has no name now.`);
        },
      }));
    });
    box.querySelector('[data-analyze]').onclick = start;
    mountEvidence(box, data, { path, target, reload: load, say });
    mountSelection(box, data, { path, reload: load, say });
    const regroupButton = box.querySelector('[data-regroup]');
    if (regroupButton) regroupButton.onclick = () => regroup(models, found);
    box.querySelectorAll('[data-suggest]').forEach(b => b.onclick = () => {
      const label = b.dataset.suggest;
      saveNames(data, { ...data.names, [label]: b.dataset.suggestName },
        `${label} is ${b.dataset.suggestName} now. Watch it to check; pick another name any time.`);
    });
    box.querySelector('[data-filter-speaker]').onchange = e => { speakerFilter = e.target.value; draw(data, models, found); };
    box.querySelector('[data-filter-band]').onchange = e => { bandFilter = e.target.value; draw(data, models, found); };
    box.querySelectorAll('[data-play]').forEach(b => b.onclick = () => {
      const [s, e] = b.dataset.play.split(',').map(Number);
      play(path, s, e, b.dataset.track);
    });
    box.querySelectorAll('[data-watch]').forEach(b => b.onclick = () => {
      audio?.pause();
      const label = b.dataset.watch;
      watch(data, found, label, b.dataset.watchLine ? Number(b.dataset.watchLine) : null, tint(label));
    });
  }

  load();
}
