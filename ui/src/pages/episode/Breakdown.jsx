import { useState } from 'react';
import { api } from '../../lib/api.js';
import { castOf, frameUrl, pickFrames, trackLabel, videoUrl, weak, whyText } from '../../lib/media.js';
import { queryClient } from '../../lib/queries.js';
import { CharacterPicker } from '../../components/CharacterPicker.jsx';
import { MediaPlayer } from '../../components/MediaPlayer.jsx';
import { Evidence, SelectionBar, screenNotes } from './Evidence.jsx';
import { Terms } from './Terms.jsx';
import { BANDS, PAD_AFTER, PAD_BEFORE, PALETTE, PARTS, ROLES, ROLE_HELP, SCREEN_NOTE, clock, fold, playClip, plural, stopClip, totalTalk } from './analysis.js';

const pct = (part, whole) => `${(part / whole * 100).toFixed(3)}%`;

// A line's emotion, said in its tooltip: face, voice, and whether they agree.
function emotionTitle(e) {
  return [e.expression && `face: ${e.expression}`, e.voice && `voice: ${e.voice}`,
    e.agree === true ? 'face and voice agree' : e.agree === false ? 'the voice disagrees' : '', `read from the ${e.from}`]
    .filter(Boolean).join(' · ');
}

function Frames({ ctx, labels, count, colour }) {
  const { data, path, screen, watch } = ctx;
  const lines = pickFrames(data.lines.filter(l => labels.includes(l.speaker)), screen, count);
  return (
    <div className="cast-frames">{lines.map(l => (
      <button key={l.index} type="button" className="cast-frame" style={{ '--tint': colour }} onClick={() => watch(labels, l.index)}
        title={`${clock(l.start)} · ${l.text}${screen[l.cue] ? ` · ${SCREEN_NOTE[screen[l.cue]] || ''}` : ''}`}>
        <img src={frameUrl(path, (l.start + l.end) / 2)} alt={`The picture at ${clock(l.start)}`} width="160" height="90" decoding="async" />
        <span className="cast-frame-time m">{clock(l.start)}</span>
      </button>
    ))}</div>
  );
}

// What the lines say about one voice group, and a warning when its name disagrees.
function Clue({ ctx, label }) {
  const { data, saveNames } = ctx;
  const said = data.dialogue?.[label] || { answers: [], calls: [], suggests: '' };
  const auto = data.named_by?.[label];
  const read = data.reader?.voices?.[label];
  if (!auto && !said.answers.length && !said.calls.length && !read) return null;
  const name = data.names[label] || '';
  const sameName = (a, b) => {
    const row = (data.cast || []).find(r => fold(r.name) === fold(a));
    return [a, ...(row?.aliases || [])].some(n => fold(n) === fold(b));
  };
  const parts = [said.answers.length ? `answers to ${said.answers.slice(0, 2).map(a => `“${a.name}” ${a.count}×`).join(', ')}` : '',
    said.calls.length ? `calls ${said.calls.slice(0, 3).map(a => a.name).join(', ')}` : ''].filter(Boolean);
  const clash = said.suggests && !(name && sameName(name, said.suggests));
  const reader = read && (
    <p className="cast-clue" title={`Read from the script by ${data.reader.model || 'a model'}`}>The script reader says <strong>{read.leading}</strong> ({Math.round(read.share * 100)}% of its lines){name && !sameName(name, read.leading) ? ', not the name it has' : ''}.</p>
  );
  if (auto) {
    const how = auto.kind === 'voice-memory'
      ? `Recognised from earlier episodes: sounds like ${name} (${Math.round(auto.similarity * 100)}%, ${plural(auto.episodes, 'episode')} heard)`
      : `Named by the dialogue: it answers when ${name} is called (${auto.answers}×)`;
    const undo = () => {
      const names = { ...data.names };
      if (auto.replaced) names[label] = auto.replaced; else delete names[label];
      saveNames(names, auto.replaced ? `${label} is ${auto.replaced} again; the dialogue will not rename it.`
        : `${label} has no name again; the dialogue will not rename it.`, [label]);
    };
    return (
      <>
        <p className="cast-clue cast-clue-auto">{how}{auto.replaced ? `, was ${auto.replaced}` : ''}.{' '}
          <button type="button" className="btn btn-ghost" onClick={undo}>{auto.replaced ? `Keep ${auto.replaced}` : 'Undo'}</button></p>
        {parts.length > 0 && <p className="cast-clue">In the dialogue: {parts.join(' · ')}</p>}
        {reader}
      </>
    );
  }
  return (
    <>
      {reader}
      <p className="cast-clue" title="A line that calls a name is spoken to that person; the next line in another voice is usually theirs.">In the dialogue: {parts.join(' · ')}</p>
      {clash && (
        <p className="cast-clue-warn">{name ? `Named ${name}, but the` : 'The'} dialogue says this is <strong>{said.suggests}</strong>: it answers when {said.suggests} is called ({said.answers[0].count}×).{' '}
          <button type="button" className="btn btn-ghost" onClick={() => saveNames({ ...data.names, [label]: said.suggests },
            `${label} is ${said.suggests} now. Watch it to check; pick another name any time.`)}>Name it {said.suggests}</button></p>
      )}
    </>
  );
}

