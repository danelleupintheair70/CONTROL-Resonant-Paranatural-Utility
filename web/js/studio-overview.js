import { api } from './api.js';
import { escapeHtml as esc } from './dom.js';

// Overview: how this episode is worked on, what it may read, and what exists.

const ROLES = [
  ['meaning', 'Meaning source', 'the original dialogue: facts and intent'],
  ['adaptation', 'Adaptation reference', 'another dub\'s writing; phrasing under a policy'],
  ['performance', 'Performance reference', 'a track to hear for delivery'],
  ['voice', 'Voice reference', 'a sample for voice identity'],
  ['evaluation', 'Evaluation only', 'held out from every generation request'],
];
const POLICIES = [
  ['original_only', 'Original only', 'No reference is ever sent to the writer.'],
  ['reference_suggestions', 'Original plus reference suggestions',
    'The original decides facts and relationships; the reference may lend phrasing or '
    + 'wordplay that keeps them. Uncertain alignment is never used.'],
  ['follow_edition', 'Follow a localized edition',
    'Target a chosen adaptation\'s choices, keeping the original\'s facts; departures are recorded.'],
];
const TEXT_KINDS = [
  ['original_transcript', 'Original-language transcript'],
  ['dub_transcript', 'Dub transcript (what that cast said)'],
  ['subtitle_translation', 'Subtitles translating the original'],
  ['manual', 'Typed or pasted'],
];

