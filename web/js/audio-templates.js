import { api, apiUrl } from './api.js';
import { escapeHtml as esc, safeGet } from './dom.js';

// The template catalogue: voice envelopes, background policies and presets.
// A template is data; editing one saves a new version and saved dubs keep the
// version they used. Previews play a template over a test phrase (or a take
// inside the work folder) and never generate speech.

const KINDS = [['voice', 'Voice envelopes'], ['background', 'Background policies'], ['preset', 'Presets']];
const FAMILY = { preserve: 'leaves the take alone', curve: 'gain curve over the line', flatten: 'evens out the take',
  peak_linked: 'lifts the take’s own stresses', bed: 'background policy', bed_legacy: 'current sidechain ducking',
  preset: 'voice + background pairing' };

const pct = x => `${Math.round(x * 100)}%`;
const signed = db => `${db > 0 ? '+' : ''}${db.toFixed(1)} dB`;

export function anchorsText(t) {
  if (t.family === 'curve') return t.anchors.map(a => `${pct(a.at)} ${signed(a.db)}`).join(' → ');
  if (t.family === 'preset') return `${t.voice} with ${t.background}`;
  const params = Object.entries(t.params || {}).filter(([k]) => !['strength', 'anchor'].includes(k))
    .map(([k, p]) => `${k.replace(/_(db|ms|s)$/, '').replaceAll('_', ' ')} ${p.default}${p.units && !/share|count/.test(p.units) ? ` ${p.units}` : ''}`);
  return params.join(', ') || FAMILY[t.family] || '';
}

export async function renderTemplates(body, view) {
  view.templateKind ||= 'voice';
  body.innerHTML = '<p class="hint">Reading the template catalogue…</p>';
  let data;
  try { data = await api(`templates?kind=${view.templateKind}&include_retired=${view.showRetired ? 'true' : 'false'}`); }
  catch (error) { body.innerHTML = `<p class="hint">${esc(error.message)}</p>`; return; }
  body.innerHTML = `<div class="panel templates-panel">
    <div class="opts" role="group" aria-label="Kind">${KINDS.map(([k, label]) =>
      `<button type="button" class="opt" data-kind="${k}" aria-pressed="${view.templateKind === k}">${label}</button>`).join('')}</div>
    <label class="hint"><input type="checkbox" data-retired ${view.showRetired ? 'checked' : ''}> Show retired</label>
    <p class="hint">Adding a curve is a data change: save it here and it is offered, previewed and rendered like the built-in ones. Gains are relative dB; 0.5 linear gain is about −6 dB.</p>
    <table class="table"><thead><tr><th></th><th>Template</th><th>Shape or settings</th><th>Version</th><th></th></tr></thead><tbody>
      ${data.templates.map(t => `<tr><td><input type="checkbox" data-pick="${esc(t.id)}" aria-label="Select ${esc(t.title)}"></td>
        <td><strong>${esc(t.title)}</strong>${t.retired ? ' <span class="tag tag-outline">retired</span>' : ''}<br><span class="hint">${esc(t.purpose || FAMILY[t.family] || '')}</span></td>
        <td class="hint">${esc(anchorsText(t))}</td>
        <td class="m">v${t.version}<span class="hint"> · ${esc(t.provenance?.origin || '')}</span></td>
        <td><button type="button" class="btn btn-ghost" data-edit="${esc(t.id)}">Open</button></td></tr>`).join('')}
    </tbody></table>
    <div class="studio-actions">
      <button type="button" class="btn btn-secondary" data-new>New template</button>
      <button type="button" class="btn btn-ghost" data-export>Export selected</button>
      <button type="button" class="btn btn-ghost" data-import>Import a bundle</button>
    </div>
    <div data-editor></div>
    <p class="hint" role="status" data-status></p></div>`;
  const say = msg => { body.querySelector('[data-status]').textContent = msg; };
  body.querySelectorAll('[data-kind]').forEach(b => b.onclick = () => { view.templateKind = b.dataset.kind; renderTemplates(body, view); });
  body.querySelector('[data-retired]').onchange = e => { view.showRetired = e.target.checked; renderTemplates(body, view); };
  body.querySelectorAll('[data-edit]').forEach(b => b.onclick = () =>
    edit(body.querySelector('[data-editor]'), data.templates.find(t => t.id === b.dataset.edit), body, view));
  body.querySelector('[data-new]').onclick = () => edit(body.querySelector('[data-editor]'), {
    id: `${view.templateKind}/my-template`, kind: view.templateKind,
    family: view.templateKind === 'voice' ? 'curve' : view.templateKind === 'preset' ? 'preset' : 'bed',
    title: 'My template', purpose: '',
    ...(view.templateKind === 'voice' ? { anchors: [{ at: 0, db: 0 }, { at: 1, db: 2 }],
      params: { strength: { default: 1, min: 0, max: 1.5, units: 'share' } } } : {}),
    ...(view.templateKind === 'background' ? { params: {
      duck_db: { default: -5, min: -12, max: 0, units: 'dB' },
      attack_ms: { default: 100, min: 20, max: 400, units: 'ms' },
      release_ms: { default: 450, min: 150, max: 1500, units: 'ms' } } } : {}),
    ...(view.templateKind === 'preset' ? { voice: 'voice/preserve', background: 'background/gentle-ducking' } : {}),
    version: 0 }, body, view);
  body.querySelector('[data-export]').onclick = async () => {
    const ids = [...body.querySelectorAll('[data-pick]:checked')].map(i => i.dataset.pick);
    if (!ids.length) { say('Select the templates to export first.'); return; }
    try {
      const bundle = await api('templates-export', { method: 'POST', json: { ids } });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 1)], { type: 'application/json' }));
      link.download = 'doblarr-templates.json';
      link.click();
      say(`Exported ${ids.length} template${ids.length === 1 ? '' : 's'}.`);
    } catch (error) { say(error.message); }
  };
  body.querySelector('[data-import]').onclick = () => {
    const box = body.querySelector('[data-editor]');
    box.innerHTML = `<label class="review-field">Bundle JSON<textarea class="input m" rows="8" data-bundle></textarea></label>
      <button type="button" class="btn btn-secondary" data-do-import>Import</button>
      <p class="hint">Every template is checked first; if one is invalid, nothing is imported.</p>`;
    box.querySelector('[data-do-import]').onclick = async () => {
      try {
        const result = await api('templates-import', { method: 'POST', json: { bundle: JSON.parse(box.querySelector('[data-bundle]').value) } });
        await renderTemplates(body, view);
        say(`Added ${result.added.length}, updated ${result.updated.length}, unchanged ${result.unchanged.length}.`);
      } catch (error) { say(error.message); }
    };
  };
}

