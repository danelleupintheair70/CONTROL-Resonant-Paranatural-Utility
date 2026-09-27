import { api, apiUrl } from './api.js';
import { escapeHtml as esc, safeGet } from './dom.js';

// Cast: who speaks with which voice, where that choice came from, and
// auditions that compare voices on the same fixed lines.

const KINDS = [
  ['current', 'Current voice', 'the takes this run already has; nothing is generated'],
  ['preset', 'Preset voice', 'a voice from the engine\'s catalogue'],
  ['directed', 'Directed preset', 'a preset plus a delivery instruction (only engines that accept one)'],
  ['clone_character', 'Clone the original actor', 'one clean line of this character\'s original performance'],
  ['clone_line', 'Clone each line (experimental)', 'unstable on short lines; not castable'],
];

let playing = null;

export async function renderCast(body, ctx) {
  const job = ctx.jobId();
  body.innerHTML = '<p class="hint">Loading the cast…</p>';
  let cast, voices = [];
  try {
    [cast, voices] = await Promise.all([
      api(`studio/sessions/${ctx.sid}/casting`),
      api('voices').then(r => r.voices || []).catch(() => []),
    ]);
  } catch (error) { body.textContent = error.message; return; }
  const auditions = ctx.overview.auditions || [];
  body.innerHTML = `
    <section class="panel studio-card" aria-labelledby="castNow">
      <h3 id="castNow">Who speaks with which voice</h3>
      ${cast.speakers.length ? `<table class="table"><thead><tr><th>Speaker</th><th>Voice</th><th>Decided at</th><th></th></tr></thead><tbody>
        ${cast.speakers.map(r => `<tr><td><strong>${esc(r.speaker)}</strong>${r.character !== r.speaker ? ` <span class="hint">(${esc(r.character)})</span>` : ''}</td>
          <td class="m">${esc(r.voice || '—')}${r.engine ? ` <span class="hint">${esc(r.engine)}</span>` : ''}</td>
          <td>${r.source === 'none' ? '<span class="hint">not decided — the run\'s own cast applies</span>'
            : `<span class="tag ${r.source === 'episode' ? 'tag-accent' : 'tag-neutral'}">${esc(r.source)}</span>`}
            ${r.overrides_series ? '<span class="review-marker">overrides the series choice</span>' : ''}</td>
          <td>${r.source === 'series' ? `<button type="button" class="btn btn-ghost" data-affected="${esc(r.character)}">Who follows this</button>` : ''}</td></tr>`).join('')}
      </tbody></table>` : `<p class="hint">${job ? 'This run has no speakers yet.' : 'Render a draft to discover the speakers.'}</p>`}
      ${cast.line_exceptions.length ? `<p class="hint">Line exceptions: ${cast.line_exceptions.map(l =>
        `${esc(l.cue_id)} → ${esc(l.voice)}`).join(', ')}</p>` : ''}
      <div id="castAffected"></div>
    </section>

    <section class="panel studio-card" aria-labelledby="castAudition">
      <h3 id="castAudition">Audition a character</h3>
      ${job ? `<p class="hint">Fixed lines from this run, chosen by what the original actor did — calm, quiet,
        intense, in an exchange. Every candidate says the same lines through the same processing.</p>
      <div class="studio-inline">
        <label class="review-field">Character <select class="input" id="auChar">${cast.speakers.map(r =>
          `<option>${esc(r.speaker)}</option>`).join('')}</select></label>
        <label class="review-field">Lines per type <input class="input m" type="number" min="1" max="3" value="1" id="auPer"></label>
        <label class="review-field">Retakes if flagged <input class="input m" type="number" min="0" max="2" value="0" id="auRetakes"></label>
        <label class="review-field">Request budget <input class="input m" type="number" min="1" max="400" value="40" id="auBudget"></label>
        <label class="studio-check"><input type="checkbox" id="auCheck"> Check words by recognition</label>
      </div>
      <div id="auCandidates"></div>
      <div class="studio-actions">
        <button type="button" class="btn btn-ghost" id="auAdd">Add a candidate</button>
        <button type="button" class="btn btn-primary" id="auCreate">Plan the audition</button></div>`
      : '<p class="hint">Auditions use a finished run\'s lines. Render a draft first.</p>'}
    </section>

    ${auditions.map(a => `<section class="panel studio-card studio-audition" data-audition="${esc(a.id)}">
      <p class="hint">Loading audition ${esc(a.character)}…</p></section>`).join('')}`;
  const wireAll = () => body.querySelectorAll('[data-affected]').forEach(b => b.onclick = async () => {
    const found = await api(`studio/sessions/${ctx.sid}/casting/affected?character=${encodeURIComponent(b.dataset.affected)}`);
    body.querySelector('#castAffected').innerHTML = `<div class="studio-import"><p>${esc(found.note)}</p>
      <p>Would follow a new series choice: ${found.follow.map(f => esc(shortRef(f.episode))).join(', ') || 'none'}</p>
      <p>Keep their own: ${found.keep.map(f => `${esc(shortRef(f.episode))} (${esc(f.voice || '')})`).join(', ') || 'none'}</p></div>`;
  });
  wireAll();
  if (job) auditionForm(body, ctx, voices);
  for (const a of auditions) renderAudition(body.querySelector(`[data-audition="${a.id}"]`), ctx, a.id);
}

