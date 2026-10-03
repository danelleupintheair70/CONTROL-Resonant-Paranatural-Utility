import { useState } from 'react';
import { api } from '../../lib/legacy.js';
import { isShow } from '../../lib/library.js';
import { LangChips } from './parts.jsx';

// What the show was made in; saving overrides detection, blank detects again.
function OriginalLanguage({ item }) {
  const [lang, setLang] = useState(item.original === '??' ? '' : item.original || '');
  const [status, setStatus] = useState('');
  async function submit(e) {
    e.preventDefault();
    const value = lang.trim().toLowerCase();
    try {
      await api(`series/${item.tvdb_id || item.parent.tvdb_id}/original-language`, { method: 'PUT', json: { lang: value } });
      setStatus(value ? `Saved: ${value}. New jobs and analyses start from it.` : 'Cleared; it is detected from the files again.');
    } catch (error) { setStatus(error.message); }
  }
  return (
    <div className="panel title-panel">
      <h3 className="meta-heading">Original language</h3>
      <p className="title-panel-sub meta-sub">What the show was made in: the audio a dub and an analysis start from. When the library does not say, it is read from the episode files (the default track, tracks titled as dubs, subtitles that only a dub needs) and kept for the show. Set it here to override; leave it blank to detect again.</p>
      <form className="original-form" data-original-form onSubmit={submit}>
        <input className="input m" data-original value={lang} onChange={e => setLang(e.target.value)} maxLength={2} size={4}
          placeholder="ja" aria-label="Original language (two letters)" />
        <button type="submit" className="btn btn-secondary">Save</button>
        <span className="hint" role="status" data-original-status>{status}</span>
      </form>
    </div>
  );
}

export function MetaTab({ item, targets }) {
  const show = isShow(item);
  const langs = item.audio_langs?.length ? item.audio_langs.join(' · ') : (item.existing_audio || item.original);
  const facts = [
    ['Type', item.episode_id ? 'Episode (single file)' : show ? 'Series (per-episode files)' : 'Film (single file)'],
    ['Source', item.source],
    ['Year', item.year || '—'],
    ['Original language', item.original],
    ['Audio tracks present', langs],
    ['Target languages', targets.join(', ') || '—'],
    ['Plex label', item.label],
    ['Auto-dub', item.auto_dub ? 'On' : 'Off'],
    ['Path', item.path || '—'],
    ['TMDB id', item.tmdb_id || '—'],
    ['TVDB id', item.tvdb_id || '—'],
  ];
  return (
    <div className="meta-stack">
      <div className="panel title-panel">
        <h3 className="meta-heading">Matched metadata</h3>
        <p className="title-panel-sub meta-sub">Read from {item.source} — used to pick the source language and the voice profile.</p>
        {facts.map(([k, v]) => (
          <div key={k} className="frow meta-row">
            <div className="flabel meta-label">{k}</div>
            <div className="m meta-value">{String(v)}</div>
          </div>
        ))}
      </div>
      {(item.tvdb_id || item.parent?.tvdb_id) && <OriginalLanguage item={item} />}
      <div className="panel title-panel">
        <h3 className="meta-heading meta-heading-chips">Audio languages</h3>
        <LangChips item={item} targets={targets} />
        <p className="meta-note">Dashed chips are target languages with no audio track yet — that&apos;s what a dub adds.</p>
      </div>
    </div>
  );
}