// The character picker for one or more voice groups: picking a name names them all.
function NamePicker({ ctx, labels, group = false }) {
  const { data, saveNames, usedBy } = ctx;
  const single = labels.length === 1;
  const current = data.names[labels[0]] || '';
  const sharedWith = {};
  Object.entries(usedBy).forEach(([name, others]) => { sharedWith[name] = others.filter(l => !labels.includes(l)); });
  return (
    <CharacterPicker label={group ? `Who this part of ${current} is` : `Character for ${labels.join(', ')}`}
      value={current} placeholder={single && !current ? `Unnamed (${labels[0]})` : labels[0]}
      cast={data.cast || []} suggestions={data.suggestions?.[labels[0]] || []} sharedWith={sharedWith}
      onPick={name => {
        const names = { ...data.names };
        labels.forEach(label => { if (name) names[label] = name; else delete names[label]; });
        const joinedWith = sharedWith[name]?.length ? `, joined with ${sharedWith[name].map(l => (data.names[l] ? `the other ${name} voice` : l)).join(', ')}` : '';
        saveNames(names, name ? `${single ? labels[0] : current} is ${name}${joinedWith}. Tagged for the show.`
          : `${labels.join(', ')} has no name now.`);
      }} />
  );
}

function CastCard({ ctx, c }) {
  const { data, colour, total, lead, watch, saveNames } = ctx;
  const multi = c.labels.length > 1;
  const suggestions = !c.named ? (data.suggestions?.[c.labels[0]] || []).slice(0, 2) : [];
  return (
    <article className={`cast-card${c.named ? '' : ' cast-card-unnamed'}`} style={{ '--tint': colour[c.key] }}>
      <header className="cast-card-head">
        <span className="voice-dot" style={{ background: colour[c.key] }} />
        <NamePicker ctx={ctx} labels={c.labels} />
        <span className="cast-card-stats"><span className="m">{c.lines}</span> lines · <span className="m">{clock(c.seconds)}</span> · <span className="m">{(c.seconds / total * 100).toFixed(1)}%</span></span>
        <button type="button" className="btn btn-ghost cast-card-watch" aria-label={`Watch ${c.key}`} onClick={() => watch(c.labels, null)}>Watch</button>
      </header>
      <span className="cast-card-share"><span style={{ width: `${(c.seconds / lead * 100).toFixed(1)}%` }} /></span>
      {suggestions.length > 0 && (
        <p className="cast-card-suggest">{suggestions.map((s, i) => (
          <button key={s.name} type="button" className={`analysis-suggest${i ? ' analysis-suggest-alt' : ''}`}
            title={`Of the named voices, the closest is ${s.name} (tagged on ${plural(s.lines, 'line')}${s.episodes > 1 ? ` across ${s.episodes} episodes` : ''})${s.margin != null && s.margin < 0.05 ? ', a weak lead' : ''}. Check the pictures before you accept it.`}
            onClick={() => saveNames({ ...data.names, [c.labels[0]]: s.name }, `${c.labels[0]} is ${s.name} now. Watch it to check; pick another name any time.`)}>
            {i ? '' : 'Sounds closest to '}{s.name} <span className="m">{Math.round(s.similarity * 100)}%</span></button>
        ))}</p>
      )}
      {multi ? (
        <>
          <p className="cast-card-warn">Heard as {c.labels.length} separate voices. If one row of pictures shows someone else, rename that row.</p>
          {c.groups.map(g => (
            <div key={g.label} className="cast-group">
              <div className="cast-group-head"><span className="hint"><span className="m">{g.lines}</span> lines · <span className="m">{clock(g.seconds)}</span></span>
                <NamePicker ctx={ctx} labels={[g.label]} group /></div>
              <Clue ctx={ctx} label={g.label} />
              <Frames ctx={ctx} labels={[g.label]} count={4} colour={colour[c.key]} />
            </div>
          ))}
        </>
      ) : (
        <>
          <Clue ctx={ctx} label={c.labels[0]} />
          <Frames ctx={ctx} labels={c.labels} count={5} colour={colour[c.key]} />
        </>
      )}
      {c.sample && <p className="cast-card-line">“{c.sample.text}”{c.sample.original_text && <> <span className="hint">{c.sample.original_text}</span></>}</p>}
    </article>
  );
}