export function renderOverview(body, ctx) {
  const o = ctx.overview, s = ctx.session;
  const refs = o.references || [];
  const direction = s.direction || {};
  const budgets = s.budgets || {};
  const job = o.active_job;
  body.innerHTML = `
    <div class="studio-grid">
      <section class="panel studio-card" aria-labelledby="ovRun">
        <h3 id="ovRun">Draft and working style</h3>
        <p class="hint">${job ? `Latest run ${esc(job.id)}: ${esc(job.status)} — ${esc(job.message || job.stage || '')}`
          : 'No run yet. A draft uses the direction and budgets below.'}</p>
        ${o.export ? `<p>${o.export.stale} stale line(s) · ${o.export.unresolved} unresolved finding(s)</p>` : ''}
        <fieldset class="studio-fieldset"><legend>Stop and ask me at</legend>
          ${['casting', 'script', 'export'].map(c => `<label class="studio-check"><input type="checkbox"
            data-check="${c}" ${(s.checkpoints || []).includes(c) ? 'checked' : ''}> ${c === 'casting'
            ? 'Casting, before the first draft' : c === 'script' ? 'Script review, before export' : 'Final export'}</label>`).join('')}
          <p class="hint">Used by the Guided style. Automatic still shows every unresolved finding;
            Manual never queues anything you did not ask for.</p>
        </fieldset>
        <div class="studio-inline">
          <label class="review-field">Request budget <input class="input m" type="number" min="0" max="5000"
            id="ovRequests" value="${budgets.requests ?? 0}"><span class="hint">0 = counted, not capped</span></label>
          <label class="review-field">Alternative takes per line <input class="input m" type="number" min="0" max="4"
            id="ovCandidates" value="${budgets.candidates ?? 2}"></label>
          <label class="review-field">Automatic retries <input class="input m" type="number" min="0" max="3"
            id="ovRetries" value="${budgets.retries ?? 1}"></label>
        </div>
        <label class="review-field">Unresolved findings at export <select class="input" id="ovUnresolved">
          <option value="flag" ${s.unresolved !== 'block_export' ? 'selected' : ''}>List them, allow export</option>
          <option value="block_export" ${s.unresolved === 'block_export' ? 'selected' : ''}>Block export until resolved</option>
        </select></label>
        <div class="studio-actions">
          <button type="button" class="btn btn-secondary" id="ovSave">Save working style</button>
          <button type="button" class="btn btn-primary" id="ovRender">Render a draft</button>
        </div>
        <p class="hint" id="ovRenderNote" role="status"></p>
      </section>

      <section class="panel studio-card" aria-labelledby="ovDirection">
        <h3 id="ovDirection">Writing direction</h3>
        <label class="review-field">Spanish region (output locale)
          <input class="input m" id="ovLocale" value="${esc(direction.target_locale || '')}" placeholder="es-MX, es-419, es-ES…"></label>
        <p class="hint">Latin American Spanish is not one accent: pick the region you want to hear.</p>
        <label class="review-field">Adaptation style <select class="input" id="ovAdaptation">
          ${['natural', 'faithful', 'localized'].map(a => `<option ${direction.adaptation === a ? 'selected' : ''}>${a}</option>`).join('')}
        </select></label>
        <label class="studio-check"><input type="checkbox" id="ovSlang" ${direction.slang ? 'checked' : ''}> Allow regional slang</label>
        <fieldset class="studio-fieldset"><legend>Reference policy</legend>
          ${POLICIES.map(([v, label, note]) => `<label class="studio-radio"><input type="radio" name="ovPolicy"
            value="${v}" ${(direction.reference_policy || 'original_only') === v ? 'checked' : ''}>
            <span><strong>${label}</strong><span class="hint">${note}</span></span></label>`).join('')}
        </fieldset>
        <label class="review-field">Adaptation reference <select class="input" id="ovReference">
          <option value="">None</option>
          ${refs.filter(r => r.roles.includes('adaptation')).map(r => `<option value="${esc(r.id)}"
            ${direction.reference === r.id ? 'selected' : ''}>${esc(r.label)} (${esc(r.language)})</option>`).join('')}
        </select></label>
        <label class="review-field">Alignment <select class="input" id="ovAlignment">
          <option value="">None</option>
          ${(o.alignments || []).map(a => `<option value="${esc(a.id)}" ${direction.alignment === a.id ? 'selected' : ''}>
            ${esc(label(refs, a.reference))} · revision ${a.revision}</option>`).join('')}
        </select></label>
        <fieldset class="studio-fieldset"><legend>Held out from generation</legend>
          ${refs.filter(r => r.evaluation_only).map(r => `<label class="studio-check"><input type="checkbox"
            data-eval="${esc(r.id)}" ${(direction.evaluation || []).includes(r.id) ? 'checked' : ''}>
            ${esc(r.label)}</label>`).join('') || '<p class="hint">No evaluation-only reference yet.</p>'}
          <p class="hint">Checked tracks are fingerprinted and every translation request of a render is
            scanned for them before it is sent.</p>
        </fieldset>
        <button type="button" class="btn btn-secondary" id="ovDirSave">Save direction</button>
      </section>
    </div>

    <section class="panel studio-card" aria-labelledby="ovRefs">
      <h3 id="ovRefs">References</h3>
      <p class="hint">A track's language tag says what the release claims, not what it contains.
        Nothing here is sent to a model unless a role and a policy allow it.</p>
      <table class="table"><thead><tr><th>Reference</th><th>Language</th><th>Roles</th><th>Text</th><th></th></tr></thead>
        <tbody>${refs.map(r => `<tr>
          <td><strong>${esc(r.label)}</strong><div class="hint">${esc(r.track?.media_name || 'text only')}
            ${r.track?.audio_index != null ? ` · audio ${r.track.audio_index}` : ''}</div></td>
          <td class="m">${esc(r.language)}</td>
          <td>${r.evaluation_only ? '<span class="tag tag-outline">evaluation only</span>'
            : r.roles.map(x => `<span class="tag tag-neutral">${esc(x)}</span>`).join(' ')}</td>
          <td class="hint">${esc(r.text?.kind || 'none')} · ${r.text?.utterances || 0} line(s)
            ${r.text?.provenance ? `· ${esc(r.text.provenance)}` : ''}${r.text?.uncertain ? ' · unreviewed' : ''}</td>
          <td>${r.track ? `<button type="button" class="btn btn-ghost" data-transcribe="${esc(r.id)}">Transcribe windows</button>` : ''}</td>
        </tr>`).join('') || '<tr><td colspan="5" class="hint">No references yet.</td></tr>'}</tbody></table>
      <details class="studio-add"><summary>Add a reference</summary><div id="ovAddRef"><p class="hint">Reading the file's tracks…</p></div></details>
    </section>

    <section class="panel studio-card" aria-labelledby="ovAlign">
      <h3 id="ovAlign">Alignments</h3>
      <div id="ovAlignList">${(o.alignments || []).map(a => `<div class="studio-align-row">
        <strong>${esc(label(refs, a.source_ref))} ↔ ${esc(label(refs, a.reference))}</strong>
        <span class="hint">revision ${a.revision} · ${a.segments} map segment(s) · ${stateSummary(a.stats)}</span>
        <button type="button" class="btn btn-ghost" data-align="${esc(a.id)}">Review lines</button></div>`).join('')
        || '<p class="hint">No alignment yet.</p>'}</div>
      <div class="studio-inline">
        <label class="review-field">Original <select class="input" id="ovAlSrc">${refs.filter(r => r.roles.includes('meaning'))
          .map(r => `<option value="${esc(r.id)}">${esc(r.label)}</option>`).join('')}</select></label>
        <label class="review-field">Reference <select class="input" id="ovAlRef">${refs.filter(r => !r.roles.includes('meaning'))
          .map(r => `<option value="${esc(r.id)}">${esc(r.label)}</option>`).join('')}</select></label>
        <label class="review-field">Offset (s, reference → original)
          <input class="input m" type="number" step="0.01" id="ovAlOffset" value="0"></label>
        <label class="studio-check"><input type="checkbox" id="ovAlEstimate"> Estimate from the audio</label>
        <button type="button" class="btn btn-secondary" id="ovAlign">Align</button>
      </div>
      <div id="ovAlignDetail"></div>
    </section>

    <section class="panel studio-card" aria-labelledby="ovImport">
      <h3 id="ovImport">Import an earlier experiment</h3>
      <p class="hint">Reads a comparison manifest or a voice-audition record from the work folder,
        shows what is there and what is missing, and asks you to map each identity. Nothing is generated.</p>
      <div class="studio-inline"><input class="input m" id="ovImportPath" placeholder="work/benchmarks/…/manifest.json">
        <button type="button" class="btn btn-secondary" id="ovImportPreview">Preview</button></div>
      <div id="ovImportResult"></div>
      ${(o.imports || []).map(i => `<div class="studio-align-row"><strong>${esc(i.legacy_id)}</strong>
        <span class="hint">${esc(i.kind)} · ${i.judgments} judgment file(s) · ${i.missing.length} missing</span>
        <label class="btn btn-ghost">Import exported results<input type="file" accept=".md,text/markdown"
          data-results="${esc(i.id)}" hidden></label></div>`).join('')}
    </section>

    ${(o.studio_jobs || []).length ? `<section class="panel studio-card"><h3>Studio work in the queue</h3>
      <table class="table"><tbody>${o.studio_jobs.map(j => `<tr><td>${esc(j.kind.replace('studio_', ''))}</td>
        <td>${esc(j.status)}</td><td class="hint">${esc(j.message || j.stage || '')}</td>
        <td>${['queued', 'running'].includes(j.status) ? `<button type="button" class="btn btn-ghost" data-cancel="${esc(j.id)}">Cancel</button>` : ''}</td></tr>`).join('')}
      </tbody></table></section>` : ''}`;
  wire(body, ctx);
}

