import { api } from './api.js';
import { escapeHtml as esc } from './dom.js';

// Writing experiments: A (original only), B (English dub only, a diagnostic),
// C (original + aligned English). Frozen before judging; judged blind; the
// held-out official dub is revealed only on request, and the reveal is logged.

const DIMENSIONS = [
  ['source_meaning', 'Source meaning'], ['character_consistency', 'Character'],
  ['regional_naturalness', 'Regional naturalness'], ['humor', 'Humor'],
  ['visual_consistency', 'Fits the picture'], ['timing', 'Timing'],
  ['listening_preference', 'Preference'],
];
const NEUTRAL = ['same', 'neither', 'uncertain', 'n/a'];

export async function renderExperiments(box, ctx) {
  if (!box) return;
  const list = ctx.overview.experiments || [];
  const refs = ctx.overview.references || [];
  box.innerHTML = `<section class="panel studio-card" aria-labelledby="exHead">
    <h3 id="exHead">Writing experiments</h3>
    <p class="hint">Does an aligned English dub help the Spanish? A writes from the original only, B from
      the English dub only (a diagnostic), C from both. Region, scene notes, model and budget are held
      the same. Improvement is a question here, not an assumption.</p>
    <div id="exList">${list.map(e => `<div class="studio-align-row"><strong>${esc(e.name)}</strong>
      <span class="hint">${esc(e.conditions.join('/'))} · ${e.excerpts} excerpt(s) · ${esc(e.target_locale)}
        · ${esc(e.provider)}${e.model ? `/${esc(e.model)}` : ''}</span>
      <button type="button" class="btn btn-ghost" data-exp="${esc(e.id)}">Open</button></div>`).join('')
      || '<p class="hint">No experiment yet.</p>'}</div>
    <details class="studio-add"><summary>Define an experiment</summary>
      <div class="studio-inline">
        <label class="review-field">Name <input class="input" id="exName"></label>
        <label class="review-field">Original <select class="input" id="exMeaning">${refs.filter(r => r.roles.includes('meaning'))
          .map(r => `<option value="${esc(r.id)}">${esc(r.label)}</option>`).join('')}</select></label>
        <label class="review-field">English reference <select class="input" id="exAdapt"><option value="">None (A only)</option>
          ${refs.filter(r => r.roles.includes('adaptation')).map(r => `<option value="${esc(r.id)}">${esc(r.label)}</option>`).join('')}</select></label>
        <label class="review-field">Alignment <select class="input" id="exAlign"><option value="">None</option>
          ${(ctx.overview.alignments || []).map(a => `<option value="${esc(a.id)}">${esc(a.id)} r${a.revision}</option>`).join('')}</select></label>
      </div>
      <fieldset class="studio-fieldset"><legend>Held out for evaluation</legend>
        ${refs.filter(r => r.evaluation_only).map(r => `<label class="studio-check"><input type="checkbox" data-hold="${esc(r.id)}" checked> ${esc(r.label)}</label>`).join('')
          || '<p class="hint">None. The experiment still works; judge naturalness, timing and fidelity with a qualified reviewer.</p>'}</fieldset>
      <label class="review-field">Excerpts, one per line: id, start s, end s, title
        <textarea class="input m" id="exExcerpts" rows="4" placeholder="x1, 95, 140, Return to the village"></textarea></label>
      <label class="review-field">Decision criteria, written before looking at any result
        <textarea class="input" id="exCriteria" rows="2">C passes this pilot if it has no critical meaning regression and is preferred, or needs fewer corrections, on most excerpts. Added requests and time are reported alongside.</textarea></label>
      <label class="review-field">Scene notes (what is seen, never what is said), one per line: excerpt id: note
        <textarea class="input" id="exScenes" rows="2"></textarea></label>
      <div class="studio-inline">
        <label class="review-field">Region <input class="input m" id="exLocale" value="${esc(ctx.session.direction?.target_locale || 'es-MX')}"></label>
        <label class="review-field">Policy for C <select class="input" id="exPolicy">
          <option value="reference_suggestions">Original plus reference suggestions</option>
          <option value="follow_edition">Follow the English edition</option></select></label>
        <label class="review-field">Provider <input class="input m" id="exProvider" value="voicebox"></label>
        <label class="review-field">Model <input class="input m" id="exModel" placeholder="provider default"></label>
        <label class="review-field">Repeats <input class="input m" type="number" min="1" max="3" value="1" id="exRepeats"></label>
        <label class="review-field">Request budget <input class="input m" type="number" min="1" max="2000" value="60" id="exBudget"></label>
      </div>
      <button type="button" class="btn btn-primary" id="exCreate">Freeze this definition</button>
      <p class="hint">Freezing pins the alignment revision, the allowed inputs and the settings. A changed
        definition is a new experiment.</p>
    </details>
    <div id="exDetail"></div></section>`;
  box.querySelectorAll('[data-exp]').forEach(b => b.onclick = () => openExperiment(box, ctx, b.dataset.exp));
  box.querySelector('#exCreate').onclick = async () => {
    const excerpts = box.querySelector('#exExcerpts').value.split('\n').map(l => l.split(',').map(x => x.trim()))
      .filter(p => p.length >= 3).map(p => ({ excerpt_id: p[0], start: Number(p[1]), end: Number(p[2]),
        title: p.slice(3).join(', ') }));
    const scenes = Object.fromEntries(box.querySelector('#exScenes').value.split('\n')
      .map(l => l.split(':')).filter(p => p.length > 1).map(p => [p[0].trim(), p.slice(1).join(':').trim()]));
    const adaptation = box.querySelector('#exAdapt').value || null;
    try {
      const made = await api(`studio/sessions/${ctx.sid}/experiments`, { method: 'POST', json: {
        name: box.querySelector('#exName').value.trim(), meaning: box.querySelector('#exMeaning').value,
        adaptation, alignment: box.querySelector('#exAlign').value || null,
        evaluation: [...box.querySelectorAll('[data-hold]')].filter(c => c.checked).map(c => c.dataset.hold),
        conditions: adaptation ? ['A', 'B', 'C'] : ['A'], excerpts,
        decision_criteria: box.querySelector('#exCriteria').value,
        shared: { scene_notes: scenes }, policy: box.querySelector('#exPolicy').value,
        target_locale: box.querySelector('#exLocale').value.trim(),
        provider: box.querySelector('#exProvider').value.trim(), model: box.querySelector('#exModel').value.trim(),
        repeats: Number(box.querySelector('#exRepeats').value) || 1,
        max_requests: Number(box.querySelector('#exBudget').value) || 60 } });
      await ctx.reload();
      await renderExperiments(box, ctx);
      openExperiment(box, ctx, made.experiment.id);
    } catch (error) { ctx.status(error.message); }
  };
}

