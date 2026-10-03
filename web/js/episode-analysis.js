import { api, apiUrl } from './api.js';
import { escapeHtml as esc, safeGet } from './dom.js';
import { openMediaPlayer } from './media-player.js';
import { characterPicker } from './character-picker.js';
import { mountEvidence, mountSelection, weak, whyText } from './episode-evidence.js';
import { mountTerms, termsSection } from './episode-terms.js';

// One episode broken down line by line: the voices found in it (with how much
// each talks, and who they are once picked from the show's cast), then every
// line with its speaker, both languages, how it was performed and a way to
// watch it. The analysis is a queued run; this page starts it and follows it.
// Unnamed voices show the named characters they sound like (voice tags, kept
// for the show), and the lines can be grouped again with other voice models
// and the episode's dub tracks in seconds.

const BANDS = { quiet: 'quiet', calm: 'calm', intense: 'intense', unmeasured: '—' };
// The episode's parts and a line's role, from the subtitle track's styles
// (doblarr/subtitle_roles.py).
const PARTS = { 'cold-open': 'Cold open', opening: 'Opening', episode: 'Episode', ending: 'Ending',
  preview: 'Preview', extra: 'Extra', song: 'Song' };
const ROLES = { inner: 'voice-over', preview: 'preview', narration: 'narrator', flashback: 'flashback', extra: 'extra' };
const ROLE_HELP = { inner: 'In italics in the subtitles: a thought, a flashback or a voice from off screen',
  preview: 'The narrated preview of the next episode', narration: 'Narration over the picture',
  flashback: 'A line from a flashback', extra: 'A bonus segment after the episode (omake)' };
const PALETTE = ['#F08A24', '#5B8DEF', '#E0567A', '#3BAA7C', '#9B6CD6', '#E8B33A', '#4FB6C9', '#B5674D', '#7A8F2E', '#D46FC4', '#2F6F8F', '#C7432B', '#6E7BD9', '#8C6B3F'];
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

export function frameUrl(path, t) {
  return withKey(apiUrl(`analysis/frame?path=${encodeURIComponent(path)}&t=${t.toFixed(2)}`));
}

const SCREEN_NOTE = { 'onscreen-speaking': 'a face on screen is talking', 'onscreen-silent': 'a face on screen, not talking',
  offscreen: 'nobody on screen' };

const totalTalk = data => data.lines.reduce((t, l) => t + l.end - l.start, 0);

// The episode's cast: voice groups given the same name are one character
// (with each group kept, so a wrong join is visible); unnamed groups stand
// alone. Most talk first.
export function castOf(data) {
  const byKey = new Map();
  for (const l of data.lines) {
    const key = data.names[l.speaker] || l.speaker;
    if (!byKey.has(key)) byKey.set(key, { key, named: Boolean(data.names[l.speaker]), groups: new Map() });
    const groups = byKey.get(key).groups;
    if (!groups.has(l.speaker)) groups.set(l.speaker, { label: l.speaker, lines: 0, seconds: 0, list: [] });
    const g = groups.get(l.speaker);
    g.lines += 1; g.seconds += l.end - l.start; g.list.push(l);
  }
  return [...byKey.values()].map(c => {
    const groups = [...c.groups.values()].sort((a, b) => b.seconds - a.seconds);
    const all = groups.flatMap(g => g.list);
    // A line worth reading: the longest of the middle-length ones, not a grunt.
    const sample = [...all].filter(l => l.text.length >= 12).sort((a, b) => (b.end - b.start) - (a.end - a.start))[0];
    return { key: c.key, named: c.named, groups, labels: groups.map(g => g.label),
      lines: all.length, seconds: groups.reduce((t, g) => t + g.seconds, 0), sample };
  }).sort((a, b) => b.seconds - a.seconds);
}