function label(refs, id) { return (refs.find(r => r.id === id) || {}).label || id; }
function stateSummary(stats) {
  const states = stats?.states || {};
  return Object.entries(states).map(([k, v]) => `${v} ${k}`).join(', ') || 'no groups';
}

function wire(body, ctx) {
  const $ = id => body.querySelector(id);
  $('#ovSave').onclick = async () => {
    const checkpoints = [...body.querySelectorAll('[data-check]')].filter(c => c.checked).map(c => c.dataset.check);
    await ctx.savePatch({ checkpoints, unresolved: $('#ovUnresolved').value, budgets: {
      requests: Number($('#ovRequests').value) || 0, candidates: Number($('#ovCandidates').value) || 0,
      retries: Number($('#ovRetries').value) || 0 } });
    await ctx.reload(); ctx.show('overview', { push: false });
  };
  $('#ovDirSave').onclick = async () => {
    await ctx.savePatch({ direction: {
      target_locale: $('#ovLocale').value.trim(), adaptation: $('#ovAdaptation').value,
      slang: $('#ovSlang').checked,
      reference_policy: body.querySelector('input[name="ovPolicy"]:checked')?.value || 'original_only',
      reference: $('#ovReference').value, alignment: $('#ovAlignment').value,
      evaluation: [...body.querySelectorAll('[data-eval]')].filter(c => c.checked).map(c => c.dataset.eval),
    } });
  };
  $('#ovRender').onclick = async e => {
    const note = $('#ovRenderNote');
    e.currentTarget.disabled = true;
    try {
      const result = await api(`studio/sessions/${ctx.sid}/render`, { method: 'POST', json: {} });
      note.textContent = `Queued run ${result.job.id}. It uses the direction and budgets above; `
        + 'follow it on the Dubs page or here after a reload.';
      ctx.onQueued?.();
      await ctx.reload();
    } catch (error) { note.textContent = error.message; }
    e.currentTarget.disabled = false;
  };
  body.querySelectorAll('[data-transcribe]').forEach(b => b.onclick = () => transcribe(b, ctx));
  body.querySelectorAll('[data-align]').forEach(b => b.onclick = () => alignmentDetail(body, ctx, b.dataset.align));
  $('#ovAlign').onclick = async () => {
    const offset = Number($('#ovAlOffset').value) || 0;
    try {
      const result = await api(`studio/sessions/${ctx.sid}/alignments`, { method: 'POST', json: {
        source: $('#ovAlSrc').value, reference: $('#ovAlRef').value,
        estimate: $('#ovAlEstimate').checked,
        time_map: $('#ovAlEstimate').checked ? null
          : { segments: [{ start: 0, end: 100000, offset, rate: 1, method: 'manual' }] } } });
      await ctx.reload();
      ctx.show('overview', { push: false }).then(() => alignmentDetail(document.getElementById('studioBody'),
        ctx, result.alignment.id));
    } catch (error) { ctx.status(error.message); }
  };
  $('#ovImportPreview').onclick = () => importPreview(body, ctx);
  body.querySelectorAll('[data-results]').forEach(input => input.onchange = async () => {
    const file = input.files[0];
    if (!file) return;
    try {
      const saved = await api(`studio/imports/${input.dataset.results}/results`, { method: 'POST',
        json: { name: file.name, text: await file.text() } });
      ctx.status(`Imported judgments: ${saved.import.judgments} results file(s) on this import.`);
      await ctx.reload(); ctx.show('overview', { push: false });
    } catch (error) { ctx.status(error.message); }
  });
  body.querySelectorAll('[data-cancel]').forEach(b => b.onclick = async () => {
    await api(`jobs/${b.dataset.cancel}`, { method: 'DELETE' }).catch(e => ctx.status(e.message));
    await ctx.reload(); ctx.show('overview', { push: false });
  });
  addReferenceForm(body.querySelector('#ovAddRef'), ctx);
}

