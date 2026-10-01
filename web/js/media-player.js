// A large popup player for any reel of media clips, after ClutchCut's
// CustomVideoPlayer: the video, a timeline with a mark at every clip, a side
// list of the clips (passed, playing, upcoming) that jumps on click, and
// play / replay / fullscreen.
//
// A reel is not a file. It is a list of stretches (a character's lines, a
// scene's exchange), each fetched as its own small clip and played back to
// back, so the timeline is the reel's own time: "Mina, 43 lines, 1:52".
// When the media has several audio tracks the reel can switch language at
// the same place in the same clip.
//
//   openMediaPlayer({ title, subtitle, colour, clips, tracks, track, startAt, menu, onClose })
//   clips:  [{ start, end, label, text, detail, tag, url(track) }]
//   tracks: [{ key, label }]  (optional)
//   menu:   (clip, index, { close, update }) => Element, the "⋯" of each clip
//           (optional); update(index, patch) redraws that clip's card.

const ICONS = {
  play: 'M8 5v14l11-7z',
  pause: 'M6 5h4v14H6zm8 0h4v14h-4z',
  replay: 'M12 5V1L7 6l5 5V7a6 6 0 1 1-6 6H4a8 8 0 1 0 8-8z',
  prev: 'M6 6h2v12H6zm3.5 6 8.5 6V6z',
  next: 'M16 6h2v12h-2zM6 18l8.5-6L6 6z',
  list: 'M3 5h2v2H3zm4 0h14v2H7zm-4 6h2v2H3zm4 0h14v2H7zm-4 6h2v2H3zm4 0h14v2H7z',
  full: 'M5 5h5v2H7v3H5zm9 0h5v5h-2V7h-3zM5 14h2v3h3v2H5zm12 0h2v5h-5v-2h3z',
  exit: 'M8 5h2v5H5V8h3zm6 0h2v3h3v2h-5zM5 14h5v5H8v-3H5zm9 0h5v2h-3v3h-2z',
  more: 'M6 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm6 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm6 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4z',
  close: 'M6.4 5 5 6.4 10.6 12 5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6L19 6.4 17.6 5 12 10.6z',
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${ICONS[name]}"/></svg>`;

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const m = Math.floor(seconds / 60), s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

// Reel time <-> (clip, offset). Pure, so it can be tested on its own.
export function reelLayout(clips) {
  let at = 0;
  const offsets = clips.map(c => { const o = at; at += Math.max(0, c.end - c.start); return o; });
  return { offsets, total: at };
}

export function locate(layout, time) {
  const { offsets, total } = layout;
  const t = Math.min(Math.max(0, time), total);
  let i = offsets.length - 1;
  while (i > 0 && offsets[i] > t) i -= 1;
  return { index: Math.max(0, i), offset: t - (offsets[i] || 0) };
}

export function openMediaPlayer({ title = '', subtitle = '', colour = '', clips: given = [], tracks = [], track = null, startAt = 0, menu = null, onClose = null } = {}) {
  const clips = given.map(c => ({ ...c }));
  if (!clips.length) return null;
  const layout = reelLayout(clips);
  const opener = document.activeElement;
  const dialog = document.createElement('dialog');
  dialog.className = 'mp';
  if (colour) dialog.style.setProperty('--mp-accent', colour);
  (document.getElementById('app') || document.body).append(dialog);
  let index = Math.min(Math.max(0, startAt), clips.length - 1);
  let current = track ?? tracks[0]?.key ?? null;
  let playing = true, panelOpen = window.innerWidth > 900, seeking = false, closed = false;
  const blobs = new Map();          // url -> Promise<objectURL>

  dialog.innerHTML = `
    <header class="mp-head">
      <div><h2 class="mp-title">${esc(title)}</h2><p class="hint mp-sub">${esc(subtitle)}</p></div>
      <button type="button" class="mp-icon" data-close aria-label="Close player">${icon('close')}</button>
    </header>
    <div class="mp-stage">
      <div class="mp-screen">
        <video class="mp-video" playsinline preload="auto"></video>
        <p class="mp-caption" aria-live="polite"></p>
        <p class="mp-loading hint" hidden>Cutting the clip…</p>
        <div class="mp-bar">
          <button type="button" class="mp-icon" data-prev aria-label="Previous clip">${icon('prev')}</button>
          <button type="button" class="mp-icon" data-play aria-label="Pause">${icon('pause')}</button>
          <button type="button" class="mp-icon" data-next aria-label="Next clip">${icon('next')}</button>
          <span class="mp-time m"><span data-now>0:00</span> / ${formatTime(layout.total)}</span>
          <div class="mp-track">
            <div class="mp-marks" aria-hidden="true">${layout.offsets.map((o, i) => `<span class="mp-mark" style="left:${(o / (layout.total || 1)) * 100}%" title="${esc(clips[i].label)}"></span>`).join('')}</div>
            <input type="range" class="mp-seek" min="0" max="${layout.total.toFixed(2)}" step="0.05" value="0" aria-label="Position in the reel">
          </div>
          ${tracks.length > 1 ? `<select class="mp-lang" aria-label="Audio language">${tracks.map(t => `<option value="${esc(t.key)}" ${String(t.key) === String(current) ? 'selected' : ''}>${esc(t.label)}</option>`).join('')}</select>` : ''}
          <button type="button" class="mp-icon" data-list aria-label="Clip list" aria-pressed="${panelOpen}">${icon('list')}</button>
          <button type="button" class="mp-icon" data-full aria-label="Fullscreen">${icon('full')}</button>
        </div>
      </div>
      <ol class="mp-panel" ${panelOpen ? '' : 'hidden'}>${clips.map((c, i) => `<li class="mp-row"><button type="button" class="mp-item" data-clip="${i}">
        <span class="mp-dot" aria-hidden="true"></span>
        <span class="mp-card">${card(c)}</span>
      </button>${menu ? `<button type="button" class="mp-icon mp-more" data-more="${i}" aria-label="More for ${esc(c.label)}" aria-haspopup="true">${icon('more')}</button>` : ''}</li>`).join('')}</ol>
    </div>`;

  function card(c) {
    return `<span class="mp-card-label">${esc(c.label)}${c.tag ? ` <span class="mp-tag">${esc(c.tag)}</span>` : ''}</span>`
      + `${c.text ? `<span class="mp-card-text">${esc(c.text)}</span>` : ''}${c.detail ? `<span class="mp-card-detail">${esc(c.detail)}</span>` : ''}`;
  }

  const video = dialog.querySelector('video');
  const seek = dialog.querySelector('.mp-seek');
  const now = dialog.querySelector('[data-now]');
  const caption = dialog.querySelector('.mp-caption');
  const loading = dialog.querySelector('.mp-loading');
  const playButton = dialog.querySelector('[data-play]');
  const items = [...dialog.querySelectorAll('.mp-item')];

  function fetchClip(i) {
    const url = clips[i]?.url(current);
    if (!url) return Promise.reject(new Error('no clip'));
    if (!blobs.has(url)) {
      blobs.set(url, fetch(url).then(r => {
        if (!r.ok) throw new Error(`clip ${r.status}`);
        return r.blob();
      }).then(b => URL.createObjectURL(b)).catch(error => { blobs.delete(url); throw error; }));
    }
    return blobs.get(url);
  }

  function paint() {
    const time = layout.offsets[index] + Math.min(video.currentTime || 0, clips[index].end - clips[index].start);
    if (!seeking) seek.value = time.toFixed(2);
    seek.style.setProperty('--mp-fill', `${(time / (layout.total || 1)) * 100}%`);
    now.textContent = formatTime(time);
    const finished = !playing && index === clips.length - 1 && video.ended;
    playButton.innerHTML = icon(playing ? 'pause' : finished ? 'replay' : 'play');
    playButton.setAttribute('aria-label', playing ? 'Pause' : finished ? 'Play again' : 'Play');
    items.forEach((item, i) => {
      item.classList.toggle('is-active', i === index);
      item.classList.toggle('is-passed', i < index);
    });
  }

  async function show(i, offset = 0, play = playing) {
    index = i;
    const clip = clips[i];
    caption.textContent = clip.text || '';
    paint();
    items[i]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    loading.hidden = false;
    try {
      const src = await fetchClip(i);
      if (closed || index !== i) return;
      if (video.src !== src) video.src = src;
      video.currentTime = offset;
      loading.hidden = true;
      if (play) await video.play().catch(() => { playing = false; });
      fetchClip(i + 1).catch(() => {});        // the next line is ready when this one ends
    } catch (error) {
      loading.textContent = `Could not load this clip (${error.message}).`;
    }
    paint();
  }

  function seekTo(time) {
    const spot = locate(layout, time);
    if (spot.index === index && video.src) { video.currentTime = spot.offset; paint(); }
    else show(spot.index, spot.offset);
  }

  video.addEventListener('timeupdate', paint);
  video.addEventListener('ended', () => {
    if (index < clips.length - 1) show(index + 1, 0, true);
    else { playing = false; paint(); }
  });
  playButton.onclick = () => {
    if (playing) { video.pause(); playing = false; paint(); return; }
    playing = true;
    if (index === clips.length - 1 && video.ended) show(0, 0, true);
    else video.play().catch(() => {});
    paint();
  };
  dialog.querySelector('[data-prev]').onclick = () => show(Math.max(0, (video.currentTime > 1.5 ? index : index - 1)), 0);
  dialog.querySelector('[data-next]').onclick = () => { if (index < clips.length - 1) show(index + 1, 0); };
  seek.addEventListener('input', () => { seeking = true; now.textContent = formatTime(Number(seek.value)); });
  seek.addEventListener('change', () => { seeking = false; seekTo(Number(seek.value)); });
  items.forEach((item, i) => { item.onclick = () => show(i, 0, true); });
  const lang = dialog.querySelector('.mp-lang');
  if (lang) lang.onchange = () => {
    current = tracks.find(t => String(t.key) === lang.value)?.key ?? lang.value;
    show(index, video.currentTime || 0);   // same line, same place, the other language
  };
  const panel = dialog.querySelector('.mp-panel');
  let popover = null;
  function closeMenu() {
    if (!popover) return;
    const opener = popover.previousElementSibling;
    popover.remove();
    popover = null;
    opener?.setAttribute('aria-expanded', 'false');
    opener?.focus();
  }
  function update(i, patch) {
    Object.assign(clips[i], patch);
    const target = items[i]?.querySelector('.mp-card');
    if (target) target.innerHTML = card(clips[i]);
    if (i === index) caption.textContent = clips[i].text || '';
  }
  dialog.querySelectorAll('[data-more]').forEach(button => button.onclick = () => {
    const i = Number(button.dataset.more);
    const reopen = popover?.dataset.for !== String(i);
    closeMenu();
    if (!reopen) return;
    popover = document.createElement('div');
    popover.className = 'mp-menu';
    popover.dataset.for = String(i);
    popover.setAttribute('role', 'group');
    popover.setAttribute('aria-label', `Line ${clips[i].label}`);
    const content = menu(clips[i], i, { close: closeMenu, update });
    if (content) popover.append(content);
    button.after(popover);
    button.setAttribute('aria-expanded', 'true');
    popover.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeMenu(); }
    });
  });
  dialog.querySelector('[data-list]').onclick = e => {
    panelOpen = !panelOpen;
    panel.hidden = !panelOpen;
    e.currentTarget.setAttribute('aria-pressed', String(panelOpen));
  };
  const full = dialog.querySelector('[data-full]');
  full.onclick = () => {
    const screen = dialog.querySelector('.mp-stage');
    if (document.fullscreenElement) document.exitFullscreen?.();
    else screen.requestFullscreen?.();
  };
  const onFullscreen = () => { full.innerHTML = icon(document.fullscreenElement ? 'exit' : 'full'); };
  document.addEventListener('fullscreenchange', onFullscreen);
  dialog.addEventListener('keydown', e => {
    if (e.target.closest('select, input, .mp-menu')) return;
    if (e.key === ' ' || e.key === 'k') { e.preventDefault(); playButton.click(); }
    else if (e.key === 'ArrowRight' && e.shiftKey) dialog.querySelector('[data-next]').click();
    else if (e.key === 'ArrowLeft' && e.shiftKey) dialog.querySelector('[data-prev]').click();
  });
  dialog.querySelector('[data-close]').onclick = () => dialog.close();
  dialog.addEventListener('click', e => { if (e.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => {
    closed = true;
    closeMenu();
    video.pause();
    video.removeAttribute('src');
    document.removeEventListener('fullscreenchange', onFullscreen);
    blobs.forEach(p => p.then(u => URL.revokeObjectURL(u)).catch(() => {}));
    dialog.remove();
    opener?.focus?.();
    onClose?.();
  });
  dialog.showModal();
  show(index, 0, true);
  return dialog;
}
