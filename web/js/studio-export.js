import { api } from './api.js';
import { escapeHtml as esc } from './dom.js';

// Export: exactly what the chosen version contains, what is stale, and what
// is still open — then hand it over without generating speech by surprise.

export async function renderExport(body, ctx) {
  const job = ctx.jobId();
  if (!job) {
    body.innerHTML = '<div class="panel studio-empty"><p>Nothing to export yet: no run has finished.</p></div>';
    return;
  }
  body.innerHTML = '<p class="hint">Reading the run…</p>';
  let plan;
  try { plan = await api(`studio/sessions/${ctx.sid}/export?job_id=${job}`); } catch (error) {
    body.innerHTML = `<div class="panel studio-empty"><p>${esc(error.message)}</p></div>`; return;
  }
  const blocked = ctx.session.unresolved === 'block_export' && plan.unresolved.length;
  body.innerHTML = `
    <section class="panel studio-card">
      <h3>What this export contains</h3>
      <p>${plan.lines.length} line(s) · ${plan.stale} stale · ${plan.unresolved.length} unresolved finding(s)
        · ${plan.timing_edits} timing edit(s) · ${plan.manual_gains} manual gain(s)</p>
      <p class="hint">${esc(plan.note)} ${plan.version_saved ? `Saved version ${esc(plan.version_id.slice(0, 12))} holds this run.`
        : 'This run has no saved version.'} The original media and earlier versions are never changed;
        publishing to a library is a separate step.</p>
      <div class="studio-actions">
        <button type="button" class="btn btn-primary" id="exGo" ${blocked ? 'disabled' : ''}>Export the selected version</button>
        ${blocked ? '<span class="review-marker">Unresolved findings block export under this studio\'s policy.</span>' : ''}
      </div>
      <p class="hint" id="exNote" role="status"></p>
    </section>
    ${plan.unresolved.length ? `<section class="panel studio-card"><h3>Open findings</h3>
      <ul class="studio-list">${plan.unresolved.map(u => `<li><button type="button" class="btn btn-ghost" data-line="${u.line}">Line ${u.line + 1}</button>
        ${esc(u.code.replaceAll('_', ' '))} <span class="tag ${u.severity === 'error' ? 'tag-outline' : 'tag-neutral'}">${esc(u.severity)}</span></li>`).join('')}</ul>
      <p class="hint">Technical findings rank what to listen to. They are not acting judgments, and
        dismissing one is a decision you record in Dialogue.</p></section>` : ''}
    <section class="panel studio-card"><h3>Line by line</h3>
      <table class="table"><thead><tr><th>Line</th><th>Speaker</th><th>Dialogue</th><th>Take</th><th>State</th></tr></thead><tbody>
      ${plan.lines.map(l => `<tr><td class="m">${l.index + 1}</td><td>${esc(l.speaker)}</td><td>${esc(l.text || '')}
        ${l.spoken && l.spoken !== l.text ? `<div class="hint">spoken as: ${esc(l.spoken)}</div>` : ''}</td>
        <td class="m">${esc((l.take || '—').slice(0, 14))}</td>
        <td>${l.stale ? '<span class="review-marker">stale: the audio says older words</span>'
          : `<span class="hint">${esc(l.selection || 'auto')}</span>`}</td></tr>`).join('')}
      </tbody></table></section>`;
  body.querySelectorAll('[data-line]').forEach(b => b.onclick = async () => {
    await ctx.savePatch({ line: Number(b.dataset.line) });
    ctx.show('dialogue');
  });
  body.querySelector('#exGo').onclick = async e => {
    const note = body.querySelector('#exNote');
    e.currentTarget.disabled = true;
    try {
      const result = await api(`studio/sessions/${ctx.sid}/export?job_id=${job}`, { method: 'POST',
        json: { base_revision: plan.revision } });
      note.textContent = result.exported === 'existing'
        ? `Exported saved version ${result.version_id.slice(0, 12)}. ${result.note}`
        : `Queued ${result.job}. ${result.note}`;
    } catch (error) {
      note.textContent = error.data?.lines
        ? `${error.message} (lines ${error.data.lines.join(', ')})` : error.message;
    }
    e.currentTarget.disabled = false;
  };
}
