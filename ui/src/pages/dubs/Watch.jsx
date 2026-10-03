import { useCallback, useEffect, useRef, useState } from 'react';
import { useLoaderData, useParams } from 'react-router';
import { api, apiUrl } from '../../lib/api.js';
import { safeGet } from '../../lib/storage.js';

// One finished dub, watched in the browser (doblarr/watch.py): every audio
// track one click away at the same moment, the original's subtitles, the
// places where the dub is clearly quieter than the original, and notes kept
// with the dub. "O" flips between the dub and the original at the same time,
// "N" starts a note at the current moment.

const clock = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const CATEGORIES = [['', 'Kind'], ['lost sound', 'Sound lost'], ['overlap', 'Voices overlap'],
  ['timing', 'Timing'], ['voice', 'Wrong or odd voice'], ['translation', 'Translation'],
  ['level', 'Too loud or quiet'], ['other', 'Other']];
const RESOLUTIONS = ['open', 'fixed', "won't fix"];

const fetchWatch = (id, retry = false) => api(`watch/${encodeURIComponent(id)}${retry ? '?retry=true' : ''}`);

export async function watchLoader({ params }) {
  try { return { data: await fetchWatch(params.id), error: '' }; }
  catch (error) { return { data: null, error: error.message }; }
}

function label(track) {
  if (track.ours) return `${track.title || 'Dub'} (Doblarr)`;
  return track.title || track.lang || `Track ${track.stream}`;
}

function key() {
  const value = safeGet('doblarr_api_key', '');
  return value ? `?api_key=${encodeURIComponent(value)}` : '';
}