// Questions about the voices: a voice question names the whole group; a line
// question assigns that one line (kept even when the voices are regrouped).
function Asks({ ctx }) {
  const { data, path, tint, watch, saveNames, reload, say } = ctx;
  const [skipped, setSkipped] = useState(() => new Set());
  const doubts = data.doubts || [];
  if (!doubts.length) return null;
  async function answer(q, name) {
    if (!name) return;
    if (q.kind === 'voice') {
      await saveNames({ ...data.names, [q.voice]: name }, `${q.voice} is ${name}: ${q.lines} lines named, and the show will recognise the voice.`);
      return;
    }
    try {
      await api('analysis/line', { method: 'PUT', json: { path, cue: q.line.cue, character: name } });
      await reload();
      say(`“${q.line.text.slice(0, 40)}” is ${name}'s. Kept even if the voices are regrouped.`);
    } catch (error) { say(error.message); }
  }
  return (
    <section className="asks" aria-label="Questions about the voices">
      <h4>Who says this? <span className="hint">{plural(doubts.length, 'question')} · each answer is kept for the show and teaches the next episodes</span></h4>
      <div className="asks-list">{doubts.map((q, n) => !skipped.has(n) && (
        <article key={n} className="ask" data-ask={n} style={{ '--tint': tint(q.voice) }}>
          <button type="button" className="cast-frame ask-frame" title="Watch this line" onClick={() => watch([q.voice], q.line.index)}>
            <img src={frameUrl(path, (q.line.start + q.line.end) / 2)} alt={`The picture at ${clock(q.line.start)}`} width="160" height="90" decoding="async" />
            <span className="cast-frame-time m">{clock(q.line.start)}</span></button>
          <div className="ask-body">
            <p className="ask-q">{q.kind === 'voice' ? <>Who is this voice? <span className="hint">{q.lines} lines, unnamed</span></>
              : <>Who says this line? <span className="hint">filed under {q.now || q.voice}</span></>}</p>
            <p className="ask-line">“{q.line.text}”{q.line.original_text && <> <span className="hint">{q.line.original_text}</span></>}</p>
            {q.kind === 'line' && <p className="hint ask-why">{q.reasons.join(' · ')}</p>}
            <div className="ask-answers">
              {q.kind === 'voice'
                ? q.hints.map(h => <button key={h.name} type="button" className="analysis-suggest" title={h.why} onClick={() => answer(q, h.name)}>{h.name}</button>)
                : <>
                    {q.now && <button type="button" className="analysis-suggest" onClick={() => answer(q, q.now)}>{q.now} is right</button>}
                    {q.options.filter(o => o !== q.now).map(o => <button key={o} type="button" className="analysis-suggest analysis-suggest-alt" onClick={() => answer(q, o)}>{o}</button>)}
                  </>}
              <CharacterPicker label={q.kind === 'voice' ? `Who is ${q.voice}` : 'Who says this line'} placeholder="Someone else"
                cast={data.cast || []} onPick={name => answer(q, name)} />
              <button type="button" className="btn btn-ghost ask-skip" onClick={() => setSkipped(new Set([...skipped, n]))}>Not sure</button>
            </div>
          </div>
        </article>
      ))}</div>
    </section>
  );
}