async function addReferenceForm(box, ctx) {
  let probe;
  try { probe = await api(`studio/sessions/${ctx.sid}/probe`); } catch (error) {
    box.innerHTML = `<p class="hint">${esc(error.message)}</p>`; return;
  }
  const audio = probe.streams.filter(s => s.type === 'audio');
  const subs = probe.streams.filter(s => s.type === 'subtitle');
  box.innerHTML = `
    <p class="hint">${esc(probe.note)}</p>
    <div class="studio-inline">
      <label class="review-field">Label <input class="input" id="arLabel" placeholder="English dub"></label>
      <label class="review-field">Language <input class="input m" id="arLang" placeholder="en"></label>
      <label class="review-field">Audio track <select class="input" id="arTrack"><option value="">None (text only)</option>
        ${audio.map(s => `<option value="${s.audio_index}">${s.audio_index}: ${esc(s.language || '?')} ${esc(s.title || '')}</option>`).join('')}</select></label>
    </div>
    <fieldset class="studio-fieldset"><legend>Roles</legend>
      ${ROLES.map(([v, name, note]) => `<label class="studio-check"><input type="checkbox" data-role="${v}"> ${name}
        <span class="hint">— ${note}</span></label>`).join('')}</fieldset>
    <div class="studio-inline">
      <label class="review-field">What the text is <select class="input" id="arKind">${TEXT_KINDS.map(([v, n]) =>
        `<option value="${v}">${n}</option>`).join('')}<option value="none">No text</option></select></label>
      <label class="review-field">Text from <select class="input" id="arFrom">
        <option value="none">Nothing yet (transcribe windows later)</option>
        <option value="job">The run's own cues</option>
        ${subs.map((s, i) => `<option value="sub:${i}">Subtitle track ${i}: ${esc(s.language)} ${esc(s.title || '')}</option>`).join('')}
        <option value="paste">Pasted lines (start|end|text)</option></select></label>
    </div>
    <textarea class="input" id="arPaste" rows="4" hidden placeholder="12.0|14.5|I'm back"></textarea>
    <button type="button" class="btn btn-secondary" id="arAdd">Add reference</button>`;
  const $ = id => box.querySelector(id);
  $('#arFrom').onchange = () => { $('#arPaste').hidden = $('#arFrom').value !== 'paste'; };
  $('#arAdd').onclick = async () => {
    const roles = [...box.querySelectorAll('[data-role]')].filter(c => c.checked).map(c => c.dataset.role);
    const from = $('#arFrom').value;
    const track = $('#arTrack').value === '' ? null
      : { media_path: '', audio_index: Number($('#arTrack').value) };
    const json = { label: $('#arLabel').value.trim(), language: $('#arLang').value.trim(), roles,
      track, text: { kind: $('#arKind').value } };
    if (from === 'job') json.from_job = true;
    if (from.startsWith('sub:')) json.subtitle_stream = Number(from.slice(4));
    if (from === 'paste') {
      json.utterances = $('#arPaste').value.split('\n').map(l => l.split('|')).filter(p => p.length >= 3)
        .map((p, i) => ({ utt_id: `p${i}`, start: Number(p[0]), end: Number(p[1]), text: p.slice(2).join('|').trim() }));
    }
    try {
      await api(`studio/sessions/${ctx.sid}/references`, { method: 'POST', json });
      await ctx.reload(); ctx.show('overview', { push: false });
    } catch (error) { ctx.status(error.message); }
  };
}

