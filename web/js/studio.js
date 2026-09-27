import { api } from './api.js';
import { escapeHtml as esc, safeGet, safeSet } from './dom.js';
import { createStudioPlayer } from './studio-player.js';
import { renderOverview } from './studio-overview.js';
import { renderCast } from './studio-cast.js';
import { renderExperiments } from './studio-experiments.js';
import { renderExport } from './studio-export.js';

// The episode studio: one persistent workspace over one episode.
//
// Where you are (view, line, window, playback position) is saved to the
// server as you move, so a reload or another browser lands in the same place.
// Dialogue editing is the existing review editor mounted here, not a copy of
// it; notes are server records tied to a cue, a source and a time.

export const VIEWS = [
  ['overview', 'Overview'], ['cast', 'Cast'], ['dialogue', 'Dialogue'],
  ['compare', 'Compare'], ['export', 'Export'],
];
const STYLES = [['automatic', 'Automatic'], ['guided', 'Guided'], ['manual', 'Manual']];
const QUICK = ['Wrong word', 'Rushed', 'Dragging', 'Too loud', 'Too quiet', 'Flat delivery',
  'Odd noise', 'Not in the original'];
const clock = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const stamp = s => `${clock(s)}.${Math.floor((s % 1) * 10)}`;

export function createStudio({ review, onQueued }) {
  const root = () => document.getElementById('studioRoot');
  const audio = new Audio();
  audio.preload = 'none';
  // Reachable for a headless playback check, as on the listening page.
  window.__studioAudio = audio;
  let video = null, player = null;
  let sid = '', view = 'overview', overview = null, session = null, notes = [];
  let windowSpan = null, sources = [], lines = [], saveTimer = null, epoch = 0;
  let blind = false;

  function ensurePlayer() {
    if (player) return;
    video = document.createElement('video');
    video.muted = true; video.playsInline = true; video.className = 'studio-video';
    video.setAttribute('aria-label', 'Scene picture (follows the audio)');
    player = createStudioPlayer({ audio, video, onChange: onPlayer });
  }

  // ---------------------------------------------------------------- session

  async function open(id, requestedView) {
    const version = ++epoch;
    ensurePlayer();
    sid = id;
    root().innerHTML = '<p class="hint" style="padding:24px 4px;">Loading the studio…</p>';
    try {
      overview = await api(`studio/sessions/${id}`);
    } catch (error) {
      root().innerHTML = `<div class="panel" style="padding:20px 24px;">${esc(error.message)}</div>`;
      return;
    }
    if (version !== epoch) return;
    session = overview.session;
    view = VIEWS.some(([v]) => v === requestedView) ? requestedView : (session.view || 'overview');
    blind = !!session.compare?.blind && !session.compare?.revealed;
    renderShell();
    await show(view, { push: false });
  }

  async function reload() {
    overview = await api(`studio/sessions/${sid}`);
    session = overview.session;
    renderHead();
    return overview;
  }

  function jobId() { return overview?.active_job?.id || ''; }

  // Save where the person is, a moment after they stop moving. A conflict
  // means another tab moved on: take its revision and keep ours on top.
  function remember(patch) {
    Object.assign(session, patch);
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      try {
        const saved = await api(`studio/sessions/${sid}`, { method: 'PATCH',
          json: { base_revision: session.revision, ...patch } });
        session = { ...session, ...saved.session };
        status('');
      } catch (error) {
        if (error.status === 409 && error.data?.current) {
          session.revision = error.data.current.revision;
          remember(patch);
        } else status(`Could not save your place: ${error.message}`);
      }
    }, 400);
  }

  function status(text) {
    const node = document.getElementById('studioStatus');
    if (node) node.textContent = text;
  }

  // ------------------------------------------------------------------ shell

  function renderShell() {
    root().innerHTML = `
      <div class="studio-head" id="studioHead"></div>
      <div class="studio-transport" id="studioTransport" hidden>
        <div class="studio-row">
          <button type="button" class="studio-play" id="stPlay" aria-label="Play or pause (space)">
            <span id="stGlyph" aria-hidden="true">▶</span></button>
          <div class="studio-clock"><div class="m" id="stNow">0:00.0</div>
            <div class="m hint" id="stTotal"></div></div>
          <div class="studio-wave" id="stWave" role="slider" tabindex="0"
               aria-label="Position in this window" aria-valuemin="0" aria-valuemax="100"></div>
          <div class="studio-picture" id="stPicture"></div>
        </div>
        <div class="studio-row studio-sources" id="stSources" role="radiogroup"
             aria-label="What to play"></div>
        <div class="studio-row studio-tools">
          <button type="button" class="opt" id="stLoop" aria-pressed="false">Loop line <span class="kbd">L</span></button>
          <button type="button" class="opt" id="stSeq" aria-pressed="false">Play line in each version <span class="kbd">P</span></button>
          <button type="button" class="opt" id="stMatch" aria-pressed="false"
            title="Plays each source at the same speech level. The render is not changed.">Level-matched preview <span class="kbd">M</span></button>
          <button type="button" class="btn btn-primary" id="stMark">Mark this moment <span class="kbd">N</span></button>
          <span class="hint" id="stMapping" role="status"></span>
        </div>
      </div>
      <nav class="studio-tabs" role="tablist" aria-label="Studio views">
        ${VIEWS.map(([v, label]) => `<button type="button" role="tab" class="tab" data-view="${v}"
          aria-selected="${v === view}" aria-controls="studioBody">${label}</button>`).join('')}
      </nav>
      <p class="hint" id="studioStatus" role="status" aria-live="polite"></p>
      <section id="studioBody" class="studio-body" role="tabpanel"></section>`;
    renderHead();
    root().querySelectorAll('.studio-tabs [data-view]').forEach(b =>
      b.addEventListener('click', () => show(b.dataset.view)));
    document.getElementById('stPlay').onclick = () => player.toggle();
    document.getElementById('stMark').onclick = () => mark('');
    document.getElementById('stMatch').onclick = () => player.setMatched(!player.matched);
    document.getElementById('stLoop').onclick = () => toggleLoop();
    document.getElementById('stSeq').onclick = () => sequenceLine();
    const wave = document.getElementById('stWave');
    wave.addEventListener('click', e => {
      if (!windowSpan) return;
      const box = wave.getBoundingClientRect();
      player.seek(windowSpan.start + ((e.clientX - box.left) / box.width) * (windowSpan.end - windowSpan.start));
    });
    wave.addEventListener('keydown', e => {
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault();
        player.seek(player.time + (e.key === 'ArrowRight' ? 2 : -2));
      }
    });
    document.getElementById('stPicture').append(video);
  }

  function renderHead() {
    const head = document.getElementById('studioHead');
    if (!head || !session) return;
    const next = overview?.next || {};
    head.innerHTML = `
      <div class="studio-title">
        <button type="button" class="btn btn-ghost" id="stBack">← Dubs</button>
        <div style="min-width:0;">
          <h2>${esc(session.title)}</h2>
          <p class="hint">${esc(session.media_name)}${overview?.active_job
            ? ` · run ${esc(overview.active_job.id)} (${esc(overview.active_job.status)})` : ' · no draft yet'}</p>
        </div>
        <div class="studio-style" role="radiogroup" aria-label="Working style">
          ${STYLES.map(([v, label]) => `<button type="button" class="opt" role="radio"
            aria-checked="${session.style === v}" aria-pressed="${session.style === v}"
            data-style="${v}">${label}</button>`).join('')}
        </div>
      </div>
      <p class="studio-next">${next.reason ? `Next: ${esc(nextLabel(next.action))} — ${esc(next.reason)}` : ''}
        ${next.view && next.view !== view ? `<button type="button" class="btn btn-ghost" data-go="${esc(next.view)}">Go there</button>` : ''}</p>`;
    head.querySelector('#stBack').onclick = () => { close(); history.pushState({}, '', '/dubs');
      window.dispatchEvent(new PopStateEvent('popstate')); };
    head.querySelectorAll('[data-style]').forEach(b => b.addEventListener('click', async () => {
      await savePatch({ style: b.dataset.style });
      await reload();
    }));
    head.querySelector('[data-go]')?.addEventListener('click', e => show(e.currentTarget.dataset.go));
  }

  function nextLabel(action) {
    return { audition: 'audition the cast', render: 'render a draft', wait: 'wait for the render',
      review: 'review the script', rerender: 're-render stale lines',
      confirm_export: 'confirm the export', done: 'nothing required' }[action] || action;
  }

  async function savePatch(patch) {
    try {
      const saved = await api(`studio/sessions/${sid}`, { method: 'PATCH',
        json: { base_revision: session.revision, ...patch } });
      session = saved.session;
      status('Saved.');
      return true;
    } catch (error) {
      if (error.status === 409 && error.data?.current) {
        session.revision = error.data.current.revision;
        status('Someone else changed this studio; your change was applied on top.');
        return savePatch(patch);
      }
      status(error.message);
      return false;
    }
  }

  // ------------------------------------------------------------------ views

  async function show(next, { push = true } = {}) {
    if (view === 'dialogue' && next !== 'dialogue') review.unmount();
    view = next;
    const path = `/studio/${encodeURIComponent(sid)}/${view}`;
    if (push && location.pathname !== path) history.pushState({}, '', path);
    document.title = `${session.title} — ${VIEWS.find(([v]) => v === view)[1]} — Doblarr`;
    root().querySelectorAll('.studio-tabs [data-view]').forEach(b =>
      b.setAttribute('aria-selected', String(b.dataset.view === view)));
    if (session.view !== view) remember({ view });
    renderHead();
    const body = document.getElementById('studioBody');
    const ctx = context();
    const transport = view === 'dialogue' || view === 'compare';
    document.getElementById('studioTransport').hidden = !transport;
    if (!transport) player.stop();
    if (view === 'overview') return renderOverview(body, ctx);
    if (view === 'cast') return renderCast(body, ctx);
    if (view === 'export') return renderExport(body, ctx);
    if (view === 'dialogue') return renderDialogue(body);
    return renderCompare(body);
  }

  function context() {
    return { sid, get session() { return session; }, get overview() { return overview; },
      jobId, reload, show, status, savePatch, onQueued, playWindow, notes: () => notes };
  }

  // --------------------------------------------------------------- dialogue

  async function renderDialogue(body) {
    if (!jobId()) {
      body.innerHTML = emptyNoDraft();
      body.querySelector('[data-go]')?.addEventListener('click', () => show('overview'));
      return;
    }
    body.innerHTML = `<div class="studio-dialogue" id="studioDialogue"></div>
      <aside class="panel studio-notes" id="studioNotes" aria-label="Notes on this run"></aside>`;
    review.mount(document.getElementById('studioDialogue'));
    await review.open(jobId());
    if (session.line != null) review.focusLine(session.line);
    await loadNotes();
  }

  function emptyNoDraft() {
    return `<div class="panel studio-empty"><p>No draft has been rendered for this episode yet.
      Dialogue, takes and comparisons appear once a run finishes.</p>
      <button type="button" class="btn btn-primary" data-go="overview">Render a draft from Overview</button></div>`;
  }

  // The editor told us which line is open: follow it with the transport.
  async function onLine(row) {
    if (!session || view !== 'dialogue' || row.index == null) return;
    if (session.line !== row.index) remember({ line: row.index, cue: row.cue?.cue_id || null });
    try {
      const scene = await api(`jobs/${jobId()}/scene/${row.index}?context=2`);
      // Another line of the same exchange: keep playing, only move the playhead.
      if (windowSpan && scene.target.start === windowSpan.start && scene.target.end === windowSpan.end) {
        player.seek(row.start);
        return;
      }
      await playWindow({ start: scene.target.start, end: scene.target.end },
        (review.data?.segments || []).filter(s => scene.cues.includes(s.index)));
      renderNotes();
    } catch (error) { status(error.message); }
  }

  // ---------------------------------------------------------------- compare

  async function renderCompare(body) {
    const hasJob = !!jobId();
    const saved = session.compare || {};
    body.innerHTML = `
      <div class="studio-compare">
        <div class="panel studio-window">
          <div class="studio-window-row">
            <label class="review-field">Window start (s)
              <input class="input m" type="number" min="0" step="0.5" id="cmpStart"
                value="${saved.start ?? (windowSpan?.start ?? session.position ?? 0)}"></label>
            <label class="review-field">Length (s)
              <input class="input m" type="number" min="2" max="240" step="1" id="cmpLen"
                value="${saved.length ?? 30}"></label>
            <button type="button" class="btn btn-secondary" id="cmpLoad">Load window</button>
            <label class="studio-check"><input type="checkbox" id="cmpBlind" ${blind ? 'checked' : ''}
              ${saved.revealed ? 'disabled' : ''}> Blind labels for dub versions</label>
            ${saved.revealed ? `<span class="tag tag-neutral">Labels revealed ${esc((saved.revealed_at || '').slice(0, 16))}</span>`
              : '<button type="button" class="btn btn-ghost" id="cmpReveal">Reveal labels</button>'}
          </div>
          <p class="hint">${hasJob ? 'Scene windows follow the selected line in Dialogue. ' : ''}
            References play at the same moment through their alignment; an unaligned reference
            plays at the same timestamps and says so.</p>
        </div>
        <div class="panel studio-verdict" id="cmpVerdict"></div>
        <aside class="panel studio-notes" id="studioNotes" aria-label="Notes"></aside>
        <div id="cmpImports"></div>
        <div id="cmpExperiments"></div>
      </div>`;
    body.querySelector('#cmpLoad').onclick = () => loadCompareWindow();
    body.querySelector('#cmpBlind').onchange = e => {
      blind = e.target.checked;
      remember({ compare: { ...(session.compare || {}), blind } });
      renderSources();
    };
    body.querySelector('#cmpReveal')?.addEventListener('click', () => {
      const at = new Date().toISOString();
      blind = false;
      remember({ compare: { ...(session.compare || {}), blind: false, revealed: true, revealed_at: at } });
      renderCompare(body);
    });
    await loadNotes();
    await loadCompareWindow();
    renderImports(body.querySelector('#cmpImports'));
    renderExperiments(body.querySelector('#cmpExperiments'), context());
  }

  async function loadCompareWindow() {
    const start = Math.max(0, Number(document.getElementById('cmpStart')?.value) || 0);
    const length = Math.max(2, Math.min(240, Number(document.getElementById('cmpLen')?.value) || 30));
    remember({ compare: { ...(session.compare || {}), start, length }, position: start });
    const inWindow = (review.data?.segments || []).filter(s => s.start < start + length && s.end > start);
    await playWindow({ start, end: start + length }, inWindow);
    renderVerdict();
  }

  // Build the source rail for a target window and load the first playable one.
  async function playWindow(span, rows) {
    windowSpan = span;
    lines = rows || [];
    const list = [];
    const meaning = (overview.references || []).find(r => r.roles.includes('meaning') && r.track);
    list.push(meaning
      ? { id: 'original', kind: 'original', label: 'Original', sub: `${meaning.language} · ${meaning.label}` }
      : { id: 'original', kind: 'original', label: jobId() ? 'Run source' : 'First track',
        sub: 'not confirmed as the original' });
    if (jobId()) list.push({ id: 'dub', kind: 'dub', label: 'This dub', sub: 'as rendered' });
    (overview.output_tracks || []).forEach(t => list.push({ id: `output:${t.audio_index}`, kind: 'dub',
      label: `${t.title && t.title !== 'AAC' ? t.title : `Track ${t.audio_index}`} (${t.language || '?'})`,
      sub: 'delivered file' }));
    (overview.references || []).filter(r => r.track && !r.evaluation_only && !r.roles.includes('meaning'))
      .forEach(r => list.push({ id: `reference:${r.id}`, kind: 'reference', label: r.label,
        sub: `${r.language} · ${r.roles.join(', ') || 'no role'}` }));
    if (jobId()) {
      try {
        const saved = await api(`jobs/${jobId()}/versions`);
        (saved.versions || []).filter(v => v.available && !v.current).slice(0, 3).forEach(v =>
          list.push({ id: `version:${v.version_id}`, kind: 'version', label: `Saved ${v.name}`,
            sub: (v.created_at || '').slice(0, 16).replace('T', ' ') }));
      } catch { /* versions are optional */ }
    }
    sources = list;
    player.attach({ session: sid, job: jobId(), span, list,
      showVideo: safeGet('doblarr.studio.video', '1') === '1' });
    renderSources();
    await Promise.all(list.map(async s => {
      const q = new URLSearchParams({ source: s.id, start: span.start, end: span.end });
      if (jobId()) q.set('job_id', jobId());
      try {
        const w = await api(`studio/sessions/${sid}/media/window?${q}`);
        Object.assign(s, { peaks: w.peaks, level_db: w.level_db, mapping: w, available: true });
      } catch (error) { Object.assign(s, { available: false, reason: error.message }); }
    }));
    renderSources();
    const first = list.find(s => s.available) || null;
    if (first) await player.load(first, { keep: false, play: false });
    else status('Nothing in this window can be played.');
    drawWave();
  }

  function blindLabel(source) {
    if (!blind || !['dub', 'version'].includes(source.kind)) return source.label;
    const versions = sources.filter(s => ['dub', 'version'].includes(s.kind))
      .map(s => s.id).sort((a, b) => hash(`${sid}:${a}`) - hash(`${sid}:${b}`));
    return `Version ${versions.indexOf(source.id) + 1}`;
  }

  function renderSources() {
    const box = document.getElementById('stSources');
    if (!box) return;
    let n = 0;
    box.innerHTML = sources.map(s => {
      const keyName = s.kind === 'original' ? '0' : s.kind === 'reference' ? 'R' : String(++n);
      s.key = keyName;
      const state = s.mapping?.state && s.mapping.state !== 'exact' ? s.mapping.state : '';
      return `<button type="button" class="studio-src" role="radio" data-kind="${s.kind}"
        data-id="${esc(s.id)}" aria-checked="${player.source?.id === s.id}"
        ${s.available === false ? 'disabled' : ''} title="${esc(s.reason || s.mapping?.note || '')}">
        <span class="studio-src-top"><strong>${esc(blindLabel(s))}</strong><span class="kbd">${keyName}</span></span>
        <span class="studio-src-sub">${esc(blind && ['dub', 'version'].includes(s.kind) ? 'blind' : s.sub)}
          ${state ? `· <em>${esc(state)}</em>` : ''}${s.available === false ? ' · unavailable' : ''}</span>
      </button>`;
    }).join('');
    box.querySelectorAll('.studio-src').forEach(b => b.addEventListener('click', () =>
      player.select(b.dataset.id)));
  }

  function drawWave() {
    const wave = document.getElementById('stWave');
    if (!wave || !windowSpan) return;
    const span = windowSpan.end - windowSpan.start;
    const peaks = player.source?.peaks || [];
    wave.innerHTML = `<div class="studio-bars">${peaks.map(p =>
      `<i style="height:${Math.max(2, p * 100)}%"></i>`).join('')}</div>`
      + lines.map(l => `<button type="button" class="studio-lane" data-line="${l.index}"
          style="left:${((Math.max(l.start, windowSpan.start) - windowSpan.start) / span) * 100}%;
          width:${((Math.min(l.end, windowSpan.end) - Math.max(l.start, windowSpan.start)) / span) * 100}%"
          title="${esc(`${l.speaker}: ${l.text_translated || l.text_src}`)}" aria-label="Line ${l.index + 1}"></button>`).join('')
      + notes.filter(n => n.at >= windowSpan.start && n.at < windowSpan.end).map(n =>
        `<button type="button" class="studio-pin" data-sev="${esc(n.severity)}" data-at="${n.at}"
          style="left:${((n.at - windowSpan.start) / span) * 100}%" title="${esc(`${stamp(n.at)} ${n.category} ${n.note}`)}"
          aria-label="Note at ${stamp(n.at)}">!</button>`).join('')
      + '<div class="studio-head-line" id="stHead"></div>';
    wave.querySelectorAll('.studio-lane').forEach(b => b.addEventListener('click', e => {
      e.stopPropagation();
      const line = lines.find(l => l.index === Number(b.dataset.line));
      if (line) player.seek(line.start);
    }));
    wave.querySelectorAll('.studio-pin').forEach(b => b.addEventListener('click', e => {
      e.stopPropagation(); player.seek(Number(b.dataset.at));
    }));
    paint();
  }

  function paint() {
    if (!windowSpan) return;
    const span = windowSpan.end - windowSpan.start;
    const t = player.time;
    const now = document.getElementById('stNow');
    if (!now) return;
    now.textContent = stamp(t);
    document.getElementById('stTotal').textContent = `${clock(windowSpan.start)}–${clock(windowSpan.end)}`;
    document.getElementById('stGlyph').textContent = player.paused ? '▶' : '❚❚';
    const head = document.getElementById('stHead');
    if (head) head.style.left = `${Math.max(0, Math.min(100, ((t - windowSpan.start) / span) * 100))}%`;
    const wave = document.getElementById('stWave');
    wave?.setAttribute('aria-valuenow', String(Math.round(((t - windowSpan.start) / span) * 100)));
    document.querySelectorAll('.studio-lane').forEach(b => {
      const line = lines.find(l => l.index === Number(b.dataset.line));
      b.dataset.active = String(!!line && line.start <= t && t < line.end);
    });
    document.getElementById('stMatch')?.setAttribute('aria-pressed', String(player.matched));
    document.getElementById('stLoop')?.setAttribute('aria-pressed', String(!!player.loop));
    document.getElementById('stSeq')?.setAttribute('aria-pressed', String(!!player.sequence));
  }

  function onPlayer(what, detail) {
    if (what === 'ready') {
      document.querySelectorAll('.studio-src').forEach(b =>
        b.setAttribute('aria-checked', String(b.dataset.id === detail.source.id)));
      const m = detail.source.mapping;
      document.getElementById('stMapping').textContent = m?.note
        ? `${blindLabel(detail.source)}: ${m.note}${m.mapped_start != null ? ` (its ${clock(m.mapped_start)})` : ''}`
        : '';
      drawWave();
      status('');
    }
    if (what === 'error') status(detail.message);
    if (what === 'time' || what === 'play' || what === 'pause' || what === 'matched'
      || what === 'loop' || what === 'sequence') paint();
    if (what === 'pause' && windowSpan) remember({ position: Number(player.time.toFixed(2)) });
  }

  function currentLine() {
    const t = player.time;
    return lines.find(l => l.start <= t && t < l.end) || null;
  }

  function toggleLoop() {
    if (player.loop) { player.setLoop(null); return; }
    const line = currentLine() || lines[0];
    if (line) player.setLoop({ start: line.start, end: line.end });
  }

  function sequenceLine() {
    const line = currentLine() || lines[0];
    const order = sources.filter(s => s.available && s.kind !== 'reference');
    if (line && order.length) player.playSequence({ start: line.start, end: line.end }, order);
  }

  // ------------------------------------------------------------------ notes

  async function loadNotes() {
    try {
      const data = await api(`studio/sessions/${sid}/notes${jobId() ? `?job_id=${jobId()}` : ''}`);
      notes = data.notes || [];
    } catch { notes = []; }
    renderNotes();
    drawWave();
  }

  async function mark(category) {
    if (!windowSpan) return;
    const line = currentLine();
    const source = player.source;
    try {
      const saved = await api(`studio/sessions/${sid}/notes`, { method: 'POST', json: {
        job_id: jobId(), cue: line?.cue?.cue_id || '', line: line?.index ?? null,
        source: source ? `${source.id}${blind ? ` (${blindLabel(source)})` : ''}` : '',
        at: Number(player.time.toFixed(2)), category, severity: 'noticeable',
        snapshot_revision: review.data?.revision || '' } });
      notes.push(saved.note);
      renderNotes(saved.note.id);
      drawWave();
      status(`Marked ${stamp(saved.note.at)}${line ? ` on line ${line.index + 1}` : ''}.`);
    } catch (error) { status(error.message); }
  }

  function renderNotes(fresh) {
    const box = document.getElementById('studioNotes');
    if (!box) return;
    const filter = session.filters?.notes || 'open';
    const shown = notes.filter(n => n.category !== 'verdict')
      .filter(n => filter === 'all' || (n.resolution || 'open') !== 'resolved')
      .sort((a, b) => a.at - b.at);
    box.innerHTML = `<div class="studio-notes-head"><h3>Notes</h3>
        <label class="review-filter">Show <select class="input" id="noteFilter">
          <option value="open" ${filter === 'open' ? 'selected' : ''}>Open</option>
          <option value="all" ${filter === 'all' ? 'selected' : ''}>All</option></select></label></div>
      <div class="studio-quick">${QUICK.map(q => `<button type="button" class="btn btn-ghost" data-quick="${esc(q)}">+ ${esc(q)}</button>`).join('')}</div>
      ${shown.length ? shown.map(n => noteRow(n, fresh)).join('')
        : '<p class="hint">No notes here yet. Press N while listening to mark a moment.</p>'}`;
    box.querySelector('#noteFilter').onchange = e =>
      { remember({ filters: { ...(session.filters || {}), notes: e.target.value } }); renderNotes(); };
    box.querySelectorAll('[data-quick]').forEach(b => b.onclick = () => mark(b.dataset.quick));
    box.querySelectorAll('.studio-note').forEach(node => wireNote(node));
  }

  function noteRow(n, fresh) {
    return `<div class="studio-note" data-id="${esc(n.id)}" data-fresh="${n.id === fresh}">
      <div class="studio-note-top">
        <button type="button" class="btn btn-ghost m" data-hear>${stamp(n.at)}</button>
        <span class="tag tag-neutral">${esc(n.source || 'no source')}</span>
        ${n.line != null ? `<span class="hint">line ${n.line + 1}</span>` : ''}
        ${n.stale ? '<span class="review-marker">made on older audio</span>' : ''}
        <span class="tag ${n.resolution === 'resolved' ? 'tag-neutral' : 'tag-accent'}">${esc((n.resolution || 'open').replace('_', ' '))}</span>
      </div>
      <div class="studio-note-fields">
        <input class="input" data-field="category" value="${esc(n.category)}" placeholder="What" aria-label="What">
        <select class="input" data-field="severity" aria-label="How bad">${['minor', 'noticeable', 'major'].map(s =>
          `<option ${n.severity === s ? 'selected' : ''}>${s}</option>`).join('')}</select>
        <input class="input" data-field="note" value="${esc(n.note)}" placeholder="Describe it" aria-label="Note">
      </div>
      <div class="studio-note-actions">
        ${n.line != null ? '<button type="button" class="btn btn-ghost" data-edit>Open in editor</button>' : ''}
        <button type="button" class="btn btn-ghost" data-original>Hear original here</button>
        ${n.resolution !== 'resolved' ? '<button type="button" class="btn btn-ghost" data-resolve>Resolve</button>'
          : '<button type="button" class="btn btn-ghost" data-reopen>Reopen</button>'}
      </div></div>`;
  }

  function wireNote(node) {
    const note = notes.find(n => n.id === node.dataset.id);
    if (!note) return;
    node.querySelector('[data-hear]').onclick = () => {
      const id = note.source.split(' ')[0];
      if (sources.some(s => s.id === id)) player.select(id);
      player.seek(Math.max(windowSpan?.start ?? 0, note.at - 1));
    };
    node.querySelector('[data-original]').onclick = async () => {
      await player.select('original'); player.seek(Math.max(0, note.at - 1));
    };
    node.querySelector('[data-edit]')?.addEventListener('click', async () => {
      await show('dialogue');
      review.focusLine(note.line);
    });
    const patch = async changes => {
      try {
        const saved = await api(`studio/notes/${note.id}`, { method: 'PATCH',
          json: { base_revision: note.revision, ...changes } });
        Object.assign(note, saved.note);
        renderNotes();
      } catch (error) { status(error.message); }
    };
    node.querySelector('[data-resolve]')?.addEventListener('click', () => patch({ resolution: 'resolved' }));
    node.querySelector('[data-reopen]')?.addEventListener('click', () => patch({ resolution: 'open' }));
    node.querySelectorAll('[data-field]').forEach(field => field.addEventListener('change', () =>
      patch({ [field.dataset.field]: field.value })));
  }

  // A scene verdict is a note of its own kind, pinned to the window start.
  function renderVerdict() {
    const box = document.getElementById('cmpVerdict');
    if (!box || !windowSpan) return;
    const verdict = notes.find(n => n.category === 'verdict' && Math.abs(n.at - windowSpan.start) < 0.01);
    const choices = sources.filter(s => ['dub', 'version'].includes(s.kind) && s.available !== false)
      .map(s => blindLabel(s));
    const options = [...choices, 'No difference', 'All bad', 'Not sure'];
    box.innerHTML = `<h3>Which sounded best in this window?</h3>
      <div class="studio-style">${options.map(o => `<button type="button" class="opt"
        aria-pressed="${verdict?.verdict === o}" data-verdict="${esc(o)}">${esc(o)}</button>`).join('')}</div>
      <p class="hint">Saved with the window, the run and the labels shown${blind ? ' (blind)' : ''}. A verdict
        is yours; technical checks never fill it in.</p>
      <button type="button" class="btn btn-secondary" id="cmpResults">Download filled results</button>`;
    box.querySelectorAll('[data-verdict]').forEach(b => b.onclick = async () => {
      try {
        if (verdict) {
          const saved = await api(`studio/notes/${verdict.id}`, { method: 'PATCH',
            json: { base_revision: verdict.revision, verdict: b.dataset.verdict } });
          Object.assign(verdict, saved.note);
        } else {
          const saved = await api(`studio/sessions/${sid}/notes`, { method: 'POST', json: {
            job_id: jobId(), at: windowSpan.start, category: 'verdict',
            note: `${clock(windowSpan.start)}–${clock(windowSpan.end)}${blind ? ' (blind)' : ''}`,
            snapshot_revision: review.data?.revision || '' } });
          const again = await api(`studio/notes/${saved.note.id}`, { method: 'PATCH',
            json: { base_revision: saved.note.revision, verdict: b.dataset.verdict } });
          notes.push(again.note);
        }
        renderVerdict();
      } catch (error) { status(error.message); }
    });
    box.querySelector('#cmpResults').onclick = downloadResults;
  }

  function downloadResults() {
    const out = [`# Studio listening results — ${session.title}`, '',
      `Run: ${jobId() || '(none)'} · exported ${new Date().toISOString().slice(0, 16)}`, '',
      '## Verdicts', ''];
    notes.filter(n => n.category === 'verdict').forEach(n =>
      out.push(`- ${n.note}: **${n.verdict || '(not answered)'}**`));
    out.push('', '## Marked moments', '', '| At | Source | What | How bad | Line | Note | State |',
      '| --- | --- | --- | --- | --- | --- | --- |');
    notes.filter(n => n.category !== 'verdict').sort((a, b) => a.at - b.at).forEach(n =>
      out.push(`| ${stamp(n.at)} | ${n.source} | ${n.category || '—'} | ${n.severity} | `
        + `${n.line != null ? n.line + 1 : '—'} | ${(n.note || '').replaceAll('|', '/')} | ${n.resolution || 'open'}`
        + `${n.stale ? ' (older audio)' : ''} |`));
    out.push('', '## What this cannot settle', '',
      '- A bounded window says nothing about an unreviewed episode.',
      '- Technical checks rank defects; they do not judge acting.', '');
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([out.join('\n')], { type: 'text/markdown' }));
    link.download = `studio-results-${sid}.md`;
    document.body.append(link); link.click(); link.remove();
  }

  // --------------------------------------------------------- legacy imports

  async function renderImports(box) {
    if (!box) return;   // the view was left while the window loaded
    const imports = (overview.imports || []).filter(i => i.kind === 'comparison');
    if (!imports.length) { box.innerHTML = ''; return; }
    box.innerHTML = `<div class="panel studio-legacy"><h3>Imported comparisons</h3>
      <p class="hint">Earlier listening tests, played from their own files. Nothing was re-rendered.</p>
      <div id="legacyList"></div></div>`;
    const list = box.querySelector('#legacyList');
    for (const summary of imports) {
      try {
        const { import: found } = await api(`studio/imports/${summary.id}`);
        list.insertAdjacentHTML('beforeend', `<details class="studio-legacy-item"><summary>
          ${esc(found.legacy_id)} · ${found.scenes.length} scene(s)
          ${found.judgments ? ` · ${found.judgments} imported judgment file(s)` : ''}
          ${found.missing.length ? ` · <span class="review-marker">${found.missing.length} missing file(s)</span>` : ''}</summary>
          ${found.scenes.map(s => `<div class="studio-legacy-scene"><strong>${esc(s.title)}</strong>
            <div class="studio-style">
            ${s.source.exists ? `<button type="button" class="opt" data-legacy="${esc(summary.id)}" data-scene="${s.index}" data-kind="source" data-name="">Original</button>` : ''}
            ${s.references.filter(r => r.exists).map(r => `<button type="button" class="opt" data-legacy="${esc(summary.id)}" data-scene="${s.index}" data-kind="reference" data-name="${esc(r.language)}">${esc(r.role)} (${esc(r.language)})</button>`).join('')}
            ${s.variants.map(v => v.mixed.exists ? `<button type="button" class="opt" data-legacy="${esc(summary.id)}" data-scene="${s.index}" data-kind="mixed" data-name="${esc(v.name)}">${esc(v.name)}</button>`
              : `<span class="hint">${esc(v.name)}: missing</span>`).join('')}
            </div></div>`).join('')}
          ${(found.judgments_imported || []).map(j => `<p class="hint">Imported from ${esc(j.file)}: ${j.answered} verdict(s), ${j.marks} marked moment(s). ${esc(j.provenance)}.</p>`).join('')}
          <p class="hint">${esc(found.settings_note || '')}</p></details>`);
      } catch (error) { list.insertAdjacentHTML('beforeend', `<p class="hint">${esc(error.message)}</p>`); }
    }
    list.querySelectorAll('[data-legacy]').forEach(b => b.onclick = async () => {
      const q = new URLSearchParams({ scene: b.dataset.scene, kind: b.dataset.kind, name: b.dataset.name });
      const key = safeGet('doblarr_api_key', '');
      const url = `/api/studio/imports/${b.dataset.legacy}/media?${q}${key ? `&api_key=${encodeURIComponent(key)}` : ''}`;
      windowSpan = { start: 0, end: 240 };
      lines = [];
      const source = { id: `legacy:${b.dataset.kind}:${b.dataset.name}`, url, label: b.textContent.trim(),
        kind: 'legacy', available: true };
      sources = [source];
      player.attach({ session: sid, job: '', span: windowSpan, list: sources, showVideo: false });
      renderSources();
      await player.load(source, { keep: false, play: true });
      list.querySelectorAll('[data-legacy]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    });
  }

  // --------------------------------------------------------------- keyboard

  document.addEventListener('keydown', e => {
    if (!root() || root().closest('[hidden]') || !player || !sid) return;
    if (view !== 'compare' && view !== 'dialogue') return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target.matches('input, textarea, select, [contenteditable]')) return;
    if (document.querySelector('dialog[open]')) return;
    const k = e.key.toLowerCase();
    const pick = key => sources.find(s => s.key === key && s.available !== false);
    if (k === ' ') { e.preventDefault(); player.toggle(); return; }
    if (k === 'n') { e.preventDefault(); mark(''); return; }
    if (k === 'm') { e.preventDefault(); player.setMatched(!player.matched); return; }
    if (k === 'l') { e.preventDefault(); toggleLoop(); return; }
    if (k === 'p') { e.preventDefault(); sequenceLine(); return; }
    if (k === 'j' || k === 'k') {
      e.preventDefault();
      const ordered = [...lines].sort((a, b) => a.start - b.start);
      const here = ordered.findIndex(l => l.start <= player.time && player.time < l.end);
      const next = ordered[Math.max(0, Math.min(ordered.length - 1, (here < 0 ? 0 : here) + (k === 'k' ? 1 : -1)))];
      if (next) player.seek(next.start);
      return;
    }
    const target = k === 'o' ? pick('0') : k === 'r' ? pick('R') : pick(k);
    if (target) { e.preventDefault(); player.load(target); }
  });

  function close() {
    player?.stop();
    if (view === 'dialogue') review.unmount();
    clearTimeout(saveTimer);
    sid = '';
  }

  function toggleVideo(on) { safeSet('doblarr.studio.video', on ? '1' : '0'); }

  // A repair was queued from the editor: every open note on those lines now
  // points at the run that should fix it, so Compare can close the loop.
  async function repairQueued(result, cues) {
    if (!sid || !result?.job?.id) return;
    for (const note of notes.filter(n => cues.includes(n.cue) && (n.resolution || 'open') === 'open')) {
      try {
        const saved = await api(`studio/notes/${note.id}`, { method: 'PATCH', json: {
          base_revision: note.revision, resolution: 'repair_queued',
          linked_edit: { job: result.job.id, cue: note.cue } } });
        Object.assign(note, saved.note);
      } catch { /* the note moved on elsewhere; it is still listed */ }
    }
    renderNotes();
    status(`Repair queued as run ${result.job.id}. Compare it with this one when it finishes, then resolve the note.`);
  }

  return { open, close, onLine, show, repairQueued, toggleVideo, get sid() { return sid; } };
}

function hash(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