function OnScreen({ ctx }) {
  const { data, watch } = ctx;
  const items = data.on_screen || [];
  if (!items.length) return null;
  return (
    <details className="analysis-onscreen">
      <summary>Text on screen <span className="hint">{items.length} · {items.filter(o => o.from === 'subtitles').slice(0, 3).map(o => o.text).join(' · ')}</span></summary>
      <div className="analysis-onscreen-list">{items.map((o, i) => {
        const l = data.lines.find(x => x.cue === o.cue);
        return (
          <button key={i} type="button" className={`analysis-suggest${o.from === 'picture' ? ' analysis-suggest-alt' : ''}`} disabled={!l}
            onClick={() => l && watch([l.speaker], l.index)}
            title={o.from === 'picture' ? 'Read from the picture by the vision model' : `From the subtitles: ${o.kind === 'title' ? 'a title card' : 'a sign'}`}>
            {o.text} <span className="m">{clock(o.at)}</span></button>
        );
      })}</div>
      <p className="hint">Signs and title cards come from the subtitle track, already translated. Dimmed ones were read from the picture.</p>
    </details>
  );
}

function Line({ ctx, l, checked, onCheck }) {
  const { path, keyOf, tint, watch, notes, reload, say } = ctx;
  const why = whyText(l.why);
  async function unlock() {
    try {
      await api('analysis/line/unlock', { method: 'POST', json: { path, cue: l.cue } });
      say('The grouping decides this line again at the next regroup.');
      reload();
    } catch (error) { say(error.message); }
  }
  const quality = l.features?.quality && l.features.quality !== 'ok';
  return (
    <div className="analysis-line" role="row">
      <span className="m" role="cell"><input type="checkbox" checked={checked} onChange={e => onCheck(l.cue, e.target.checked)}
        aria-label={`Select line at ${clock(l.start)}`} /> {clock(l.start)}</span>
      <span role="cell"><span className="analysis-who" style={{ borderColor: tint(l.speaker) }} title={why}>{keyOf(l.speaker)}</span>
        {(l.uncertain || weak(l.why)) && <span className="hint" title={why || 'Too short to be sure of the voice'}>?</span>}
        {l.locked && <button type="button" className="analysis-lock" onClick={unlock}
          title="You assigned this line; it stays with this character when voices are regrouped. Click to let the grouping decide again.">assigned</button>}
        {' '}<span className="hint analysis-screen">{notes[l.cue] || ''}</span></span>
      <span role="cell" className="analysis-text">{l.role && l.role !== 'dialogue' && <span className={`role role-${l.role}`} title={ROLE_HELP[l.role] || ''}>{ROLES[l.role] || l.role}</span>}{l.text}{l.original_text && <span className="analysis-original">{l.original_text}</span>}</span>
      <span role="cell"><span className={`cast-band cast-band-${l.band} analysis-band`}>{BANDS[l.band]}</span>
        {l.emotion && <span className={`emo emo-${l.emotion.confidence}`} title={emotionTitle(l.emotion)}>{l.emotion.feeling}</span>}</span>
      <span role="cell" className="m hint">{l.pitch_hz ? `${Math.round(l.pitch_hz)} Hz` : ''}{l.movement_st ? ` · ${l.movement_st} st` : ''}
        {quality && <><br /><span title={(l.features.reasons || []).join('; ')}>curve {l.features.quality}</span></>}</span>
      <span role="cell" className="analysis-play">
        <button type="button" className="btn btn-ghost" title="This line on screen, then the rest of this voice’s lines" onClick={() => watch([l.speaker], l.index)}>Watch</button>
        <button type="button" className="btn btn-ghost" data-track="vocals" title="The separated dialogue only" onClick={() => playClip(path, l.start, l.end, 'vocals')}>Voice</button></span>
    </div>
  );
}