async function transcribe(button, ctx) {
  const text = window.prompt('Windows to transcribe, in seconds (e.g. "60-120, 300-360"). '
    + 'Each is at most 240 s; nothing outside them is read.', '');
  if (!text) return;
  const windows = text.split(',').map(w => w.split('-').map(Number)).filter(w => w.length === 2
    && w.every(Number.isFinite));
  try {
    const result = await api(`studio/references/${button.dataset.transcribe}/transcribe`,
      { method: 'POST', json: { windows } });
    ctx.status(`Queued transcription ${result.job.id}. It runs through the ordinary queue.`);
  } catch (error) { ctx.status(error.message); }
}

async function alignmentDetail(body, ctx, id) {
  const box = body.querySelector('#ovAlignDetail');
  if (!box) return;
  const { alignment } = await api(`studio/alignments/${id}`);
  box.innerHTML = `<div class="studio-align">
    <p class="hint">Method ${esc(alignment.method)} · ${stateSummary(alignment.stats)}.
      Uncertain and excluded groups are never sent to a writer.</p>
    <table class="table"><thead><tr><th>Original</th><th>Reference</th><th>State</th><th></th></tr></thead><tbody>
    ${alignment.groups.slice(0, 400).map(g => `<tr data-group="${esc(g.group_id)}">
      <td>${esc(g.source_text || '—')}</td><td>${esc(g.reference_text || '—')}
        ${(g.differences || []).length ? `<div class="review-marker">${esc(g.differences.join('; '))}</div>` : ''}</td>
      <td><span class="tag ${g.state === 'matched' ? 'tag-neutral' : 'tag-outline'}">${esc(g.state)}</span>
        ${g.confidence != null ? `<span class="hint m">${g.confidence.toFixed(2)}</span>` : ''}
        ${g.manual ? '<span class="hint">manual</span>' : ''}</td>
      <td>${g.state === 'excluded' ? '<button type="button" class="btn btn-ghost" data-act="include">Include</button>'
        : '<button type="button" class="btn btn-ghost" data-act="exclude">Exclude</button>'}
        ${g.source.length && g.reference.length ? '<button type="button" class="btn btn-ghost" data-act="unlink">Unlink</button>' : ''}</td>
    </tr>`).join('')}</tbody></table></div>`;
  box.querySelectorAll('[data-act]').forEach(b => b.onclick = async () => {
    const group = b.closest('[data-group]').dataset.group;
    try {
      await api(`studio/alignments/${id}/overrides`, { method: 'POST', json: {
        base_revision: alignment.revision, action: b.dataset.act, group_id: group } });
      alignmentDetail(body, ctx, id);
    } catch (error) { ctx.status(error.message); }
  });
}