function edit(box, template, body, view) {
  const fields = { ...template };
  ['version', 'updated_at', 'fingerprint', 'template_id', 'preview_curve'].forEach(k => delete fields[k]);
  box.innerHTML = `<div class="template-editor">
    <h4>${esc(template.title)} <span class="hint">${template.version ? `v${template.version}` : 'new'}</span></h4>
    <label class="review-field">Definition (JSON)<textarea class="input m" rows="14" data-json>${esc(JSON.stringify(fields, null, 1))}</textarea></label>
    <p class="hint">Fields outside the schema are refused. Anchors sit on the line's speech from 0 (first word) to 1 (last word).</p>
    <div class="studio-actions">
      <button type="button" class="btn btn-primary" data-save>${template.version ? 'Save as a new version' : 'Create'}</button>
      ${template.version ? `<button type="button" class="btn btn-ghost" data-duplicate>Duplicate</button>
      <button type="button" class="btn btn-ghost" data-retire ${template.retired ? 'disabled' : ''}>Retire</button>` : ''}
      ${template.kind === 'voice' ? `<button type="button" class="btn btn-ghost" data-preview>Hear it on a test phrase</button>
      <label class="hint">Strength <input class="input m" type="number" min="0" max="1.5" step="0.1" value="1" data-strength style="width:70px"></label>` : ''}
    </div>
    <audio controls hidden data-audio></audio>
    <p class="hint" role="status" data-edit-status></p></div>`;
  const say = msg => { box.querySelector('[data-edit-status]').textContent = msg; };
  const parsed = () => { try { return JSON.parse(box.querySelector('[data-json]').value); } catch { say('That is not valid JSON.'); return null; } };
  box.querySelector('[data-save]').onclick = async () => {
    const doc = parsed();
    if (!doc) return;
    try {
      const saved = await api('templates', { method: 'PUT', json: { template: doc, base_version: template.version || 0 } });
      await renderTemplates(body, view);
      body.querySelector('[data-status]').textContent = `Saved ${saved.id} as version ${saved.version}.`;
    } catch (error) { say(error.message); }
  };
  const dup = box.querySelector('[data-duplicate]');
  if (dup) dup.onclick = async () => {
    const id = window.prompt('Id for the copy', `${template.id}-copy`);
    if (!id) return;
    try { await api(`templates/${template.id}/duplicate`, { method: 'POST', json: { new_id: id } }); await renderTemplates(body, view); }
    catch (error) { say(error.message); }
  };
  const retire = box.querySelector('[data-retire]');
  if (retire) retire.onclick = async () => {
    try { await api(`templates/${template.id}/retire`, { method: 'POST', json: { base_version: template.version } }); await renderTemplates(body, view); }
    catch (error) { say(error.message); }
  };
  const preview = box.querySelector('[data-preview]');
  if (preview) preview.onclick = async () => {
    const doc = parsed();
    if (!doc) return;
    say('Rendering the preview…');
    try {
      const key = safeGet('doblarr_api_key', '');
      const response = await fetch(apiUrl('templates-preview'), { method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(key ? { 'X-Api-Key': key } : {}) },
        body: JSON.stringify({ template: doc, params: { strength: Number(box.querySelector('[data-strength]').value) } }) });
      if (!response.ok) throw new Error((await response.json()).error || 'Preview failed');
      const audio = box.querySelector('[data-audio]');
      audio.src = URL.createObjectURL(await response.blob());
      audio.hidden = false;
      audio.play().catch(() => {});
      say(`Moves ${response.headers.get('X-Envelope-Range-Db')} dB inside the phrase · peak ${response.headers.get('X-Envelope-Peak')}. A test phrase, not a dubbed line.`);
    } catch (error) { say(error.message); }
  };
}