// Which model tells the voices apart, and which dub tracks are heard too.
function Models({ ctx, models, found, dubs, heardDubs }) {
  const { data, path, reload, say } = ctx;
  const [pickedModels, setPickedModels] = useState(null);     // null: what the analysis used
  const [pickedDubs, setPickedDubs] = useState(null);
  const [busy, setBusy] = useState(false);
  const usedModels = (data.model || '').split('+');
  const modelOn = id => (pickedModels ? pickedModels.includes(id) : usedModels.includes(id));
  const dubOn = stream => (pickedDubs ? pickedDubs.includes(stream) : heardDubs.has(stream));
  const toggle = (list, setList, on, value, checked) => {
    const base = list ?? on;
    setList(checked ? [...base.filter(v => v !== value), value] : base.filter(v => v !== value));
  };
  async function regroup() {
    const picked = models.map(m => m.id).filter(modelOn);
    if (!picked.length) { say('Pick at least one voice model.'); return; }
    const tracks = found ? dubs.map(t => t.stream).filter(dubOn) : null;
    setBusy(true);
    say(`Grouping the voices with ${picked.map(id => models.find(m => m.id === id)?.name || id).join(' + ')}`
      + `${tracks?.length ? `, hearing ${plural(tracks.length, 'dub track')} too` : ''}… (the first use of a model downloads it)`);
    try {
      const result = await api('analysis/regroup', { method: 'POST', json: { path, models: picked, tracks } });
      queryClient.invalidateQueries({ queryKey: ['voice-models'] });
      const kept = Object.keys(result.names).length;
      await reload();
      setPickedModels(null); setPickedDubs(null);
      say(`${result.voices} voices found with ${result.model}${result.tracks?.length ? ` and ${plural(result.tracks.length, 'dub track')}` : ''}${kept ? ` · ${kept} kept their names` : ''}.`);
    } catch (error) {
      say(error.message);
    }
    setBusy(false);
  }
  if (!models.length) return null;
  return (
    <details className="analysis-models">
      <summary>Voice model · <span className="m">{data.model || 'unknown'}</span>{heardDubs.size > 0 && <> <span className="hint">+ {plural(heardDubs.size, 'dub track')}</span></>}</summary>
      <p className="hint">Which model tells the voices apart. Pick one, or several to combine them. Regrouping reuses the separated dialogue, so it takes seconds; names follow their lines.</p>
      <div className="analysis-model-list">{models.map(m => (
        <label key={m.id} className="analysis-model">
          <input type="checkbox" value={m.id} checked={modelOn(m.id)}
            onChange={e => toggle(pickedModels, setPickedModels, usedModels.filter(id => models.some(x => x.id === id)), m.id, e.target.checked)} />
          <span><strong>{m.name}</strong> <span className="hint">{m.family}{m.size_mb ? ` · ${m.size_mb} MB` : ''}{m.ready ? '' : ' · downloads on first use'}</span>
            <span className="hint analysis-model-note">{m.note}{m.scores?.recognise ? ` Anime test episode: recognises ${Math.round(m.scores.recognise * 100)}% of lines, groups ${m.scores.group.toFixed(2)}.` : ''}</span></span>
        </label>
      ))}</div>
      {dubs.length > 0 && <>
        <p className="hint">Also listen to the dubs: each has its own cast, so voices one language confuses another often keeps apart.</p>
        <div className="analysis-dubs">{dubs.map(t => (
          <label key={t.stream} className="analysis-model"><input type="checkbox" value={t.stream} checked={dubOn(t.stream)}
            onChange={e => toggle(pickedDubs, setPickedDubs, dubs.map(d => d.stream).filter(s => heardDubs.has(s)), t.stream, e.target.checked)} /> {trackLabel(t)}</label>
        ))}</div>
      </>}
      {(data.track_evidence || []).length > 0 && <p className="hint">Dub tracks last time: {data.track_evidence.map(t => `${trackLabel(t)} ${t.state === 'verified' ? `lined up (offset ${(t.offset ?? 0).toFixed(2)} s)` : `not used: ${t.reason || t.state}`}`).join('; ')}.</p>}
      <button type="button" className="btn btn-secondary" disabled={busy} onClick={regroup}>Regroup voices</button>
    </details>
  );
}

