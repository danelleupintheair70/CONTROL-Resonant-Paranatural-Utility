import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { formatTime, locate, reelLayout } from '../lib/legacy.js';

// A large popup player for any reel of media clips: the video, a timeline with
// a mark at every clip, a side list of the clips (passed, playing, upcoming)
// that jumps on click, and play / replay / fullscreen.
//
// A reel is not a file. It is a list of stretches (a character's lines, a
// scene's exchange), each fetched as its own small clip and played back to
// back, so the timeline is the reel's own time. When the media has several
// audio tracks the reel can switch language at the same place in the same clip.
//
// Mount it to open it; it calls onClose when the person closes it, and the
// owner unmounts it then:
//
//   {player && <MediaPlayer {...player} onClose={() => setPlayer(null)} />}
//
//   title, subtitle, colour   the heading and the accent colour
//   clips:   [{ start, end, label, text, detail, tag, url(track) }]
//   tracks:  [{ key, label }]          (optional) audio languages to switch between
//   track:   the key to start with     (default: the first track)
//   startAt: the clip index to start at
//   menu:    (clip, index, { close, update }) => ReactNode, the "⋯" of each clip
//            (optional); update(index, patch) changes that clip's card.
//   onClose: () => void

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
const Icon = ({ name }) => <svg viewBox="0 0 24 24" aria-hidden="true"><path d={ICONS[name]} /></svg>;

function Card({ clip }) {
  return (
    <span className="mp-card">
      <span className="mp-card-label">{clip.label}{clip.tag && <> <span className="mp-tag">{clip.tag}</span></>}</span>
      {clip.text && <span className="mp-card-text">{clip.text}</span>}
      {clip.detail && <span className="mp-card-detail">{clip.detail}</span>}
    </span>
  );
}