function Player({ jobId, data, reload }) {
  const ours = data.tracks.find(t => t.ours) || data.tracks[0];
  const original = data.tracks.find(t => t.original);
  const [current, setCurrent] = useState(ours?.stream);
  const [length, setLength] = useState(() =>
    data.loudness?.curves?.ours?.length * (data.loudness?.window || 0.25) || 1);
  const [playhead, setPlayhead] = useState(0);
  const [at, setAt] = useState('0:00');
  const video = useRef(null);
  const form = useRef(null);
  const resume = useRef(null);     // where to pick up after a language switch
  const loud = data.loudness || { spans: [] };
  const src = stream => `${apiUrl(`watch/${encodeURIComponent(jobId)}/audio/${stream}.mp4`)}${key()}`;

  const switchTo = useCallback(stream => {
    if (stream === current) return;
    const v = video.current;
    resume.current = { time: v.currentTime, playing: !v.paused };
    setCurrent(stream);
  }, [current]);

  function onMetadata() {
    const v = video.current;
    if (v.duration) setLength(v.duration);
    if (resume.current) {
      v.currentTime = resume.current.time;
      if (resume.current.playing) v.play().catch(() => {});
      resume.current = null;
    }
  }

  function onTime() {
    const v = video.current;
    setPlayhead(v.currentTime);
    if (document.activeElement?.name !== 'note') setAt(clock(v.currentTime));
  }

  const seek = (time, compare = false) => {
    video.current.currentTime = Math.max(0, time - (compare ? 1 : 0));
    video.current.play().catch(() => {});
  };

  useEffect(() => {
    const oursTrack = data.tracks.find(t => t.ours);
    const onKey = e => {
      if (e.target.closest?.('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 'o' || e.key === 'O') {
        if (oursTrack && original) switchTo(current === oursTrack.stream ? original.stream : oursTrack.stream);
      } else if (e.key === 'n' || e.key === 'N') {
        e.preventDefault();
        video.current.pause();
        setAt(clock(video.current.currentTime));
        form.current.elements.note.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [current, data.tracks, original, switchTo]);

  async function keepTime(action) {
    const time = video.current.currentTime;
    try {
      await action();
      await reload();
      if (video.current) video.current.currentTime = time;
    } catch (error) { window.alert(error.message); }
  }

  function saveNote(e) {
    e.preventDefault();
    const fields = Object.fromEntries(new FormData(form.current));
    const track = data.tracks.find(t => t.stream === current);
    keepTime(() => api(`watch/${encodeURIComponent(jobId)}/notes`, { method: 'POST', json: {
      ...fields, at: Math.round(video.current.currentTime * 100) / 100, track: track ? label(track) : '' } }));
  }

  const resolve = (note, resolution) => keepTime(() => api(
    `watch/${encodeURIComponent(jobId)}/notes/${encodeURIComponent(note.id)}`,
    { method: 'PATCH', json: { resolution, base_revision: Number(note.revision) } }));

  const mark = (left, width) => ({ left: `${left / length * 100}%`, width: `${Math.max(0.25, width / length * 100)}%` });
  const originalName = original ? label(original) : 'the original';

  return (
    <>
      <header className="watch-head">
        <div><h2>{data.job.title}</h2><p className="hint">{data.job.output}</p></div>
        <div className="watch-langs" role="group" aria-label="Audio language">
          {data.tracks.map(t => (
            <button key={t.stream} type="button" className={`watch-lang${t.ours ? ' watch-lang-ours' : ''}`} data-stream={t.stream}
              aria-pressed={t.stream === current ? 'true' : 'false'} onClick={() => switchTo(t.stream)}>{label(t)}</button>
          ))}
        </div>
      </header>
      <div className="watch-stage">
        <video ref={video} className="watch-video" controls preload="metadata" src={src(current)}
          onLoadedMetadata={onMetadata} onTimeUpdate={onTime}>
          {data.subtitles.map(s => (
            <track key={s.stream} kind="subtitles" label={s.title || s.lang} srcLang={s.lang}
              src={`${apiUrl(`watch/${encodeURIComponent(jobId)}/subtitles/${s.stream}.vtt`)}${key()}`} />
          ))}
        </video>
        <div className="watch-strip" aria-label="Where the dub is quieter than the original, and notes">
          {loud.spans.map(s => (
            <button key={`q${s.start}`} type="button" className="watch-mark watch-quiet" style={mark(s.start, s.end - s.start)}
              title={`${clock(s.start)}: ours ${s.quieter_db} dB quieter than the original`} onClick={() => seek(s.start)} />
          ))}
          {data.notes.map(n => (
            <button key={`n${n.id}`} type="button" className={`watch-mark watch-note-mark${n.resolution === 'open' ? '' : ' watch-note-done'}`}
              style={mark(n.at, 0)} title={`${clock(n.at)}: ${n.note || n.category}`} onClick={() => seek(n.at)} />
          ))}
          <span className="watch-head-line" style={{ left: `${playhead / length * 100}%` }} />
        </div>
        <p className="hint watch-keys"><kbd>O</kbd> switches between the dub and {originalName} at the same moment · <kbd>N</kbd> writes a note here</p>
      </div>
      <form className="watch-note" ref={form} onSubmit={saveNote}>
        <span className="m">{at}</span>
        <select className="input" name="category" aria-label="What is wrong">
          {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select className="input" name="severity" aria-label="How much it matters" defaultValue="noticeable">
          <option value="minor">Minor</option><option value="noticeable">Noticeable</option><option value="major">Major</option>
        </select>
        <select className="input" name="in_original" aria-label="Is it like this in the original?">
          <option value="">In the original?</option><option value="no">Not in the original</option>
          <option value="yes">Also in the original</option><option value="not sure">Not sure</option>
        </select>
        <input className="input" name="note" placeholder="What you heard, e.g. the laugh is gone" aria-label="Note" maxLength={2000} />
        <button type="submit" className="btn btn-primary">Save note</button>
      </form>
      <div className="watch-columns">
        <section aria-label="Notes"><h3>Notes <span className="hint">{data.notes.length}</span></h3>
          {data.notes.length ? (
            <ul className="watch-list">
              {data.notes.map(n => (
                <li key={n.id} className={n.resolution === 'open' ? '' : 'watch-done'}>
                  <button type="button" className="watch-time m" onClick={() => seek(n.at)}>{clock(n.at)}</button>
                  <span>{n.category && <><strong>{CATEGORIES.find(c => c[0] === n.category)?.[1] || n.category}</strong> · </>}{n.note}
                    <span className="hint">{n.severity}{n.in_original ? ` · in original: ${n.in_original}` : ''}{n.track ? ` · heard on ${n.track}` : ''}</span></span>
                  <select className="input" aria-label="State of this note" value={n.resolution} onChange={e => resolve(n, e.target.value)}>
                    {RESOLUTIONS.map(r => <option key={r} value={r}>{r}</option>)}
                  </select>
                </li>
              ))}
            </ul>
          ) : <p className="hint">Nothing noted yet. Pause where something sounds wrong and press N.</p>}
        </section>
        <section aria-label="Where the dub is quieter"><h3>Quieter than the original <span className="hint">{loud.spans.length}</span></h3>
          <p className="hint">Places where the dub is at least 9 dB below {originalName}
            {loud.offset_db ? ` (after taking out an overall ${loud.offset_db} dB)` : ''}: a laugh or a sound nobody voiced, or the music dipping.</p>
          <ul className="watch-list watch-quiet-list">
            {loud.spans.slice(0, 200).map(s => (
              <li key={s.start}>
                <button type="button" className="watch-time m" onClick={() => seek(s.start, true)}>{clock(s.start)}</button>
                <span>{(s.end - s.start).toFixed(1)} s, {s.quieter_db} dB quieter</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </>
  );
}

export function Watch() {
  const { id } = useParams();
  return <WatchPage key={id} id={id} />;
}

function WatchPage({ id }) {
  const [state, setState] = useState(useLoaderData());

  const reload = useCallback(async (retry = false) => {
    try { setState({ data: await fetchWatch(id, retry), error: '' }); }
    catch (error) { setState({ data: null, error: error.message }); }
  }, [id]);

  // The browser copy is made once per dub; poll until it is ready.
  const waiting = state.data && state.data.state !== 'ready' && !state.data.state.startsWith('failed');
  useEffect(() => {
    if (!waiting) return undefined;
    const timer = setTimeout(() => reload(), 3000);
    return () => clearTimeout(timer);
  }, [waiting, state, reload]);

  let body;
  if (state.error) body = <p className="hint">{state.error}</p>;
  else if (state.data.state !== 'ready') {
    const failed = state.data.state.startsWith('failed');
    body = (
      <div className="watch-wait"><h2>{state.data.job.title}</h2>
        <p className="hint">{failed ? state.data.state : 'Making a copy any browser can play (once per dub, about a minute)…'}</p>
        {failed && <button type="button" className="btn btn-secondary" onClick={() => reload(true)}>Try again</button>}
      </div>
    );
  } else body = <Player key={id} jobId={id} data={state.data} reload={reload} />;
  return <div id="watchRoot" className="watch">{body}</div>;
}