export function Breakdown({ data, path, target, tvdb, models, found, visual, voices, status, say, reload, start, busy }) {
  const [speakerFilter, setSpeakerFilter] = useState('');
  const [bandFilter, setBandFilter] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [selected, setSelected] = useState(() => new Set());
  const [player, setPlayer] = useState(null);

  // The colour a person chose for a character on its voice, kept here too.
  const chosen = {};
  voices.filter(v => v.color && v.show === `tvdb-${tvdb}`).forEach(v => {
    [v.character, v.display_name].filter(Boolean).forEach(n => { chosen[n.toLowerCase()] = v.color; });
  });
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
  const usedBy = {};
  Object.entries(data.names).forEach(([label, name]) => { (usedBy[name] ||= []).push(label); });
  const groupsOf = label => cast.find(c => c.key === keyOf(label))?.labels || [label];

  async function saveNames(names, message, keep = []) {
    try {
      await api('analysis/names', { method: 'PUT', json: { path, names, keep } });
      await reload();
      say(message);
    } catch (error) { say(error.message); }
  }

  // Every line of the given voice groups, back to back, from `fromLine`.
  function watch(labels, fromLine) {
    stopClip();
    if (!found?.tracks?.length) { say('The episode’s video is not reachable from here, so only the dialogue can be heard.'); return; }
    const name = data.names[labels[0]] || labels[0];
    const lines = data.lines.filter(l => labels.includes(l.speaker));
    const share = lines.reduce((t, l) => t + l.end - l.start, 0) / Math.max(1, total);
    const clips = lines.map(l => {
      const clipStart = Math.max(0, l.start - PAD_BEFORE);
      const end = Math.min(clipStart + 29.5, l.end + PAD_AFTER);
      return { start: clipStart, end, label: clock(l.start), text: l.text, detail: l.original_text || '',
        cue: l.cue, tag: l.moved ? 'moved here' : '', url: stream => videoUrl(path, clipStart, end, stream) };
    });
    let changed = false;
    const menu = (clip, i, { close, update }) => {
      const moveTo = async character => {
        try {
          const result = await api('analysis/line', { method: 'PUT', json: { path, cue: clip.cue, character } });
          changed = true;
          update(i, { tag: character ? `→ ${character}` : `→ new voice ${result.speaker}` });
          close();
        } catch (error) { say(error.message); close(); }
      };
      return (
        <div className="line-menu">
          <p className="line-menu-title">Who says “{clip.text.slice(0, 60)}{clip.text.length > 60 ? '…' : ''}”?</p>
          <p className="hint line-menu-hint">The grouping filed it under {name}. Pick who it really is, or add them.</p>
          <CharacterPicker label="Who says this line" placeholder="Pick or type a name" autoFocus
            cast={(data.cast || []).filter(c => c.name !== name)} onPick={n => n && moveTo(n)} />
          <button type="button" className="btn btn-ghost line-menu-new" onClick={() => moveTo('')}>A new voice, name it later</button>
        </div>
      );
    };
    setPlayer({
      title: name, colour: tint(labels[0]),
      subtitle: `${plural(lines.length, 'line')} · ${(share * 100).toFixed(1)}% of this episode’s dialogue · only their lines, back to back`,
      clips, tracks: found.tracks.map(t => ({ key: t.stream, label: trackLabel(t) })), track: found.default,
      startAt: Math.max(0, lines.findIndex(l => l.index === fromLine)),
      menu,
      onClose: () => {
        setPlayer(null);
        if (changed) reload().then(() => say('Moved lines are saved and tagged for the show; the cast above includes them.'));
      },
    });
  }

  const ctx = { data, path, colour, tint, keyOf, screen, total, lead, usedBy, notes: screenNotes(visual),
    watch, saveNames, reload, say };
  const roles = data.roles || {};
  const check = (cue, on) => {
    const nextSet = new Set(selected);
    if (on) nextSet.add(cue); else nextSet.delete(cue);
    setSelected(nextSet);
  };

  return (
    <>
      <div className="analysis-head">
        <div><h3>Analysis</h3>
          <p className="hint">{data.lines.length} lines · {clock(total)} of dialogue in {clock(length)} · {languages}</p></div>
        <button type="button" className="btn btn-ghost" data-analyze disabled={busy} onClick={start}>Analyze again</button>
      </div>
      <p className="analysis-tally">
        <strong>{cast.length}</strong> {cast.length === 1 ? 'character' : 'characters'} heard ·{' '}
        <strong>{named.length}</strong> named · <strong>{cast.length - named.length}</strong> to name
        {joined.length > 0 && <> · <strong>{joined.length}</strong> joined from several voices, check their pictures</>}
        {Object.keys(ROLES).filter(r => roles[r]).map(r => <span key={r}> · <strong>{roles[r]}</strong> {ROLES[r]}</span>)}</p>
      <p className="hint" role="status" data-status>{status}</p>
      <div className="analysis-timeline" role="img" aria-label="Who talks when, across the episode">
        {data.lines.map(l => (
          <span key={l.index} className="analysis-tick" onClick={() => watch(groupsOf(l.speaker), l.index)}
            style={{ left: pct(l.start, length), width: `${Math.max(0.12, (l.end - l.start) / length * 100).toFixed(3)}%`, background: tint(l.speaker) }}
            title={`${clock(l.start)} · ${keyOf(l.speaker)}: ${l.text}`} />
        ))}
        {Array.from({ length: Math.floor(length / 300) }, (_, i) => (
          <span key={i} className="analysis-minute m" style={{ left: `${((i + 1) * 300 / length * 100).toFixed(2)}%` }}>{(i + 1) * 5}:00</span>
        ))}
      </div>
      {(data.structure || []).length > 0 && (
        <div className="analysis-parts" aria-label="Parts of the episode">{data.structure.map((p, i) => (
          <span key={i} className={`analysis-part part-${p.kind}`}
            style={{ left: pct(p.start, length), width: `${Math.max(0.4, (p.end - p.start) / length * 100).toFixed(3)}%` }}
            title={`${PARTS[p.kind] || p.kind} · ${clock(p.start)}–${clock(p.end)}`}>{PARTS[p.kind] || p.kind}</span>
        ))}</div>
      )}
      <OnScreen ctx={ctx} />
      <Terms data={data} path={path} reload={reload} say={say} />
      <Asks ctx={ctx} />
      <section className="cast-grid" aria-label="Who speaks in this episode">
        {cast.map(c => <CastCard key={c.key} ctx={ctx} c={c} />)}
      </section>
      <p className="hint">Pictures are taken from the middle of each voice’s lines, preferring moments a face is on screen and moving its mouth. Click one to watch from that line. Pick each voice from the show’s cast, or add a new character; two voices given the same character are joined.</p>
      <div className="analysis-filters">
        <label>Who <select className="input" data-filter-speaker value={speakerFilter} onChange={e => setSpeakerFilter(e.target.value)}>
          <option value="">Everyone</option>
          {cast.map(c => <option key={c.key} value={c.key}>{c.key}</option>)}</select></label>
        <label>How <select className="input" data-filter-band value={bandFilter} onChange={e => setBandFilter(e.target.value)}>
          <option value="">Every line</option>
          {['intense', 'calm', 'quiet'].map(b => <option key={b} value={b}>{b}{b === 'intense' ? ' (training lines)' : ''}</option>)}</select></label>
        {Object.values(roles).some((n, i) => i && n) && (
          <label>Kind <select className="input" data-filter-role value={roleFilter} onChange={e => setRoleFilter(e.target.value)}>
            <option value="">Every kind</option>
            {['dialogue', ...Object.keys(ROLES)].filter(r => roles[r]).map(r => <option key={r} value={r}>{r === 'dialogue' ? 'dialogue' : ROLES[r]} ({roles[r]})</option>)}</select></label>
        )}
        <span className="hint">{plural(visible.length, 'line')}</span>
      </div>
      <SelectionBar data={data} path={path} selected={selected} clear={() => setSelected(new Set())} reload={reload} say={say} />
      <div className="analysis-lines" role="table" aria-label="Every line of the episode">
        {visible.map(l => <Line key={l.index} ctx={ctx} l={l} checked={selected.has(l.cue)} onCheck={check} />)}
      </div>
      <section className="analysis-behind" aria-label="Behind the analysis">
        <h4>Behind the analysis</h4>
        <Models ctx={ctx} models={models} found={found} dubs={dubs} heardDubs={heardDubs} />
        <Evidence data={data} path={path} target={target} reload={reload} say={say} visual={visual} />
      </section>
      {player && <MediaPlayer {...player} />}
    </>
  );
}