function shortRef(ref) { return String(ref).split(/[\\/]/).pop(); }

function candidateRow(n, voices) {
  return `<div class="studio-candidate" data-row="${n}">
    <label class="review-field">Name <input class="input m" data-f="name" value="${['current', 'preset', 'clone'][n] || `c${n}`}"></label>
    <label class="review-field">Kind <select class="input" data-f="kind">${KINDS.map(([v, l]) =>
      `<option value="${v}" ${(['current', 'preset', 'clone_character'][n] || 'preset') === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
    <label class="review-field">Engine <input class="input m" data-f="engine" placeholder="chatterbox, qwen_custom_voice…"
      value="${n === 2 ? 'chatterbox' : ''}"></label>
    <label class="review-field">Voice <select class="input" data-f="voice"><option value="">—</option>
      ${voices.map(v => `<option value="${esc(v.id)}">${esc(v.name)}</option>`).join('')}</select></label>
    <label class="review-field">Direction <input class="input" data-f="direction" placeholder="only for directed presets"></label>
  </div>`;
}

function auditionForm(body, ctx, voices) {
  const box = body.querySelector('#auCandidates');
  let rows = 3;
  box.innerHTML = [0, 1, 2].map(n => candidateRow(n, voices)).join('')
    + `<p class="hint">${KINDS.map(([, l, note]) => `<strong>${l}</strong>: ${note}`).join('. ')}.</p>`;
  body.querySelector('#auAdd').onclick = () => {
    if (rows >= 6) return;
    box.insertAdjacentHTML('beforeend', candidateRow(rows, voices)); rows += 1;
  };
  body.querySelector('#auCreate').onclick = async () => {
    const candidates = [...box.querySelectorAll('.studio-candidate')].map(r => {
      const get = f => r.querySelector(`[data-f="${f}"]`).value.trim();
      return { name: get('name'), kind: get('kind'), engine: get('engine'), voice: get('voice'),
        direction: get('direction') };
    }).filter(c => c.name);
    try {
      await api(`studio/sessions/${ctx.sid}/auditions`, { method: 'POST', json: {
        character: body.querySelector('#auChar').value, job_id: ctx.jobId(),
        per_category: Number(body.querySelector('#auPer').value) || 1,
        retakes: Number(body.querySelector('#auRetakes').value) || 0,
        max_requests: Number(body.querySelector('#auBudget').value) || 40,
        check_words: body.querySelector('#auCheck').checked, candidates } });
      await ctx.reload(); ctx.show('cast', { push: false });
    } catch (error) { ctx.status(error.message); }
  };
}

async function renderAudition(box, ctx, id) {
  if (!box) return;
  let a;
  try { a = (await api(`studio/auditions/${id}`)).audition; } catch (error) { box.textContent = error.message; return; }
  const plan = a.plan || { excerpts: [], missing: [], notes: [] };
  const runnable = !['running'].includes(a.status);
  box.innerHTML = `
    <div class="studio-card-head"><h3>Audition: ${esc(a.character)}</h3>
      <span class="tag tag-neutral">${esc(a.status)}</span>
      ${a.usage?.budget ? `<span class="hint">${a.usage.budget.spent} request(s) spent${a.usage.budget.limit ? ` of ${a.usage.budget.limit}` : ''}</span>` : ''}
      <button type="button" class="btn btn-secondary" data-run ${runnable ? '' : 'disabled'}>${a.status === 'planned' ? 'Generate takes' : 'Continue / retry missing takes'}</button></div>
    ${a.error ? `<p class="review-marker">${esc(a.error)}</p>` : ''}
    ${plan.notes.map(n => `<p class="hint">${esc(n)}</p>`).join('')}
    <div class="studio-audition-grid" role="table" aria-label="Candidates by line">
      <div role="row" class="studio-audition-row"><span role="columnheader">Line</span>
        ${a.candidates.map(c => `<span role="columnheader"><strong>${esc(c.name)}</strong>
          <span class="hint">${esc(c.kind.replace('_', ' '))}${c.engine ? ` · ${esc(c.engine)}` : ''}</span>
          ${c.status && c.status !== 'generated' ? `<span class="review-marker">${esc(c.status)}${c.reason ? `: ${esc(c.reason)}` : ''}</span>` : ''}
          ${(c.reference_findings?.findings || []).map(f => `<span class="hint">${esc(f.code.replace('reference_', ''))}: ${esc(f.detail)}</span>`).join('')}
        </span>`).join('')}</div>
      ${plan.excerpts.map(x => `<div role="row" class="studio-audition-row">
        <span role="cell"><span class="tag tag-neutral">${esc(x.category)}</span> ${esc(x.text)}
          <span class="hint">line ${x.index + 1}${x.relative_db != null ? ` · original ${x.relative_db > 0 ? '+' : ''}${x.relative_db} dB` : ''}</span></span>
        ${a.candidates.map(c => {
          const take = (a.takes[c.name] || {})[x.cue_id];
          return `<span role="cell">${take?.available
            ? `<button type="button" class="btn btn-ghost" data-play="${esc(c.name)}" data-cue="${esc(x.cue_id)}">Play</button>
               ${take.clean === false ? '<span class="review-marker">flagged</span>' : ''}${take.reused ? '<span class="hint">reused</span>' : ''}`
            : `<span class="hint">${esc(take?.state || '—')}</span>`}</span>`;
        }).join('')}</div>`).join('')}
    </div>
    ${plan.missing.length ? `<p class="hint">Missing performance types: ${esc(plan.missing.join(', '))}.</p>` : ''}
    <div class="studio-actions">${a.candidates.filter(c => ['preset', 'directed', 'clone_character'].includes(c.kind)
      && c.status === 'generated').map(c => `
      <button type="button" class="btn btn-secondary" data-pick="${esc(c.name)}" data-scope="episode">Cast ${esc(c.name)} for this episode</button>
      <button type="button" class="btn btn-ghost" data-pick="${esc(c.name)}" data-scope="series">…for the series</button>
      <button type="button" class="btn btn-primary" data-pick="${esc(c.name)}" data-scope="episode" data-apply="1">Cast and re-render only ${esc(a.character)}</button>`).join('')}</div>
    <p class="hint" role="status" data-note></p>`;
  box.querySelector('[data-run]').onclick = async () => {
    try {
      const r = await api(`studio/auditions/${id}/run`, { method: 'POST' });
      box.querySelector('[data-note]').textContent = `Queued ${r.job.id}. Takes appear as they finish; cancelling keeps what is done.`;
    } catch (error) { box.querySelector('[data-note]').textContent = error.message; }
  };
  box.querySelectorAll('[data-play]').forEach(b => b.onclick = () => {
    const key = safeGet('doblarr_api_key', '');
    playing?.pause();
    playing = new Audio(`${apiUrl(`studio/auditions/${id}/takes/${b.dataset.play}/${b.dataset.cue}`)}${key ? `?api_key=${encodeURIComponent(key)}` : ''}`);
    playing.play().catch(error => { box.querySelector('[data-note]').textContent = error.message; });
  });
  box.querySelectorAll('[data-pick]').forEach(b => b.onclick = async () => {
    const note = box.querySelector('[data-note]');
    try {
      const r = await api(`studio/auditions/${id}/select`, { method: 'POST', json: {
        candidate: b.dataset.pick, scope: b.dataset.scope, apply: !!b.dataset.apply } });
      note.textContent = r.rerender ? r.rerender.note : 'Casting saved. Nothing was re-rendered.';
      await ctx.reload();
    } catch (error) { note.textContent = error.message; }
  });
}
