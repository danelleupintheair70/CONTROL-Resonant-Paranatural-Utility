import { apiUrl } from './api.js';
import { safeGet } from './dom.js';

// The studio's one playback owner.
//
// Exactly one <audio> element plays; the picture is a muted <video> proxy that
// follows it. Switching source converts the playhead through the target
// timeline (every source is cut for the same target window, and a reference is
// mapped through its alignment on the server), so A/B keeps the same moment
// rather than the same byte offset. Leaving the studio stops everything.

const key = () => {
  const stored = safeGet('doblarr_api_key', '');
  return stored ? `&api_key=${encodeURIComponent(stored)}` : '';
};

export function createStudioPlayer({ audio, video, onChange }) {
  let sessionId = '', jobId = '', windowSpan = null, sources = [], current = null;
  let loop = null, sequence = null, matched = false, epoch = 0;

  const emit = (what, detail = {}) => onChange?.(what, detail);

  function sourceUrl(source) {
    if (source.url) return source.url;
    const q = new URLSearchParams({ source: source.id, start: windowSpan.start.toFixed(3),
      end: windowSpan.end.toFixed(3) });
    if (jobId) q.set('job_id', jobId);
    return `${apiUrl(`studio/sessions/${sessionId}/media/audio`)}?${q}${key()}`;
  }

  function videoUrl() {
    const q = new URLSearchParams({ start: windowSpan.start.toFixed(3),
      end: windowSpan.end.toFixed(3) });
    return `${apiUrl(`studio/sessions/${sessionId}/media/video`)}?${q}${key()}`;
  }

  // Scene time is seconds on the target timeline; each clip starts at the
  // window start, so the conversion is the same for every source.
  const sceneTime = () => (windowSpan ? windowSpan.start + (audio.currentTime || 0) : 0);

  function applyLevel() {
    const gain = matched && current?.level_db != null ? Math.pow(10, (-20 - current.level_db) / 20) : 1;
    audio.volume = Math.max(0, Math.min(1, gain));
  }

  async function load(source, { keep = true, play = null } = {}) {
    if (!source || !windowSpan) return false;
    const version = ++epoch;
    const wasPlaying = play ?? (!audio.paused && !audio.ended);
    const at = keep ? audio.currentTime : 0;
    current = source;
    audio.pause();
    emit('loading', { source });
    audio.src = sourceUrl(source);
    applyLevel();
    try {
      await new Promise((resolve, reject) => {
        const ok = () => { off(); resolve(); };
        const bad = () => { off(); reject(new Error(`${source.label} could not be played here.`)); };
        function off() { audio.removeEventListener('loadedmetadata', ok); audio.removeEventListener('error', bad); }
        audio.addEventListener('loadedmetadata', ok, { once: true });
        audio.addEventListener('error', bad, { once: true });
        audio.load();
      });
    } catch (error) {
      if (version === epoch) emit('error', { source, message: error.message });
      return false;
    }
    if (version !== epoch) return false;
    if (at && Number.isFinite(audio.duration)) audio.currentTime = Math.min(at, Math.max(0, audio.duration - 0.05));
    follow();
    emit('ready', { source });
    if (wasPlaying) { try { await audio.play(); } catch { /* needs a gesture */ } }
    return true;
  }

  function follow() {
    if (!video || !video.src) return;
    const want = audio.currentTime || 0;
    if (Math.abs((video.currentTime || 0) - want) > 0.15) {
      try { video.currentTime = want; } catch { /* not seekable yet */ }
    }
    if (audio.paused && !video.paused) video.pause();
    if (!audio.paused && video.paused) video.play().catch(() => {});
  }

  audio.addEventListener('timeupdate', () => {
    const t = audio.currentTime || 0;
    if (loop && t >= loop.end - windowSpan.start) audio.currentTime = Math.max(0, loop.start - windowSpan.start);
    if (sequence && t >= sequence.end - windowSpan.start) {
      sequence.at += 1;
      if (sequence.at >= sequence.order.length) { sequence = null; audio.pause(); emit('sequence', { done: true }); }
      else {
        const next = sequence.order[sequence.at];
        const start = sequence.start;
        load(next, { keep: false, play: true }).then(ok => {
          if (ok) audio.currentTime = Math.max(0, start - windowSpan.start);
        });
        emit('sequence', { source: next });
      }
    }
    follow();
    emit('time', { t: sceneTime() });
  });
  ['play', 'pause', 'seeked'].forEach(ev => audio.addEventListener(ev, () => { follow(); emit(ev); }));

  return {
    get source() { return current; },
    get window() { return windowSpan; },
    get time() { return sceneTime(); },
    get paused() { return audio.paused; },
    get matched() { return matched; },
    get sequence() { return sequence; },
    get loop() { return loop; },
    attach({ session, job, span, list, showVideo = true }) {
      sessionId = session; jobId = job || ''; windowSpan = span; sources = list;
      loop = null; sequence = null;
      if (video) {
        if (showVideo) { video.src = videoUrl(); video.muted = true; video.load(); }
        else { video.removeAttribute('src'); video.load(); }
      }
    },
    sources: () => sources,
    load,
    async select(id, opts) { const s = sources.find(x => x.id === id); return s ? load(s, opts) : false; },
    toggle() { if (audio.paused) audio.play().catch(() => {}); else audio.pause(); },
    seek(t) {
      if (!windowSpan) return;
      const local = Math.max(0, t - windowSpan.start);
      audio.currentTime = Number.isFinite(audio.duration) ? Math.min(local, Math.max(0, audio.duration - 0.03)) : local;
      follow();
    },
    setLoop(span) { loop = span; if (span) this.seek(span.start); emit('loop', { span }); },
    setMatched(on) { matched = !!on; applyLevel(); emit('matched', { on: matched }); },
    playSequence(span, order) {
      if (!order.length) return;
      sequence = { start: span.start, end: span.end, order, at: 0 };
      load(order[0], { keep: false, play: true }).then(ok => {
        if (ok) audio.currentTime = Math.max(0, span.start - windowSpan.start);
      });
      emit('sequence', { source: order[0] });
    },
    stop() {
      epoch += 1; sequence = null; loop = null;
      audio.pause(); audio.removeAttribute('src'); audio.load();
      if (video) { video.pause(); video.removeAttribute('src'); video.load(); }
    },
  };
}