// Which lines to show as pictures: a face talking on screen first, then a
// face on screen, then the longest; never two from the same moment.
export function pickFrames(lines, screen = {}, count = 5) {
  const score = l => ({ 'onscreen-speaking': 3, 'onscreen-silent': 1 }[screen[l.cue]] || 0)
    + Math.min(2, l.end - l.start) / 2;
  const picked = [];
  for (const l of [...lines].sort((a, b) => score(b) - score(a))) {
    if (picked.length >= count) break;
    if (picked.every(p => Math.abs(p.start - l.start) > 12)) picked.push(l);
  }
  return picked.sort((a, b) => a.start - b.start);
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
  let speakerFilter = '', bandFilter = '', roleFilter = '', timer = null, tracks = null, chosen = {};
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
    const [models, found, visual, voices] = await Promise.all([voiceModels(), episodeTracks().catch(() => null),
      api(`analysis/visual?path=${encodeURIComponent(path)}`).catch(() => null),
      api('voice-catalog').then(r => r.voices || []).catch(() => [])]);
    // The colour a person chose for a character on its voice, kept here too.
    chosen = {};
    voices.filter(v => v.color && v.show === `tvdb-${tvdb}`).forEach(v => {
      [v.character, v.display_name].filter(Boolean).forEach(n => { chosen[n.toLowerCase()] = v.color; });
    });
    draw(data, models, found, visual);
  }

  function say(text) {
    const status = box.querySelector('[data-status]');
    if (status) status.textContent = text;
  }

  async function saveNames(data, names, message, keep = []) {
    try {
      await api('analysis/names', { method: 'PUT', json: { path, names, keep } });
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

  // Every line of the given voice groups, back to back, from `fromLine`.
  function watch(data, found, labels, fromLine, colour) {
    if (!found?.tracks?.length) { say('The episode’s video is not reachable from here, so only the dialogue can be heard.'); return; }
    const name = data.names[labels[0]] || labels[0];
    const lines = data.lines.filter(l => labels.includes(l.speaker));
    const share = lines.reduce((t, l) => t + l.end - l.start, 0) / Math.max(1, totalTalk(data));
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
      onClose: () => { if (changed) load().then(() => say('Moved lines are saved and tagged for the show; the cast above includes them.')); },
    });
  }

  function draw(data, models = [], found = null, visual = null) {
    const cast = castOf(data);
    const colour = {};
    const taken = new Set(Object.values(chosen).map(c => c.toLowerCase()));
    const free = PALETTE.filter(c => !taken.has(c.toLowerCase()));
    let next = 0;
    cast.forEach(c => { colour[c.key] = (c.named && chosen[c.key.toLowerCase()]) || free[next++ % free.length]; });
    const keyOf = label => data.names[label] || label;
    const tint = label => colour[keyOf(label)] || '#999';
    const screen = Object.fromEntries((visual?.associations || []).map(a => [a.cue, a.screen]));
    const total = totalTalk(data);
    const lead = Math.max(...cast.map(c => c.seconds), 1);
    const visible = data.lines.filter(l => (!speakerFilter || keyOf(l.speaker) === speakerFilter)
      && (!bandFilter || l.band === bandFilter) && (!roleFilter || (l.role || 'dialogue') === roleFilter));
    const languages = [data.languages.text, data.languages.original_text ? data.languages.original : '']
      .filter(Boolean).map(l => l.toUpperCase()).join(' + ');
    const dubs = (found?.tracks || []).filter(t => t.stream !== found.default);
    const heardDubs = new Set(data.grouped_tracks || []);
    const named = cast.filter(c => c.named);
    const joined = named.filter(c => c.labels.length > 1);
    const length = Math.max(...data.lines.map(l => l.end), ...(data.structure || []).map(p => p.end), 1);
    const frames = (labels, count) => pickFrames(data.lines.filter(l => labels.includes(l.speaker)), screen, count);
    // What the lines say about one voice group, and a warning when its name disagrees.
    const sameName = (a, b) => {
      const row = (data.cast || []).find(r => fold(r.name) === fold(a));
      return [a, ...(row?.aliases || [])].some(n => fold(n) === fold(b));
    };
    const clue = label => {
      const said = data.dialogue?.[label] || { answers: [], calls: [], suggests: '' };
      const auto = data.named_by?.[label];
      if (!auto && !said.answers.length && !said.calls.length && !data.reader?.voices?.[label]) return '';
      const name = data.names[label] || '';
      const parts = [said.answers.length ? `answers to ${said.answers.slice(0, 2).map(a => `“${esc(a.name)}” ${a.count}×`).join(', ')}` : '',
        said.calls.length ? `calls ${said.calls.slice(0, 3).map(a => esc(a.name)).join(', ')}` : ''].filter(Boolean);
      const clash = said.suggests && !(name && sameName(name, said.suggests));
      const read = data.reader?.voices?.[label];
      const reader = read ? `<p class="cast-clue" title="Read from the script by ${esc(data.reader.model || 'a model')}">The script reader says <strong>${esc(read.leading)}</strong> (${Math.round(read.share * 100)}% of its lines)${name && !sameName(name, read.leading) ? ', not the name it has' : ''}.</p>` : '';
      if (auto) {
        const how = auto.kind === 'voice-memory'
          ? `Recognised from earlier episodes: sounds like ${esc(name)} (${Math.round(auto.similarity * 100)}%, ${auto.episodes} episode${auto.episodes === 1 ? '' : 's'} heard)`
          : `Named by the dialogue: it answers when ${esc(name)} is called (${auto.answers}×)`;
        return `<p class="cast-clue cast-clue-auto">${how}${auto.replaced ? `, was ${esc(auto.replaced)}` : ''}.
          <button type="button" class="btn btn-ghost" data-undo-dialogue="${esc(label)}" data-was="${esc(auto.replaced || '')}">${auto.replaced ? `Keep ${esc(auto.replaced)}` : 'Undo'}</button></p>
          ${parts.length ? `<p class="cast-clue">In the dialogue: ${parts.join(' · ')}</p>` : ''}${reader}`;
      }
      return `${reader}<p class="cast-clue" title="A line that calls a name is spoken to that person; the next line in another voice is usually theirs.">In the dialogue: ${parts.join(' · ')}</p>
        ${clash ? `<p class="cast-clue-warn">${name ? `Named ${esc(name)}, but the` : 'The'} dialogue says this is <strong>${esc(said.suggests)}</strong>: it answers when ${esc(said.suggests)} is called (${said.answers[0].count}×).
          <button type="button" class="btn btn-ghost" data-suggest="${esc(label)}" data-suggest-name="${esc(said.suggests)}">Name it ${esc(said.suggests)}</button></p>` : ''}`;
    };
    const strip = (labels, count, colourOf) => `<div class="cast-frames">${frames(labels, count).map(l => `
      <button type="button" class="cast-frame" data-watch="${esc(labels.join('|'))}" data-watch-line="${l.index}"
        title="${clock(l.start)} · ${esc(l.text)}${screen[l.cue] ? ` · ${esc(SCREEN_NOTE[screen[l.cue]] || '')}` : ''}" style="--tint:${colourOf}">
        <img src="${frameUrl(path, (l.start + l.end) / 2)}" alt="The picture at ${clock(l.start)}" width="160" height="90" decoding="async">
        <span class="cast-frame-time m">${clock(l.start)}</span></button>`).join('')}</div>`;
    box.innerHTML = `
      <div class="analysis-head">
        <div><h3>Analysis</h3>
          <p class="hint">${data.lines.length} lines · ${clock(total)} of dialogue in ${clock(length)} · ${esc(languages)}</p></div>
        <button type="button" class="btn btn-ghost" data-analyze>Analyze again</button>
      </div>
      <p class="analysis-tally">
        <strong>${cast.length}</strong> ${cast.length === 1 ? 'character' : 'characters'} heard ·
        <strong>${named.length}</strong> named · <strong>${cast.length - named.length}</strong> to name${joined.length
          ? ` · <strong>${joined.length}</strong> joined from several voices, check their pictures` : ''}${Object.keys(ROLES).filter(r => (data.roles || {})[r]).map(r => ` · <strong>${data.roles[r]}</strong> ${ROLES[r]}`).join('')}</p>
      <p class="hint" role="status" data-status></p>
      <div class="analysis-timeline" role="img" aria-label="Who talks when, across the episode">
        ${data.lines.map(l => `<span class="analysis-tick" data-watch="${esc(cast.find(c => c.key === keyOf(l.speaker))?.labels.join('|') || l.speaker)}" data-watch-line="${l.index}"
          style="left:${(l.start / length * 100).toFixed(3)}%;width:${Math.max(0.12, (l.end - l.start) / length * 100).toFixed(3)}%;background:${tint(l.speaker)}"
          title="${clock(l.start)} · ${esc(keyOf(l.speaker))}: ${esc(l.text)}"></span>`).join('')}
        ${Array.from({ length: Math.floor(length / 300) }, (_, i) => `<span class="analysis-minute m" style="left:${((i + 1) * 300 / length * 100).toFixed(2)}%">${(i + 1) * 5}:00</span>`).join('')}
      </div>
      ${(data.structure || []).length ? `<div class="analysis-parts" aria-label="Parts of the episode">${data.structure.map(p => `<span class="analysis-part part-${esc(p.kind)}"
        style="left:${(p.start / length * 100).toFixed(3)}%;width:${Math.max(0.4, (p.end - p.start) / length * 100).toFixed(3)}%"
        title="${esc(PARTS[p.kind] || p.kind)} · ${clock(p.start)}–${clock(p.end)}">${esc(PARTS[p.kind] || p.kind)}</span>`).join('')}</div>` : ''}
      ${(data.on_screen || []).length ? `<details class="analysis-onscreen">
        <summary>Text on screen <span class="hint">${data.on_screen.length} · ${data.on_screen.filter(o => o.from === 'subtitles').slice(0, 3).map(o => esc(o.text)).join(' · ')}</span></summary>
        <div class="analysis-onscreen-list">${data.on_screen.map(o => {
          const l = data.lines.find(x => x.cue === o.cue);
          return `<button type="button" class="analysis-suggest${o.from === 'picture' ? ' analysis-suggest-alt' : ''}" ${l ? `data-watch="${esc(l.speaker)}" data-watch-line="${l.index}"` : 'disabled'}
            title="${o.from === 'picture' ? 'Read from the picture by the vision model' : `From the subtitles: ${o.kind === 'title' ? 'a title card' : 'a sign'}`}">${esc(o.text)} <span class="m">${clock(o.at)}</span></button>`;
        }).join('')}</div>
        <p class="hint">Signs and title cards come from the subtitle track, already translated. Dimmed ones were read from the picture.</p>
      </details>` : ''}
      ${termsSection(data)}
      ${(data.doubts || []).length ? `<section class="asks" aria-label="Questions about the voices">
        <h4>Who says this? <span class="hint">${data.doubts.length} question${data.doubts.length === 1 ? '' : 's'} · each answer is kept for the show and teaches the next episodes</span></h4>
        <div class="asks-list">${data.doubts.map((q, n) => `<article class="ask" data-ask="${n}" style="--tint:${tint(q.voice)}">
          <button type="button" class="cast-frame ask-frame" data-watch="${esc(q.voice)}" data-watch-line="${q.line.index}" title="Watch this line">
            <img src="${frameUrl(path, (q.line.start + q.line.end) / 2)}" alt="The picture at ${clock(q.line.start)}" width="160" height="90" decoding="async">
            <span class="cast-frame-time m">${clock(q.line.start)}</span></button>
          <div class="ask-body">
            <p class="ask-q">${q.kind === 'voice' ? `Who is this voice? <span class="hint">${q.lines} lines, unnamed</span>`
              : `Who says this line? <span class="hint">filed under ${esc(q.now || q.voice)}</span>`}</p>
            <p class="ask-line">“${esc(q.line.text)}”${q.line.original_text ? ` <span class="hint">${esc(q.line.original_text)}</span>` : ''}</p>
            ${q.kind === 'line' ? `<p class="hint ask-why">${q.reasons.map(esc).join(' · ')}</p>` : ''}
            <div class="ask-answers">
              ${q.kind === 'voice' ? q.hints.map(h => `<button type="button" class="analysis-suggest" data-ask-name="${esc(h.name)}" title="${esc(h.why)}">${esc(h.name)}</button>`).join('')
                : `${q.now ? `<button type="button" class="analysis-suggest" data-ask-name="${esc(q.now)}">${esc(q.now)} is right</button>` : ''}
                   ${q.options.filter(o => o !== q.now).map(o => `<button type="button" class="analysis-suggest analysis-suggest-alt" data-ask-name="${esc(o)}">${esc(o)}</button>`).join('')}`}
              <span data-ask-picker></span>
              <button type="button" class="btn btn-ghost ask-skip" data-ask-skip>Not sure</button>
            </div>
          </div></article>`).join('')}</div>
      </section>` : ''}
      <section class="cast-grid" aria-label="Who speaks in this episode">
        ${cast.map(c => {
          const multi = c.labels.length > 1;
          return `<article class="cast-card${c.named ? '' : ' cast-card-unnamed'}" style="--tint:${colour[c.key]}">
            <header class="cast-card-head">
              <span class="voice-dot" style="background:${colour[c.key]}"></span>
              <span class="cast-card-name" data-picker="${esc(c.labels.join('|'))}"></span>
              <span class="cast-card-stats"><span class="m">${c.lines}</span> lines · <span class="m">${clock(c.seconds)}</span> · <span class="m">${(c.seconds / total * 100).toFixed(1)}%</span></span>
              <button type="button" class="btn btn-ghost cast-card-watch" data-watch="${esc(c.labels.join('|'))}" aria-label="Watch ${esc(c.key)}">Watch</button>
            </header>
            <span class="cast-card-share"><span style="width:${(c.seconds / lead * 100).toFixed(1)}%"></span></span>
            ${!c.named && (data.suggestions?.[c.labels[0]] || []).length ? `<p class="cast-card-suggest">${(data.suggestions[c.labels[0]] || []).slice(0, 2).map((s, i) => `<button type="button" class="analysis-suggest${i ? ' analysis-suggest-alt' : ''}" data-suggest="${esc(c.labels[0])}" data-suggest-name="${esc(s.name)}" title="Of the named voices, the closest is ${esc(s.name)} (tagged on ${s.lines} line${s.lines === 1 ? '' : 's'}${s.episodes > 1 ? ` across ${s.episodes} episodes` : ''})${s.margin != null && s.margin < 0.05 ? ', a weak lead' : ''}. Check the pictures before you accept it.">${i ? '' : 'Sounds closest to '}${esc(s.name)} <span class="m">${Math.round(s.similarity * 100)}%</span></button>`).join('')}</p>` : ''}
            ${multi ? `<p class="cast-card-warn">Heard as ${c.labels.length} separate voices. If one row of pictures shows someone else, rename that row.</p>
              ${c.groups.map(g => `<div class="cast-group">
                <div class="cast-group-head"><span class="hint"><span class="m">${g.lines}</span> lines · <span class="m">${clock(g.seconds)}</span></span>
                  <span data-picker="${esc(g.label)}" data-group-picker></span></div>
                ${clue(g.label)}${strip([g.label], 4, colour[c.key])}</div>`).join('')}`
              : `${clue(c.labels[0])}${strip(c.labels, 5, colour[c.key])}`}
            ${c.sample ? `<p class="cast-card-line">“${esc(c.sample.text)}”${c.sample.original_text ? ` <span class="hint">${esc(c.sample.original_text)}</span>` : ''}</p>` : ''}
          </article>`;
        }).join('')}
      </section>
      <p class="hint">Pictures are taken from the middle of each voice’s lines, preferring moments a face is on screen and moving its mouth. Click one to watch from that line. Pick each voice from the show’s cast, or add a new character; two voices given the same character are joined.</p>
      <div class="analysis-filters">
        <label>Who <select class="input" data-filter-speaker><option value="">Everyone</option>
          ${cast.map(c => `<option value="${esc(c.key)}" ${c.key === speakerFilter ? 'selected' : ''}>${esc(c.key)}</option>`).join('')}</select></label>
        <label>How <select class="input" data-filter-band><option value="">Every line</option>
          ${['intense', 'calm', 'quiet'].map(b => `<option value="${b}" ${b === bandFilter ? 'selected' : ''}>${b}${b === 'intense' ? ' (training lines)' : ''}</option>`).join('')}</select></label>
        ${Object.values(data.roles || {}).some((n, i) => i && n) ? `<label>Kind <select class="input" data-filter-role><option value="">Every kind</option>
          ${['dialogue', ...Object.keys(ROLES)].filter(r => (data.roles || {})[r]).map(r => `<option value="${r}" ${r === roleFilter ? 'selected' : ''}>${r === 'dialogue' ? 'dialogue' : ROLES[r]} (${data.roles[r]})</option>`).join('')}</select></label>` : ''}
        <span class="hint">${visible.length} line${visible.length === 1 ? '' : 's'}</span>
      </div>
      <div class="analysis-selection" data-selection hidden><span class="hint" data-count></span><span data-selection-picker></span></div>
      <div class="analysis-lines" role="table" aria-label="Every line of the episode">
        ${visible.map(l => `<div class="analysis-line" role="row">
          <span class="m" role="cell"><input type="checkbox" data-select-line="${esc(l.cue)}" aria-label="Select line at ${clock(l.start)}"> ${clock(l.start)}</span>
          <span role="cell"><span class="analysis-who" style="border-color:${tint(l.speaker)}" title="${esc(whyText(l.why))}">${esc(keyOf(l.speaker))}</span>${l.uncertain || weak(l.why) ? `<span class="hint" title="${esc(whyText(l.why) || 'Too short to be sure of the voice')}">?</span>` : ''}${l.locked ? `<button type="button" class="analysis-lock" data-unlock="${esc(l.cue)}" title="You assigned this line; it stays with this character when voices are regrouped. Click to let the grouping decide again.">assigned</button>` : ''}
            <span class="hint analysis-screen" data-screen-cue="${esc(l.cue)}"></span></span>
          <span role="cell" class="analysis-text">${l.role && l.role !== 'dialogue' ? `<span class="role role-${esc(l.role)}" title="${esc(ROLE_HELP[l.role] || '')}">${esc(ROLES[l.role] || l.role)}</span>` : ''}${esc(l.text)}${l.original_text ? `<span class="analysis-original">${esc(l.original_text)}</span>` : ''}</span>
          <span role="cell"><span class="cast-band cast-band-${l.band} analysis-band">${BANDS[l.band]}</span>${l.emotion ? `<span class="emo emo-${esc(l.emotion.confidence)}" title="${esc([l.emotion.expression && `face: ${l.emotion.expression}`, l.emotion.voice && `voice: ${l.emotion.voice}`, l.emotion.agree === true ? 'face and voice agree' : l.emotion.agree === false ? 'the voice disagrees' : '', `read from the ${l.emotion.from}`].filter(Boolean).join(' · '))}">${esc(l.emotion.feeling)}</span>` : ''}</span>
          <span role="cell" class="m hint">${l.pitch_hz ? `${Math.round(l.pitch_hz)} Hz` : ''}${l.movement_st ? ` · ${l.movement_st} st` : ''}${l.features?.quality && l.features.quality !== 'ok' ? `<br><span title="${esc((l.features.reasons || []).join('; '))}">curve ${esc(l.features.quality)}</span>` : ''}</span>
          <span role="cell" class="analysis-play">
            <button type="button" class="btn btn-ghost" data-watch-line="${l.index}" data-watch="${esc(l.speaker)}" title="This line on screen, then the rest of this voice’s lines">Watch</button>
            <button type="button" class="btn btn-ghost" data-play="${l.start},${l.end}" data-track="vocals" title="The separated dialogue only">Voice</button></span>
        </div>`).join('')}
      </div>
      <section class="analysis-behind" aria-label="Behind the analysis">
        <h4>Behind the analysis</h4>
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
        <div data-evidence-top></div>
        <div data-visual></div>
      </section>`;

    const usedBy = {};
    Object.entries(data.names).forEach(([label, name]) => { (usedBy[name] ||= []).push(label); });
    box.querySelectorAll('[data-picker]').forEach(slot => {
      const labels = slot.dataset.picker.split('|');
      const single = labels.length === 1;
      const current = data.names[labels[0]] || '';
      const sharedWith = {};
      Object.entries(usedBy).forEach(([name, others]) => { sharedWith[name] = others.filter(l => !labels.includes(l)); });
      slot.replaceWith(characterPicker({
        label: slot.hasAttribute('data-group-picker') ? `Who this part of ${current} is` : `Character for ${labels.join(', ')}`,
        value: current, placeholder: single && !current ? `Unnamed (${labels[0]})` : labels[0],
        cast: data.cast || [], suggestions: data.suggestions?.[labels[0]] || [], sharedWith,
        onPick: name => {
          const names = { ...data.names };
          labels.forEach(label => { if (name) names[label] = name; else delete names[label]; });
          const joinedWith = sharedWith[name]?.length ? `, joined with ${sharedWith[name].map(l => data.names[l] ? `the other ${name} voice` : l).join(', ')}` : '';
          saveNames(data, names, name ? `${single ? labels[0] : current} is ${name}${joinedWith}. Tagged for the show.`
            : `${labels.join(', ')} has no name now.`);
        },
      }));
    });
    box.querySelector('[data-analyze]').onclick = start;
    mountEvidence(box, data, { path, target, reload: load, say, visual });
    mountSelection(box, data, { path, reload: load, say });
    mountTerms(box, data, { path, reload: load, say });
    const regroupButton = box.querySelector('[data-regroup]');
    if (regroupButton) regroupButton.onclick = () => regroup(models, found);
    // Answers: a voice question names the whole group; a line question assigns
    // that one line (kept even when the voices are regrouped).
    const answer = async (q, name) => {
      if (!name) return;
      if (q.kind === 'voice') {
        await saveNames(data, { ...data.names, [q.voice]: name }, `${q.voice} is ${name}: ${q.lines} lines named, and the show will recognise the voice.`);
        return;
      }
      try {
        await api('analysis/line', { method: 'PUT', json: { path, cue: q.line.cue, character: name } });
        await load();
        say(`“${q.line.text.slice(0, 40)}” is ${name}'s. Kept even if the voices are regrouped.`);
      } catch (error) { say(error.message); }
    };
    box.querySelectorAll('[data-ask]').forEach(card => {
      const q = data.doubts[Number(card.dataset.ask)];
      card.querySelectorAll('[data-ask-name]').forEach(b => b.onclick = () => answer(q, b.dataset.askName));
      card.querySelector('[data-ask-skip]').onclick = () => card.remove();
      card.querySelector('[data-ask-picker]').replaceWith(characterPicker({
        label: q.kind === 'voice' ? `Who is ${q.voice}` : 'Who says this line', value: '',
        placeholder: 'Someone else', cast: data.cast || [], suggestions: [], onPick: name => answer(q, name) }));
    });
    box.querySelectorAll('[data-undo-dialogue]').forEach(b => b.onclick = () => {
      const label = b.dataset.undoDialogue;
      const names = { ...data.names };
      if (b.dataset.was) names[label] = b.dataset.was; else delete names[label];
      saveNames(data, names, b.dataset.was ? `${label} is ${b.dataset.was} again; the dialogue will not rename it.`
        : `${label} has no name again; the dialogue will not rename it.`, [label]);
    });
    box.querySelectorAll('[data-suggest]').forEach(b => b.onclick = () => {
      const label = b.dataset.suggest;
      saveNames(data, { ...data.names, [label]: b.dataset.suggestName },
        `${label} is ${b.dataset.suggestName} now. Watch it to check; pick another name any time.`);
    });
    box.querySelector('[data-filter-speaker]').onchange = e => { speakerFilter = e.target.value; draw(data, models, found, visual); };
    box.querySelector('[data-filter-band]').onchange = e => { bandFilter = e.target.value; draw(data, models, found, visual); };
    box.querySelector('[data-filter-role]')?.addEventListener('change', e => { roleFilter = e.target.value; draw(data, models, found, visual); });
    box.querySelectorAll('[data-play]').forEach(b => b.onclick = () => {
      const [s, e] = b.dataset.play.split(',').map(Number);
      play(path, s, e, b.dataset.track);
    });
    box.querySelectorAll('[data-watch]').forEach(b => b.onclick = () => {
      audio?.pause();
      const labels = b.dataset.watch.split('|');
      watch(data, found, labels, b.dataset.watchLine ? Number(b.dataset.watchLine) : null, tint(labels[0]));
    });
  }

  load();
}