export function MediaPlayer({ title = '', subtitle = '', colour = '', clips: given = [], tracks = [], track = null,
  startAt = 0, menu = null, onClose = null }) {
  const [clips, setClips] = useState(() => given.map(c => ({ ...c })));
  const [layout] = useState(() => reelLayout(given));
  const [index, setIndex] = useState(() => Math.min(Math.max(0, startAt), Math.max(0, given.length - 1)));
  const [current, setCurrent] = useState(track ?? tracks[0]?.key ?? null);
  const [playing, setPlaying] = useState(true);
  const [panelOpen, setPanelOpen] = useState(() => window.innerWidth > 900);
  const [loading, setLoading] = useState('');
  const [time, setTime] = useState(0);
  const [seekValue, setSeekValue] = useState(null);        // set while the thumb is dragged
  const [fullscreen, setFullscreen] = useState(false);
  const [menuFor, setMenuFor] = useState(null);
  const lastMenu = useRef(null);
  const [ended, setEnded] = useState(false);

  const dialogRef = useRef(null);
  const videoRef = useRef(null);
  const blobs = useRef(new Map());                          // url -> Promise<objectURL>
  // What event handlers and the async clip loader need without a re-render.
  const live = useRef({ index, current, playing, closed: false });
  const clipsRef = useRef(clips);
  const onCloseRef = useRef(onClose);
  useLayoutEffect(() => {
    live.current.current = current;
    live.current.playing = playing;
    clipsRef.current = clips;
    onCloseRef.current = onClose;
  });

  const fetchClip = useCallback(i => {
    const url = clipsRef.current[i]?.url(live.current.current);
    if (!url) return Promise.reject(new Error('no clip'));
    if (!blobs.current.has(url)) {
      blobs.current.set(url, fetch(url).then(r => {
        if (!r.ok) throw new Error(`clip ${r.status}`);
        return r.blob();
      }).then(b => URL.createObjectURL(b)).catch(error => { blobs.current.delete(url); throw error; }));
    }
    return blobs.current.get(url);
  }, []);

  const show = useCallback(async (i, offset = 0, play = live.current.playing) => {
    const video = videoRef.current;
    live.current.index = i;
    setIndex(i);
    setEnded(false);
    setLoading('Cutting the clip…');
    try {
      const src = await fetchClip(i);
      if (live.current.closed || live.current.index !== i || !video) return;
      if (video.src !== src) video.src = src;
      video.currentTime = offset;
      setLoading('');
      if (play) await video.play().catch(() => { setPlaying(false); });
      fetchClip(i + 1).catch(() => {});        // the next line is ready when this one ends
    } catch (error) {
      setLoading(`Could not load this clip (${error.message}).`);
    }
  }, [fetchClip]);

  // Open as a modal on mount; the first clip starts at once.
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return undefined;                          // an empty reel renders nothing
    const opener = document.activeElement;
    const video = videoRef.current;
    const state = live.current;
    state.closed = false;
    if (!dialog.open) dialog.showModal();
    show(state.index, 0, true);
    const onFullscreen = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', onFullscreen);
    const onDialogClose = () => {
      state.closed = true;
      video?.pause();
      opener?.focus?.();
      onCloseRef.current?.();
    };
    dialog.addEventListener('close', onDialogClose);
    const cache = blobs.current;
    return () => {
      state.closed = true;
      document.removeEventListener('fullscreenchange', onFullscreen);
      dialog.removeEventListener('close', onDialogClose);
      video?.pause();
      cache.forEach(p => p.then(u => URL.revokeObjectURL(u)).catch(() => {}));
      cache.clear();
    };
  }, [show]);

  useEffect(() => {
    dialogRef.current?.querySelectorAll('.mp-item')[index]?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
  }, [index]);

  useEffect(() => {
    const was = lastMenu.current;
    lastMenu.current = menuFor;
    if (menuFor == null && was != null) dialogRef.current?.querySelector(`[data-more="${was}"]`)?.focus();
  }, [menuFor]);

  if (!given.length) return null;

  const clip = clips[index];
  const reelTime = layout.offsets[index] + Math.min(time, clip.end - clip.start);
  const shownTime = seekValue ?? reelTime;
  const finished = !playing && index === clips.length - 1 && ended;

  function onTimeUpdate() { setTime(videoRef.current?.currentTime || 0); }
  function onEnded() {
    if (live.current.index < clipsRef.current.length - 1) show(live.current.index + 1, 0, true);
    else { setPlaying(false); setEnded(true); }
  }
  function togglePlay() {
    const video = videoRef.current;
    if (playing) { video?.pause(); setPlaying(false); return; }
    setPlaying(true);
    live.current.playing = true;
    if (index === clips.length - 1 && video?.ended) show(0, 0, true);
    else video?.play().catch(() => {});
  }
  const prev = () => show(Math.max(0, ((videoRef.current?.currentTime || 0) > 1.5 ? index : index - 1)), 0);
  const next = () => { if (index < clips.length - 1) show(index + 1, 0); };
  function seekTo(t) {
    const spot = locate(layout, t);
    const video = videoRef.current;
    if (spot.index === index && video?.src) { video.currentTime = spot.offset; setTime(spot.offset); }
    else show(spot.index, spot.offset);
  }
  // A closed menu hands focus back to its "⋯" button.
  const closeMenu = () => setMenuFor(null);
  function update(i, patch) {
    setClips(list => list.map((c, n) => (n === i ? { ...c, ...patch } : c)));
  }
  function onKeyDown(e) {
    if (e.target.closest('select, input, .mp-menu')) return;
    if (e.key === ' ' || e.key === 'k') { e.preventDefault(); togglePlay(); }
    else if (e.key === 'ArrowRight' && e.shiftKey) next();
    else if (e.key === 'ArrowLeft' && e.shiftKey) prev();
  }
  const close = () => dialogRef.current?.close();
  const style = colour ? { '--mp-accent': colour } : undefined;

  return createPortal(
    <dialog className="mp" ref={dialogRef} style={style} onKeyDown={onKeyDown}
      onClick={e => { if (e.target === dialogRef.current) close(); }}>
      <header className="mp-head">
        <div><h2 className="mp-title">{title}</h2><p className="hint mp-sub">{subtitle}</p></div>
        <button type="button" className="mp-icon" aria-label="Close player" onClick={close}><Icon name="close" /></button>
      </header>
      <div className="mp-stage">
        <div className="mp-screen">
          <video className="mp-video" playsInline preload="auto" ref={videoRef} onTimeUpdate={onTimeUpdate} onEnded={onEnded} />
          <p className="mp-caption" aria-live="polite">{clip.text || ''}</p>
          <p className="mp-loading hint" hidden={!loading}>{loading}</p>
          <div className="mp-bar">
            <button type="button" className="mp-icon" aria-label="Previous clip" onClick={prev}><Icon name="prev" /></button>
            <button type="button" className="mp-icon" aria-label={playing ? 'Pause' : finished ? 'Play again' : 'Play'} onClick={togglePlay}>
              <Icon name={playing ? 'pause' : finished ? 'replay' : 'play'} /></button>
            <button type="button" className="mp-icon" aria-label="Next clip" onClick={next}><Icon name="next" /></button>
            <span className="mp-time m"><span>{formatTime(shownTime)}</span> / {formatTime(layout.total)}</span>
            <div className="mp-track">
              <div className="mp-marks" aria-hidden="true">
                {layout.offsets.map((o, i) => <span key={i} className="mp-mark" style={{ left: `${(o / (layout.total || 1)) * 100}%` }} title={clips[i].label} />)}
              </div>
              <input type="range" className="mp-seek" min="0" max={layout.total.toFixed(2)} step="0.05" aria-label="Position in the reel"
                value={shownTime.toFixed(2)} style={{ '--mp-fill': `${(reelTime / (layout.total || 1)) * 100}%` }}
                onChange={e => setSeekValue(Number(e.target.value))}
                onPointerUp={e => { setSeekValue(null); seekTo(Number(e.currentTarget.value)); }}
                onKeyUp={e => { setSeekValue(null); seekTo(Number(e.currentTarget.value)); }} />
            </div>
            {tracks.length > 1 && (
              <select className="mp-lang" aria-label="Audio language" value={String(current)}
                onChange={e => {
                  const key = tracks.find(t => String(t.key) === e.target.value)?.key ?? e.target.value;
                  live.current.current = key;
                  setCurrent(key);
                  show(index, videoRef.current?.currentTime || 0);   // same line, same place, the other language
                }}>
                {tracks.map(t => <option key={t.key} value={String(t.key)}>{t.label}</option>)}
              </select>
            )}
            <button type="button" className="mp-icon" aria-label="Clip list" aria-pressed={panelOpen ? 'true' : 'false'}
              onClick={() => setPanelOpen(!panelOpen)}><Icon name="list" /></button>
            <button type="button" className="mp-icon" aria-label="Fullscreen" onClick={() => {
              if (document.fullscreenElement) document.exitFullscreen?.();
              else dialogRef.current?.querySelector('.mp-stage')?.requestFullscreen?.();
            }}><Icon name={fullscreen ? 'exit' : 'full'} /></button>
          </div>
        </div>
        <ol className="mp-panel" hidden={!panelOpen}>
          {clips.map((c, i) => (
            <li key={i} className="mp-row">
              <button type="button"
                className={`mp-item${i === index ? ' is-active' : ''}${i < index ? ' is-passed' : ''}`} onClick={() => show(i, 0, true)}>
                <span className="mp-dot" aria-hidden="true" />
                <Card clip={c} />
              </button>
              {menu && (
                <button type="button" className="mp-icon mp-more" data-more={i}
                  aria-label={`More for ${c.label}`} aria-haspopup="true" aria-expanded={menuFor === i ? 'true' : 'false'}
                  onClick={() => (menuFor === i ? closeMenu() : setMenuFor(i))}><Icon name="more" /></button>
              )}
              {menu && menuFor === i && (
                <div className="mp-menu" role="group" aria-label={`Line ${c.label}`}
                  onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeMenu(); } }}>
                  {menu(c, i, { close: closeMenu, update })}
                </div>
              )}
            </li>
          ))}
        </ol>
      </div>
    </dialog>,
    document.getElementById('app') || document.body,
  );
}
