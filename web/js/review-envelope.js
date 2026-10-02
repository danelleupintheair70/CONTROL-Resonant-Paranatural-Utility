import { api, apiUrl } from './api.js';
import { escapeHtml as esc, safeGet } from './dom.js';

// One line's voice envelope in review: what was chosen and why, what the
// render actually did, the other candidates, and the same take heard four
// ways. Changing the envelope queues a rerender that reuses the take (no new
// speech); the panel says so before anything runs.

const cache = new Map();          // job id -> recommendations
let player = null;

const ORIGIN = { manual: 'chosen by hand', judge: 'chosen by the judge', retrieval: 'retrieval (rule)',
  default: 'fallback', none: 'not chosen' };
const OUTCOME = { applied: 'rendered', preserved: 'kept as generated', bypassed: 'suggested, not rendered',
  unsupported: 'not supported here', unavailable: 'not available', unknown: 'not rendered yet' };
const PROBLEMS = [['envelope', 'Envelope'], ['level', 'Level'], ['acting', 'Acting'], ['timing', 'Timing'],
  ['background', 'Background'], ['identity', 'Wrong speaker'], ['source_evidence', 'Bad source evidence']];

function audioUrl(jobId, cue, kind, matched = false) {
  const key = safeGet('doblarr_api_key', '');
  return apiUrl(`adaptive/audio?job_id=${encodeURIComponent(jobId)}&cue=${encodeURIComponent(cue)}`
    + `&kind=${kind}${matched ? '&level_matched=true' : ''}`) + (key ? `&api_key=${encodeURIComponent(key)}` : '');
}

export function forget(jobId) { cache.delete(jobId); }

