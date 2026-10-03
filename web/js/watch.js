import { api, apiUrl } from './api.js';
import { escapeHtml as esc, safeGet } from './dom.js';

// One finished dub, watched in the browser (doblarr/watch.py): every audio
// track one click away at the same moment, the original's subtitles, the
// places where the dub is clearly quieter than the original, and notes kept
// with the dub. "O" flips between the dub and the original at the same time,
// "N" starts a note at the current moment.

const clock = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const CATEGORIES = [['', 'Kind'], ['lost sound', 'Sound lost'], ['overlap', 'Voices overlap'],
  ['timing', 'Timing'], ['voice', 'Wrong or odd voice'], ['translation', 'Translation'],
  ['level', 'Too loud or quiet'], ['other', 'Other']];

function label(track) {
  if (track.ours) return `${track.title || 'Dub'} (Doblarr)`;
  return track.title || track.lang || `Track ${track.stream}`;
}

function key() {
  const value = safeGet('doblarr_api_key', '');
  return value ? `?api_key=${encodeURIComponent(value)}` : '';
}

export async function renderWatch(root, jobId) {
  root.innerHTML = '<p class="hint">Opening the dub…</p>';
  let data;
  let current = null;
  let timer = null;

  async function load(retry = false) {
    try {
      data = await api(`watch/${encodeURIComponent(jobId)}${retry ? '?retry=true' : ''}`);
    } catch (error) {
      root.innerHTML = `<p class="hint">${esc(error.message)}</p>`;
      return;
    }
    if (data.state !== 'ready') {
      const failed = data.state.startsWith('failed');
      root.innerHTML = `<div class="watch-wait"><h2>${esc(data.job.title)}</h2>
        <p class="hint">${failed ? esc(data.state) : 'Making a copy any browser can play (once per dub, about a minute)…'}</p>
        ${failed ? '<button type="button" class="btn btn-secondary" data-retry>Try again</button>' : ''}</div>`;
      root.querySelector('[data-retry]')?.addEventListener('click', () => load(true));
      if (!failed) timer = setTimeout(load, 3000);
      return;
    }
    draw();
  }

  function src(stream) {
    return `${apiUrl(`watch/${encodeURIComponent(jobId)}/audio/${stream}.mp4`)}${key()}`;
  }

  function draw() {
    const ours = data.tracks.find(t => t.ours) || data.tracks[0];
    const original = data.tracks.find(t => t.original);
    current = current ?? ours?.stream;
    const loud = data.loudness || { spans: [] };
    root.innerHTML = `
      <header class="watch-head">
        <div><h2>${esc(data.job.title)}</h2><p class="hint">${esc(data.job.output)}</p></div>
        <div class="watch-langs" role="group" aria-label="Audio language">${data.tracks.map(t => `
          <button type="button" class="watch-lang${t.ours ? ' watch-lang-ours' : ''}" data-stream="${t.stream}" aria-pressed="${t.stream === current}">${esc(label(t))}</button>`).join('')}</div>
      </header>
      <div class="watch-stage">
        <video class="watch-video" controls preload="metadata" src="${src(current)}">
          ${data.subtitles.map(s => `<track kind="subtitles" label="${esc(s.title || s.lang)}" srclang="${esc(s.lang)}" src="${apiUrl(`watch/${encodeURIComponent(jobId)}/subtitles/${s.stream}.vtt`)}${key()}">`).join('')}
        </video>
        <div class="watch-strip" data-strip aria-label="Where the dub is quieter than the original, and notes">
          ${loud.spans.map(s => `<button type="button" class="watch-mark watch-quiet" data-seek="${s.start}" title="${clock(s.start)}: ours ${s.quieter_db} dB quieter than the original" data-left="${s.start}" data-width="${s.end - s.start}"></button>`).join('')}
          ${data.notes.map(n => `<button type="button" class="watch-mark watch-note-mark${n.resolution === 'open' ? '' : ' watch-note-done'}" data-seek="${n.at}" title="${clock(n.at)}: ${esc(n.note || n.category)}" data-left="${n.at}" data-width="0"></button>`).join('')}
          <span class="watch-head-line" data-playhead></span>
        </div>
        <p class="hint watch-keys"><kbd>O</kbd> switches between the dub and ${esc(original ? label(original) : 'the original')} at the same moment · <kbd>N</kbd> writes a note here</p>
      </div>
      <form class="watch-note" data-note-form>
        <span class="m" data-note-at>0:00</span>
        <select class="input" name="category" aria-label="What is wrong">${CATEGORIES.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select>
        <select class="input" name="severity" aria-label="How much it matters"><option value="minor">Minor</option><option value="noticeable" selected>Noticeable</option><option value="major">Major</option></select>
        <select class="input" name="in_original" aria-label="Is it like this in the original?"><option value="">In the original?</option><option value="no">Not in the original</option><option value="yes">Also in the original</option><option value="not sure">Not sure</option></select>
        <input class="input" name="note" placeholder="What you heard, e.g. the laugh is gone" aria-label="Note" maxlength="2000">
        <button type="submit" class="btn btn-primary">Save note</button>
      </form>
      <div class="watch-columns">
        <section aria-label="Notes"><h3>Notes <span class="hint">${data.notes.length}</span></h3>
          ${data.notes.length ? `<ul class="watch-list">${data.notes.map(n => `<li class="${n.resolution === 'open' ? '' : 'watch-done'}">
            <button type="button" class="watch-time m" data-seek="${n.at}">${clock(n.at)}</button>
            <span>${n.category ? `<strong>${esc(CATEGORIES.find(c => c[0] === n.category)?.[1] || n.category)}</strong> · ` : ''}${esc(n.note)}
              <span class="hint">${esc(n.severity)}${n.in_original ? ` · in original: ${esc(n.in_original)}` : ''}${n.track ? ` · heard on ${esc(n.track)}` : ''}</span></span>
            <select class="input" data-resolve="${esc(n.id)}" data-revision="${n.revision}" aria-label="State of this note">
              ${['open', 'fixed', "won't fix"].map(r => `<option value="${r}" ${r === n.resolution ? 'selected' : ''}>${r}</option>`).join('')}</select></li>`).join('')}</ul>`
            : '<p class="hint">Nothing noted yet. Pause where something sounds wrong and press N.</p>'}
        </section>
        <section aria-label="Where the dub is quieter"><h3>Quieter than the original <span class="hint">${loud.spans.length}</span></h3>
          <p class="hint">Places where the dub is at least 9 dB below ${esc(original ? label(original) : 'the original')}${loud.offset_db ? ` (after taking out an overall ${loud.offset_db} dB)` : ''}: a laugh or a sound nobody voiced, or the music dipping.</p>
          <ul class="watch-list watch-quiet-list">${loud.spans.slice(0, 200).map(s => `<li>
            <button type="button" class="watch-time m" data-seek="${s.start}" data-compare>${clock(s.start)}</button>
            <span>${(s.end - s.start).toFixed(1)} s, ${s.quieter_db} dB quieter</span></li>`).join('')}</ul>
        </section>
      </div>`;
    wire(original);
  }

  function wire(original) {
    const video = root.querySelector('video');
    const strip = root.querySelector('[data-strip]');
    const at = root.querySelector('[data-note-at]');
    const form = root.querySelector('[data-note-form]');
    const placeMarks = () => {
      const length = video.duration || data.loudness?.curves?.ours?.length * (data.loudness?.window || 0.25) || 1;
      strip.querySelectorAll('[data-left]').forEach(m => {
        m.style.left = `${Number(m.dataset.left) / length * 100}%`;
        m.style.width = `${Math.max(0.25, Number(m.dataset.width) / length * 100)}%`;
      });
      return length;
    };
    let length = placeMarks();
    video.addEventListener('loadedmetadata', () => { length = placeMarks(); });
    video.addEventListener('timeupdate', () => {
      root.querySelector('[data-playhead]').style.left = `${video.currentTime / length * 100}%`;
      if (document.activeElement?.name !== 'note') at.textContent = clock(video.currentTime);
    });
    const switchTo = stream => {
      if (stream === current) return;
      const time = video.currentTime;
      const playing = !video.paused;
      current = stream;
      video.src = src(stream);
      video.addEventListener('loadedmetadata', () => {
        video.currentTime = time;
        if (playing) video.play().catch(() => {});
      }, { once: true });
      root.querySelectorAll('[data-stream]').forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.stream) === stream)));
    };
    root.querySelectorAll('[data-stream]').forEach(b => b.onclick = () => switchTo(Number(b.dataset.stream)));
    root.querySelectorAll('[data-seek]').forEach(b => b.onclick = () => {
      video.currentTime = Math.max(0, Number(b.dataset.seek) - (b.hasAttribute('data-compare') ? 1 : 0));
      video.play().catch(() => {});
    });
    const ours = data.tracks.find(t => t.ours);
    const onKey = e => {
      if (!document.body.contains(root) || root.closest('[hidden]')) { document.removeEventListener('keydown', onKey); return; }
      if (e.target.closest('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 'o' || e.key === 'O') {
        if (ours && original) switchTo(current === ours.stream ? original.stream : ours.stream);
      } else if (e.key === 'n' || e.key === 'N') {
        e.preventDefault();
        video.pause();
        at.textContent = clock(video.currentTime);
        form.elements.note.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    form.onsubmit = async e => {
      e.preventDefault();
      const fields = Object.fromEntries(new FormData(form));
      const track = data.tracks.find(t => t.stream === current);
      try {
        await api(`watch/${encodeURIComponent(jobId)}/notes`, { method: 'POST', json: {
          ...fields, at: Math.round(video.currentTime * 100) / 100, track: track ? label(track) : '' } });
        const time = video.currentTime;
        await load();
        root.querySelector('video').currentTime = time;
      } catch (error) { window.alert(error.message); }
    };
    root.querySelectorAll('[data-resolve]').forEach(s => s.onchange = async () => {
      try {
        await api(`watch/${encodeURIComponent(jobId)}/notes/${encodeURIComponent(s.dataset.resolve)}`, {
          method: 'PATCH', json: { resolution: s.value, base_revision: Number(s.dataset.revision) } });
        const time = video.currentTime;
        await load();
        root.querySelector('video').currentTime = time;
      } catch (error) { window.alert(error.message); }
    });
  }

  clearTimeout(timer);
  load();
}