async function openExperiment(box, ctx, id) {
  const detail = box.querySelector('#exDetail');
  detail.innerHTML = '<p class="hint">Loading…</p>';
  const data = await api(`studio/experiments/${id}`);
  const e = data.experiment;
  detail.innerHTML = `<div class="studio-experiment">
    <h4>${esc(e.name)}</h4>
    <p class="hint">Predeclared: ${esc(e.decision_criteria)}</p>
    <div class="studio-actions">
      <button type="button" class="btn btn-primary" id="exRun">Write the conditions</button>
      <button type="button" class="btn btn-secondary" id="exEval">Judge blind</button></div>
    <p class="hint" id="exNote" role="status"></p>
    <table class="table"><thead><tr><th>Variant</th><th>State</th><th>Requests</th><th>Time</th><th>Inputs</th><th></th></tr></thead><tbody>
    ${data.variants.map(v => `<tr><td>${esc(v.condition)} · repeat ${v.repeat}</td>
      <td>${esc(v.status)}${v.error ? `<div class="review-marker">${esc(v.error)}</div>` : ''}
        ${v.missing_input?.length ? `<div class="hint">${v.missing_input.length} unit(s) had no English to write from</div>` : ''}</td>
      <td class="m">${v.usage?.provider_calls ?? 0}${v.usage?.cost == null ? ' · cost unknown' : ` · ${v.usage.cost}`}</td>
      <td class="m">${v.usage?.seconds ?? 0}s</td>
      <td><details><summary>Allowed / excluded</summary>
        <ul class="studio-list">${(v.manifest?.allowed || []).map(a => `<li>reads ${esc(a.label)} (${esc(a.role)})</li>`).join('')}
        ${(v.manifest?.excluded || []).map(x => `<li>never reads ${esc(x.label)}: ${esc(x.reason)}</li>`).join('')}
        <li>${v.guard_audit} request(s) scanned; ${v.memory_rejected || 0} memory candidate(s) dropped</li></ul></details></td>
      <td>${v.frozen && ctx.jobId() ? `<button type="button" class="btn btn-ghost" data-render="${esc(v.id)}">Speak it</button>` : ''}</td></tr>`).join('')
      || '<tr><td colspan="6" class="hint">Not written yet.</td></tr>'}</tbody></table>
    <details><summary>Limitations</summary><ul class="studio-list">${(e.limitations || []).map(l => `<li>${esc(l)}</li>`).join('')}</ul></details>
    <div id="exJudge"></div></div>`;
  const note = detail.querySelector('#exNote');
  detail.querySelector('#exRun').onclick = async () => {
    try {
      const r = await api(`studio/experiments/${id}/run`, { method: 'POST', json: {} });
      note.textContent = `Queued ${r.job.id}. Reopen when it finishes; cancelling keeps finished excerpts.`;
    } catch (error) { note.textContent = error.message; }
  };
  detail.querySelector('#exEval').onclick = async () => {
    try {
      const r = await api(`studio/experiments/${id}/evaluations`, { method: 'POST', json: {} });
      renderJudging(detail.querySelector('#exJudge'), r.evaluation.id);
    } catch (error) { note.textContent = error.message; }
  };
  detail.querySelectorAll('[data-render]').forEach(b => b.onclick = async () => {
    try {
      const r = await api(`studio/experiments/${id}/variants/${b.dataset.render}/render`,
        { method: 'POST', json: { job_id: ctx.jobId() } });
      note.textContent = `Queued ${r.job.id}: ${r.lines} line(s). ${r.note}`;
    } catch (error) { note.textContent = error.message; }
  });
  if (data.evaluations[0]) renderJudging(detail.querySelector('#exJudge'), data.evaluations[0].id);
}