export async function envelopePanel(host, { jobId, row }) {
  const cue = row?.cue?.cue_id;
  if (!host || !jobId || !cue) return;
  host.innerHTML = '<p class="hint">Reading the envelope recommendations…</p>';
  let data = cache.get(jobId);
  if (!data) {
    try { data = await api(`adaptive/recommendations?job_id=${encodeURIComponent(jobId)}`); }
    catch (error) { host.innerHTML = `<p class="hint">${esc(error.message)}</p>`; return; }
    cache.set(jobId, data);
  }
  const line = data.lines.find(l => l.cue === cue);
  if (!line) { host.innerHTML = ''; return; }
  let templates = [];
  try { templates = (await api('templates?kind=voice')).templates; } catch { /* list stays empty */ }
  const env = line.envelope || {};
  const chosen = env.template?.id || '';
  const said = msg => { const s = host.querySelector('[data-env-status]'); if (s) s.textContent = msg; };
  const mode = data.mode === 'off' ? 'Envelopes are off for this run; a choice made here still applies.'
    : `Mode ${esc(data.mode)} · decided by ${esc(data.judge || 'retrieval')}${data.judge_is_model ? '' : ' (a rule, not a model)'}`;
  host.innerHTML = `<details class="envelope-panel" open>
    <summary><strong>Voice envelope</strong> <span class="hint">${chosen ? esc(chosen) : 'none'} · ${esc(ORIGIN[env.origin] || 'not chosen')} · ${esc(OUTCOME[env.outcome] || '')}</span></summary>
    <p class="hint">${mode}</p>
    ${env.template?.id ? `<p class="hint">${env.outcome === 'applied'
      ? `Applied at strength ${(env.applied ?? 0).toFixed(2)} of ${(env.requested ?? 0).toFixed(2)} asked`
        + `${env.preserved > 0.05 ? `; ${Math.round(env.preserved * 100)}% of the shape was already in the take` : ''}`
        + ` · moves ${(env.range_db ?? 0).toFixed(1)} dB inside the line · peak ${(env.peak ?? 0).toFixed(2)}`
      : esc(env.reason || '')}</p>` : ''}
    ${line.warnings?.length ? `<p class="hint">${line.warnings.map(esc).join(' ')}</p>` : ''}
    <div class="envelope-listen">
      <button type="button" class="btn btn-ghost" data-hear="dry">Take as generated</button>
      <button type="button" class="btn btn-ghost" data-hear="shaped">With envelope</button>
      <button type="button" class="btn btn-ghost" data-hear="shaped-matched" title="The envelope at the same overall level as the take, so only the shape differs">With envelope, level-matched</button>
      <button type="button" class="btn btn-ghost" data-hear="source">Original</button>
      <button type="button" class="btn btn-ghost" data-hear="mixed">In the mix</button>
    </div>
    ${line.candidates?.length ? `<table class="table envelope-candidates"><thead><tr><th>Template</th><th>Score</th><th>Why</th></tr></thead><tbody>
      ${line.candidates.map(c => `<tr><td>${esc(c.title)}${c.template.id === chosen ? ' <span class="tag tag-neutral">chosen</span>' : ''}</td>
        <td class="m">${c.score.toFixed(2)}</td>
        <td class="hint">${[...c.support.map(esc), ...c.conflicts.map(x => `but ${esc(x)}`)].join('; ') || '—'}</td></tr>`).join('')}
    </tbody></table>` : '<p class="hint">No recommendation was made for this line.</p>'}
    <div class="envelope-choose">
      <label class="review-field">Template<select class="input" data-env-template>
        ${templates.map(t => `<option value="${esc(t.id)}" ${t.id === (chosen || 'voice/preserve') ? 'selected' : ''}>${esc(t.title)}</option>`).join('')}</select></label>
      <label class="review-field">Strength <input class="input m" type="number" min="0" max="1.5" step="0.05" data-env-strength value="${(env.requested || 1).toFixed(2)}"></label>
      <button type="button" class="btn btn-secondary" data-env-apply>Render this envelope</button>
      <button type="button" class="btn btn-ghost" data-env-clear>Keep as generated</button>
      ${line.locked ? '<button type="button" class="btn btn-ghost" data-env-undo>Undo my choice</button>' : ''}
    </div>
    <p class="hint">Changing the envelope reprocesses the existing take and remixes. No new speech is generated.</p>
    <div class="envelope-verdict">
      <span class="hint">How does it sound?</span>
      <button type="button" class="btn btn-ghost" data-verdict="accept">Good</button>
      <button type="button" class="btn btn-ghost" data-verdict="reject">Not right</button>
      <select class="input" data-problem aria-label="What is wrong">${PROBLEMS.map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
    </div>
    <p class="hint" role="status" data-env-status></p>
  </details>`;
  host.querySelectorAll('[data-hear]').forEach(button => button.onclick = () => {
    const kind = button.dataset.hear;
    player?.pause();
    player = new Audio(audioUrl(jobId, cue, kind.startsWith('shaped') ? 'shaped' : kind, kind === 'shaped-matched'));
    player.play().catch(error => said(`Could not play: ${error.message}`));
    said(kind === 'shaped-matched' ? 'Level-matched: the loudness difference is removed on purpose.' : '');
  });
  const select = async body => {
    try {
      const result = await api('adaptive/select', { method: 'POST', json: { job_id: jobId, cue, ...body } });
      forget(jobId);
      said(`Queued (${result.note}) The new render appears as a new run.`);
    } catch (error) { said(error.message); }
  };
  host.querySelector('[data-env-apply]').onclick = () => select({
    template: host.querySelector('[data-env-template]').value,
    strength: Number(host.querySelector('[data-env-strength]').value) });
  host.querySelector('[data-env-clear]').onclick = () => select({ clear: true });
  const undo = host.querySelector('[data-env-undo]');
  if (undo) undo.onclick = () => select({ undo: true });
  host.querySelectorAll('[data-verdict]').forEach(button => button.onclick = async () => {
    const verdict = button.dataset.verdict;
    try {
      const saved = await api('adaptive/feedback', { method: 'POST', json: {
        job_id: jobId, cue, verdict, template: env.template || {}, params: env.params || {},
        artifact: env.inputs || '', decision: env.decision || '',
        problems: verdict === 'reject' ? [host.querySelector('[data-problem]').value] : [] } });
      if (verdict !== 'accept') { said('Saved. It stays out of future recommendations.'); return; }
      said('Saved. ');
      const promote = document.createElement('button');
      promote.type = 'button'; promote.className = 'btn btn-ghost'; promote.textContent = 'Use as an example for similar lines';
      promote.onclick = async () => {
        try {
          await api('adaptive/examples', { method: 'POST', json: { feedback_id: saved.id, job_id: jobId } });
          said('Added. Future recommendations can learn from this line.');
        } catch (error) { said(error.message); }
      };
      host.querySelector('[data-env-status]').append(promote);
    } catch (error) { said(error.message); }
  });
}