async function importPreview(body, ctx) {
  const box = body.querySelector('#ovImportResult');
  const path = body.querySelector('#ovImportPath').value.trim();
  try {
    const { preview } = await api(`studio/sessions/${ctx.sid}/imports/preview`, { method: 'POST', json: { path } });
    const refs = ctx.overview.references || [];
    box.innerHTML = `<div class="studio-import">
      <p><strong>${esc(preview.legacy_id)}</strong> · ${esc(preview.kind)}
        ${preview.media ? ` · media ${esc(preview.media.state)}` : ''}</p>
      <p class="hint">${esc(preview.generates)}. ${esc(preview.judgments)}</p>
      ${preview.missing.length ? `<p class="review-marker">Missing: ${esc(preview.missing.join(', '))}</p>` : '<p class="hint">Every listed file is present.</p>'}
      <fieldset class="studio-fieldset"><legend>Map each legacy speaker</legend>
        ${preview.speakers.map(sp => `<label class="studio-inline">${esc(sp)} →
          <input class="input m" data-speaker="${esc(sp)}" value="${esc(sp)}"></label>`).join('')}</fieldset>
      ${(preview.tracks || []).length ? `<fieldset class="studio-fieldset"><legend>What each legacy source track is</legend>
        ${preview.tracks.map(t => `<label class="studio-inline">${esc(t.language)} (${esc(t.legacy_role)}) →
          <select class="input" data-track="${esc(t.key)}"><option value="">Choose…</option>
          ${ROLES.map(([v, n]) => `<option value="${v}">${n}</option>`).join('')}
          ${refs.map(r => `<option value="ref:${esc(r.id)}">${esc(r.label)}</option>`).join('')}</select></label>`).join('')}
      </fieldset>` : ''}
      <button type="button" class="btn btn-primary" id="ovImportApply">Import with this mapping</button></div>`;
    box.querySelector('#ovImportApply').onclick = async () => {
      const mapping = { speakers: {}, tracks: {} };
      box.querySelectorAll('[data-speaker]').forEach(i => { mapping.speakers[i.dataset.speaker] = i.value.trim(); });
      box.querySelectorAll('[data-track]').forEach(i => { if (i.value) mapping.tracks[i.dataset.track] = i.value; });
      try {
        const result = await api(`studio/sessions/${ctx.sid}/imports`, { method: 'POST', json: { path, mapping } });
        ctx.status(result.repeated ? 'Already imported; nothing changed.' : 'Imported. Play it from Compare.');
        await ctx.reload(); ctx.show('overview', { push: false });
      } catch (error) { ctx.status(error.message); }
    };
  } catch (error) { box.innerHTML = `<p class="review-marker">${esc(error.message)}</p>`; }
}
