import { useRef, useState } from 'react';
import { Link, redirect, useLoaderData, useNavigate } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { ensure, libraryQuery } from '../../lib/queries.js';
import { api, characterFor, seriesOfShow, showOfSeries } from '../../lib/legacy.js';
import { CharacterPicker } from '../../components/CharacterPicker.jsx';
import { catalogQuery, charactersQuery, invalidateVoices, voiceQuery } from './queries.js';
import { ColourField, HearPanel, UsedPanel, VoiceOrb, voiceTitle } from './VoiceParts.jsx';

// A voice of the catalogue. Cast as a character, its page is the
// character's; otherwise: hear it, say what it is, cast it.

const AGES = ['unknown', 'child', 'young', 'adult', 'older'];
const GENDERS = ['unknown', 'male', 'female', 'neutral'];

export async function voiceLoader({ params }) {
  const [data, , characters] = await Promise.all([ensure(voiceQuery(params.key)), ensure(catalogQuery), ensure(charactersQuery)]);
  const owner = characterFor(data.voice, characters);
  if (owner) throw redirect(`/voices/character:${encodeURIComponent(owner.id)}`);
  return { key: params.key };
}

// Shows and films a voice can be cast for, from the library scan.
export function castChoices(items) {
  return (items || []).filter(i => (i.media_type === 'show' && i.tvdb_id) || (i.media_type === 'movie' && i.tmdb_id))
    .map(i => ({ id: i.media_type === 'show' ? `show:tvdb:${i.tvdb_id}` : `movie:tmdb:${i.tmdb_id}`, label: i.title }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

function CastAs({ voice }) {
  const navigate = useNavigate();
  const { data: characters = [] } = useQuery(charactersQuery);
  const { data: library } = useQuery(libraryQuery);
  const shows = castChoices(library?.items);
  const [series, setSeries] = useState(seriesOfShow(voice.show));
  const [status, setStatus] = useState('');
  const cast = characters.filter(c => c.series_id === series).map(c => ({ name: c.name, lines: 0, episodes: 0 }));

  async function castAs(name) {
    if (!name) return;
    if (!series) { setStatus('Choose the show first.'); return; }
    setStatus(`Casting ${voiceTitle(voice)} as ${name}…`);
    try {
      const chosen = voice.profile_id ? { profile_id: voice.profile_id, engine: voice.engine }
        : await api('voice-catalog/select', { method: 'POST', json: { key: voice.key } });
      const made = await api('characters', { method: 'POST', json: { series_id: series, name } });
      await api(`characters/${encodeURIComponent(made.id)}/assignments`, { method: 'PUT',
        json: { voice: chosen.profile_id, engine: chosen.engine || voice.engine || '' } });
      await api('voice-catalog/traits', { method: 'PUT', json: { key: voice.key, character: made.name,
        show: showOfSeries(series) || voice.show || '', show_name: shows.find(s => s.id === series)?.label || voice.show_name || '',
        display_name: voice.display_name || made.name } });
      invalidateVoices();
      navigate(`/voices/${encodeURIComponent(`character:${made.id}`)}`);
    } catch (error) { setStatus(error.message); }
  }

  return (
    <section className="panel voice-panel" aria-labelledby="voiceCastAs">
      <h3 id="voiceCastAs">Cast as a character</h3>
      <div className="voice-cast-as">
        <label className="review-field">Show or film
          <select className="input" data-cast-series value={series} onChange={e => setSeries(e.target.value)}>
            <option value="">Choose one</option>
            {shows.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select></label>
        <CharacterPicker key={series} label="Cast as" value="" cast={cast} suggestions={[]}
          placeholder={series ? 'Pick or type a character' : 'Choose a show first'} onPick={castAs} />
      </div>
      <p className="hint" role="status" data-cast-status>{status}</p>
    </section>
  );
}

function AboutVoice({ voice, orbRef }) {
  const [traits, setTraits] = useState({ display_name: voice.display_name || '', gender: voice.gender || 'unknown',
    age: voice.age || 'unknown', notes: voice.notes || '' });
  const [colour, setColour] = useState(voice.color || '');
  const [saved, setSaved] = useState('');
  const set = key => e => setTraits({ ...traits, [key]: e.target.value });

  async function save() {
    const body = { key: voice.key, color: colour };
    for (const [k, v] of Object.entries(traits)) body[k] = v.trim();
    try {
      await api('voice-catalog/traits', { method: 'PUT', json: body });
      invalidateVoices();
      setSaved('Saved.');
    } catch (error) { setSaved(error.message); }
  }

  return (
    <section className="panel voice-panel" aria-labelledby="voiceWho">
      <h3 id="voiceWho">About this voice</h3>
      <div className="voice-form">
        <label className="review-field">Name <input className="input" data-t="display_name" maxLength={80}
          value={traits.display_name} placeholder={voice.name} onChange={set('display_name')} /></label>
        <label className="review-field">Gender <select className="input" data-t="gender" value={traits.gender} onChange={set('gender')}>
          {GENDERS.map(g => <option key={g}>{g}</option>)}</select></label>
        <label className="review-field">Age <select className="input" data-t="age" value={traits.age} onChange={set('age')}>
          {AGES.map(a => <option key={a}>{a}</option>)}</select></label>
        <ColourField voice={voice} value={colour} onChange={setColour} orbRef={orbRef} />
        <label className="review-field voice-notes">Notes <textarea className="input" data-t="notes" rows={2} maxLength={500}
          value={traits.notes} onChange={set('notes')} /></label>
      </div>
      <div className="studio-actions"><button type="button" className="btn btn-secondary" data-save onClick={save}>Save</button>
        <span className="hint" role="status" data-saved>{saved}</span></div>
    </section>
  );
}

export function VoiceDetail() {
  const { key } = useLoaderData();
  const { data } = useQuery(voiceQuery(key));
  const orbRef = useRef(null);
  const v = data.voice;
  return (
    <div className="page" id="voicesRoot">
      <p><Link to="/voices">← All voices</Link></p>
      <div className="voice-hero">
        <div className="voice-orb-wrap"><VoiceOrb voice={v} orbRef={orbRef} /></div>
        <div className="voice-hero-body">
          <span className="card-kicker">{v.kind || 'voice'} · {v.engine || ''}{v.language ? ` · ${v.language}` : ''}</span>
          <h2>{voiceTitle(v)}</h2>
          {v.display_name && <p className="hint m">{v.name}</p>}
          <p className="hint">Not cast as a character yet. Cast it below and this page becomes that character’s.</p>
          {v.notes && <p>{v.notes}</p>}
        </div>
      </div>
      <HearPanel voice={v} orbRef={orbRef} />
      <CastAs voice={v} />
      <AboutVoice key={v.key} voice={v} orbRef={orbRef} />
      <UsedPanel used={data.used_in} />
    </div>
  );
}