async function renderJudging(box, id) {
  const { evaluation: ev, summary } = await api(`studio/evaluations/${id}`);
  let holdout = null;
  if (ev.revealed.holdout) holdout = (await api(`studio/evaluations/${id}/holdout`)).holdout;
  const mine = (unit, dim) => ev.judgments.find(j => j.unit_id === unit && j.dimension === dim);
  box.innerHTML = `<div class="studio-judging">
    <div class="studio-card-head"><h4>Blind judging</h4>
      ${ev.mapping ? `<span class="tag tag-neutral">${Object.entries(ev.mapping).map(([k, v]) => `${k} = ${v}`).join(' · ')}</span>`
        : '<button type="button" class="btn btn-ghost" data-reveal="labels">Reveal which version is which</button>'}
      ${ev.revealed.holdout ? '<span class="tag tag-outline">official dub revealed — later edits are assisted</span>'
        : '<button type="button" class="btn btn-ghost" data-reveal="holdout">Reveal the official dub</button>'}
      <a class="btn btn-ghost" href="/api/studio/evaluations/${esc(id)}/export" download="evaluation-${esc(id)}.json">Download results</a></div>
    <label class="studio-check"><input type="checkbox" id="jCompetent"> I read the source language (needed for a source-meaning verdict)</label>
    ${ev.units.map(u => `<div class="studio-unit" data-unit="${esc(u.unit_id)}">
      ${Object.entries(u.candidates).map(([label, lines]) => `<div class="studio-candidate-text">
        <strong>Version ${esc(label)}</strong>${lines.map(l => `<p data-label="${esc(label)}" data-slot="${esc(l.slot_id)}">${esc(l.text)}</p>`).join('')}
        <button type="button" class="btn btn-ghost" data-edit="${esc(label)}">Correct</button></div>`).join('')}
      ${holdout ? Object.values(holdout).map(h => `<div class="studio-candidate-text studio-holdout"><strong>${esc(h.label)}</strong>
        <p>${esc((h.units || {})[u.unit_id] || '—')}</p></div>`).join('') : ''}
      <div class="studio-dims">${DIMENSIONS.map(([dim, name]) => `<label class="review-filter">${name}
        <select class="input" data-dim="${dim}"><option value="">—</option>
        ${[...Object.keys(u.candidates).map(l => [l, `Version ${l}`]), ...NEUTRAL.map(n => [n, n])].map(([v, t]) =>
          `<option value="${esc(v)}" ${mine(u.unit_id, dim)?.choice === v ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></label>`).join('')}
        <label class="review-filter">Critical meaning error in <select class="input" data-critical>
          <option value="">none</option>${Object.keys(u.candidates).map(l => `<option value="${esc(l)}">Version ${esc(l)}</option>`).join('')}</select></label>
      </div></div>`).join('')}
    <div class="studio-summary"><h4>What the answers say so far</h4>
      <p>${esc(summary.gate.state)} — ${esc(summary.gate.reason)}</p>
      <p class="hint">${Object.entries(summary.conditions).map(([c, s]) =>
        `${c}: preferred ${Object.values(s.preferred).reduce((a, b) => a + b, 0)}×, ${s.critical} critical, `
        + `${s.corrections} correction(s), ${s.assisted_revisions} assisted`).join(' · ')}</p>
      <p class="hint">${Object.entries(summary.usage).map(([c, u]) => `${c}: ${u.provider_calls} request(s), `
        + `${u.seconds.toFixed(1)}s, cost ${u.cost == null ? 'unknown' : u.cost}`).join(' · ')}</p>
      <p class="hint">${esc(summary.note)}${summary.competent_source_review ? '' : ' No source-meaning verdict here came from a reviewer who reads the source.'}</p></div>
  </div>`;
  let revision = ev.revision;
  const post = async (path, json, params = '') => {
    const r = await api(`studio/evaluations/${id}/${path}?base_revision=${revision}${params}`, { method: 'POST', json });
    revision = r.evaluation.revision;
    return r;
  };
  box.querySelectorAll('[data-dim]').forEach(select => select.onchange = async () => {
    const unit = select.closest('[data-unit]');
    const critical = unit.querySelector('[data-critical]').value;
    try {
      await post('judgments', { unit_id: unit.dataset.unit, dimension: select.dataset.dim,
        choice: select.value || 'uncertain', critical: critical ? [critical] : [],
        source_competent: box.querySelector('#jCompetent').checked });
    } catch (error) { select.after(Object.assign(document.createElement('span'),
      { className: 'review-marker', textContent: error.message })); }
  });
  box.querySelectorAll('[data-reveal]').forEach(b => b.onclick = async () => {
    const what = b.dataset.reveal;
    if (what === 'holdout' && !window.confirm('Reveal the official dub? Judgments and corrections made after '
      + 'this are recorded as assisted, and the clean results stay as they are.')) return;
    await post(`reveal/${what}`, undefined, '&actor=studio');
    renderJudging(box, id);
  });
  box.querySelectorAll('[data-edit]').forEach(b => b.onclick = async () => {
    const unit = b.closest('[data-unit]');
    const line = unit.querySelector(`[data-label="${b.dataset.edit}"]`);
    const started = Date.now();
    const text = window.prompt('Corrected line (saved as a new revision; the frozen candidate stays):', line.textContent);
    if (!text) return;
    try {
      await post('revisions', { label: b.dataset.edit, unit_id: unit.dataset.unit, slot_id: line.dataset.slot,
        text, editing_seconds: (Date.now() - started) / 1000 });
      renderJudging(box, id);
    } catch (error) { b.textContent = error.message; }
  });
}
