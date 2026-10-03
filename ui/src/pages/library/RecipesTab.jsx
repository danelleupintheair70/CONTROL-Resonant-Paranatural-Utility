import { useRef, useState } from 'react';
import { api } from '../../lib/api.js';
import { castParams } from '../../lib/identity.js';

const ENGINES = ['chatterbox', 'chatterbox_turbo', 'qwen', 'qwen_custom_voice', 'kokoro', 'luxtts', 'tada'];

export function recipeMedia(item) {
  return { kind: item.episode_id ? 'episode' : 'movie', title: item.parent?.title || item.title,
    tmdb_id: item.tmdb_id || null, tvdb_id: item.tvdb_id || null,
    season: item.season ?? null, episode: item.episode_number ?? null,
    runtime_seconds: null };
}

function download(item, recipe) {
  const blob = new Blob([JSON.stringify(recipe, null, 2) + '\n'], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${(item.title || 'dub').replace(/[^a-z0-9-]/gi, '-').slice(0, 100)}-${recipe.target_locale || recipe.target_language}.dobdub`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Personal knowledge rules an export left out, offered for a second export.
function PersonalRules({ pending, onExport }) {
  const [picked, setPicked] = useState([]);
  const [busy, setBusy] = useState(false);
  return (
    <>
      <hr /><h3>Personal rules also affect this title</h3>
      <p className="hint">They stay private unless you explicitly include them.</p>
      {pending.map(d => (
        <label key={d.id} className="recipe-rule">
          <input type="checkbox" className="recipe-promote" value={d.id} checked={picked.includes(d.id)}
            onChange={e => setPicked(e.target.checked ? [...picked, d.id] : picked.filter(id => id !== d.id))} />
          {' '}{d.phrase} <span className="hint">{d.kind} · {d.locale} · {d.status}</span>
        </label>
      ))}
      <div className="episode-actions">
        <button type="button" className="btn btn-secondary" id="recipeReexport" disabled={busy}
          onClick={async () => { setBusy(true); if (!(await onExport(picked))) setBusy(false); }}>Export again including the selected rules</button>
      </div>
    </>
  );
}

// A checked recipe: pick local voices for each slot, then apply it.
function RecipePreview({ data, media, onApply }) {
  const r = data.recipe;
  const slots = [{ key: 'narrator', label: 'Narrator', voice: r.narrator },
    ...r.characters.map(c => ({ key: 'character:' + c.speaker_id, label: `${c.label} (${c.speaker_id})`, voice: c.voice }))];
  const [choices, setChoices] = useState(() => slots.map(s => {
    const matches = data.voices.filter(v => s.voice.name && v.name === s.voice.name);
    const voice = matches.length === 1 ? matches[0].id : '';
    // Source-audio casting needs a cloning engine.
    const engine = !voice && ['kokoro', 'qwen_custom_voice'].includes(s.voice.engine) ? 'qwen' : s.voice.engine;
    return { voice, engine };
  }));
  const [busy, setBusy] = useState(false);
  const set = (i, patch) => setChoices(list => list.map((c, j) => {
    if (j !== i) return c;
    const next = { ...c, ...patch };
    if ('voice' in patch && !next.voice && ['kokoro', 'qwen_custom_voice'].includes(next.engine)) next.engine = 'qwen';
    return next;
  }));
  return (
    <>
      <hr /><h3>Review recipe</h3>
      <p><strong>{r.media.title}</strong> · {r.target_language} · version {r.revision}</p>
      <p className="hint">{r.creator ? `By ${r.creator}` : 'No creator specified'}</p>
      <p className="recipe-notes">{r.notes}</p>
      {data.warnings.map(w => <p key={w} className="hint">{w}</p>)}
      {data.knowledge && <p className="hint">Knowledge overlay: {data.knowledge.entries.length} rule(s) — {data.knowledge.entries.map(e => `${e.phrase} (${e.state})`).join(', ') || 'none'}</p>}
      <div className="narrator-fields">
        {slots.map((s, i) => (
          <label key={s.key}>{s.label} — {s.voice.engine}
            <span className="hint">Requested: {s.voice.name || 'Local source audio'}{s.voice.delivery ? ` · ${s.voice.delivery}` : ''}</span>
            <select className="input" data-slot={i} aria-label={`Local voice for ${s.label}`} value={choices[i].voice}
              onChange={e => set(i, { voice: e.target.value })}>
              <option value="">Use local source audio</option>
              {data.voices.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
            <select className="input" data-engine={i} aria-label={`Local engine for ${s.label}`} value={choices[i].engine}
              onChange={e => set(i, { engine: e.target.value })}>
              {[...new Set([...ENGINES, choices[i].engine])].map(e => <option key={e} value={e}>{e}</option>)}
            </select>
          </label>
        ))}
      </div>
      <p className="hint">Source-audio casting needs a cloning engine; missing preset voices default to Qwen. Delivery directions require Qwen. Check your local voice and engine compatibility.</p>
      <details><summary>Included generation settings ({Object.keys(r.settings).length})</summary>
        <pre className="recipe-settings">{JSON.stringify(r.settings, null, 2)}</pre></details>
      <p className="hint">Applying replaces this title’s character cast and included settings, and clears prior dialogue edits and shared cast links. Existing jobs and global settings stay unchanged. Review speaker assignments before queueing a dub.</p>
      <button type="button" className="btn btn-primary" id="recipeApply" disabled={busy} onClick={async () => {
        setBusy(true);
        const voices = Object.fromEntries(slots.map((s, i) => [s.key, choices[i].voice]));
        const engines = Object.fromEntries(slots.map((s, i) => [s.key, choices[i].engine]));
        if (!(await onApply(r, voices, engines))) setBusy(false);
      }}>Apply recipe to this {media.kind}</button>
    </>
  );
}

// Share a dub's settings as a .dobdub file, or apply one someone shared.
export function RecipesTab({ item, target, onApplied }) {
  const identity = Object.fromEntries(castParams(item));
  const media = recipeMedia(item);
  const [form, setForm] = useState({ creator: '', revision: '1', runtime: '', notes: '', schema: '1' });
  const [status, setStatus] = useState('');
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [preview, setPreview] = useState(null);
  const runtimeRef = useRef(null);
  const fileRequest = useRef(0);
  const set = key => e => setForm({ ...form, [key]: e.target.value });

  async function doExport(includePersonal) {
    if (!runtimeRef.current.checkValidity()) throw new Error('Enter a runtime between 1 and 86400 seconds, or leave it blank.');
    return api('recipes/export', { method: 'POST', json: {
      identity, media: { ...media, runtime_seconds: form.runtime ? Number(form.runtime) : null },
      parent: item.parent ? Object.fromEntries(castParams(item.parent)) : null,
      source_language: item.original || '', target_language: target,
      creator: form.creator, revision: form.revision, notes: form.notes,
      schema_version: Number(form.schema), include_personal: includePersonal,
    } });
  }

  async function exportRecipe() {
    setExporting(true);
    setStatus('Preparing recipe…');
    try {
      const data = await doExport([]);
      download(item, data.recipe);
      setStatus(['Recipe exported.', ...data.warnings, ...(data.loss || [])].join(' '));
      const pending = (data.personal_dependencies || []).filter(d => !d.included);
      if (pending.length) setPreview({ kind: 'personal', pending });
    } catch (e) { setStatus(e.message); }
    finally { setExporting(false); }
  }

  async function exportWith(ids) {
    try {
      const again = await doExport(ids);
      download(item, again.recipe);
      setStatus('Recipe exported with the selected personal rules.');
      setPreview(null);
      return true;
    } catch (e) { setStatus(e.message); return false; }
  }

  async function pickFile(event) {
    const request = ++fileRequest.current;
    setPreview(null);
    const file = event.target.files[0];
    if (!file) return;
    setStatus('Checking recipe…');
    try {
      if (file.size > 128 * 1024) throw new Error('Recipe files must be smaller than 128 KB. Audio and video are not supported.');
      const recipe = JSON.parse(await file.text());
      const data = await api('recipes/preview', { method: 'POST', json: { identity, media, recipe, target_locale: target } });
      if (request !== fileRequest.current) return;
      setStatus('Recipe checked. Choose local voices before applying.');
      setPreview({ kind: 'recipe', data });
    } catch (e) {
      if (request === fileRequest.current) setStatus(e instanceof SyntaxError ? 'This is not a valid JSON recipe file.' : e.message);
    }
  }

  async function apply(recipe, voices, engines) {
    setImporting(true);
    setStatus('Applying recipe…');
    try {
      const result = await api('recipes/import', { method: 'POST', json: { identity, media, recipe, voices, engines, target_locale: target } });
      onApplied(result.plan);
      setStatus('Recipe applied. Review Speakers & voices, then queue a dub when ready. Nothing has been generated.');
      setPreview(null);
      return true;
    } catch (e) { setStatus(e.message); return false; }
    finally { setImporting(false); }
  }

  return (
    <>
      <h3>Dub recipes</h3>
      <p className="hint">Share the settings for a dub. Each person generates it using their own media and locally available voices.</p>
      <p className="hint">Recipe files contain no audio, video, subtitles, or cloned voice recordings. Dialogue and timing are extracted again from the local file.</p>
      <div className="narrator-fields">
        <label>Creator<input className="input" id="recipeCreator" maxLength={100} autoComplete="off" value={form.creator} onChange={set('creator')} /></label>
        <label>Recipe version<input className="input" id="recipeRevision" maxLength={40} value={form.revision} onChange={set('revision')} /></label>
        <label>Expected runtime (seconds)<input className="input" id="recipeRuntime" ref={runtimeRef} type="number" min="1" max="86400" step="0.001"
          placeholder="Unknown" value={form.runtime} onChange={set('runtime')} /></label>
        <label className="narrator-direction">Release notes<textarea className="input" id="recipeNotes" maxLength={2000} rows={3}
          placeholder="Edition, delivery style, or casting notes" value={form.notes} onChange={set('notes')} /></label>
        <label>Recipe format<select className="input" id="recipeSchema" value={form.schema} onChange={set('schema')}>
          <option value="1">v1 — settings only</option><option value="2">v2 — settings + knowledge overlay</option></select></label>
      </div>
      <p className="hint">Export uses saved settings and character assignments. Review the file before sharing; names and notes are included.</p>
      <div className="episode-actions">
        <button type="button" className="btn btn-secondary" id="recipeExport" disabled={exporting} onClick={exportRecipe}>Export recipe</button>
        <label className="btn btn-secondary" htmlFor="recipeFile">Import recipe</label>
        <input id="recipeFile" aria-label="Import recipe file" type="file" accept=".dobdub,application/json"
          className="recipe-file" disabled={importing} onChange={pickFile} />
      </div>
      <p id="recipeStatus" role="status" className="hint">{status}</p>
      <div id="recipePreview">
        {preview?.kind === 'personal' && <PersonalRules pending={preview.pending} onExport={exportWith} />}
        {preview?.kind === 'recipe' && <RecipePreview data={preview.data} media={media} onApply={apply} />}
      </div>
    </>
  );
}
