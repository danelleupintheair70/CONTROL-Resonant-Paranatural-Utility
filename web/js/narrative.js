import { api } from './api.js';
import { escapeHtml as esc } from './dom.js';
import { library } from './state.js';

// Title knowledge: what an episode's lines establish (who is who, what
// happens, how characters speak), reviewed by a person before it is used.
// Extraction is started from an analysed episode's Analysis tab; here a
// person reviews proposals, activates them as one revision, and retires what
// no longer holds. Jobs already queued keep the revision they froze.

const KIND = { character: 'Character', alias: 'Alias', relationship: 'Relationship', event: 'Event',
  location: 'Location', scene_intent: 'Scene intent', addressee: 'Addressee', behavior: 'Behaviour',
  speech_mode: 'Speech mode', term: 'Term', summary: 'Summary' };
const DECISION = { accept: 'Accepted', edit: 'Corrected', reject: 'Rejected', defer: 'Deferred' };
const clock = ms => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`;

export function seriesChoices() {
  const shows = (library.items || []).filter(i => i.media_type === 'show' && i.tvdb_id)
    .map(i => ({ id: `show:tvdb:${i.tvdb_id}`, label: i.title }));
  const movies = (library.items || []).filter(i => i.media_type === 'movie' && i.tmdb_id)
    .map(i => ({ id: `movie:tmdb:${i.tmdb_id}`, label: i.title }));
  return [...shows, ...movies].sort((a, b) => a.label.localeCompare(b.label));
}

export async function renderNarrative(body, view) {
  const choices = seriesChoices();
  body.innerHTML = `<div class="panel narrative-panel">
    <div class="narrative-pick">
      <label class="review-field">Show or film<select class="input" data-series>
        <option value="">Choose one</option>
        ${choices.map(c => `<option value="${esc(c.id)}" ${view.series === c.id ? 'selected' : ''}>${esc(c.label)}</option>`).join('')}
      </select></label>
      <label class="review-field">Or a series id<input class="input m" data-series-id value="${esc(view.series || '')}" placeholder="show:tvdb:12345"></label>
      <button type="button" class="btn btn-secondary" data-open>Open</button>
    </div>
    <p class="hint">Proposals come from analysed episodes and are never used until you accept them and activate a revision.</p>
    <div data-narrative></div></div>`;
  const open = () => {
    view.series = body.querySelector('[data-series-id]').value.trim() || body.querySelector('[data-series]').value;
    if (view.series) loadSeries(body.querySelector('[data-narrative]'), view);
  };
  body.querySelector('[data-series]').onchange = e => { body.querySelector('[data-series-id]').value = e.target.value; open(); };
  body.querySelector('[data-open]').onclick = open;
  if (view.series) loadSeries(body.querySelector('[data-narrative]'), view);
}

async function loadSeries(box, view) {
  box.innerHTML = '<p class="hint">Reading title knowledge…</p>';
  let data;
  try { data = await api(`narrative?series_id=${encodeURIComponent(view.series)}`); }
  catch (error) { box.innerHTML = `<p class="hint">${esc(error.message)}</p>`; return; }
  const names = data.characters || {};
  const subject = s => s.startsWith('character:') ? (names[s.slice(10)] || s.slice(10)) : s.split(':').pop();
  const say = msg => { const s = box.querySelector('[data-status]'); if (s) s.textContent = msg; };
  box.innerHTML = `
    <h4>Episodes</h4>
    ${data.coverage.length ? `<table class="table"><thead><tr><th>Episode</th><th>Draft</th><th>Proposals</th><th>To review</th><th>Conflicts</th><th>Active</th><th></th></tr></thead><tbody>
      ${data.coverage.map(r => `<tr><td class="m">${r.order ? `S${String(r.order[0]).padStart(2, '0')}E${String(r.order[1]).padStart(2, '0')}` : esc(r.media_id)}</td>
        <td>${esc(r.state)}<span class="hint"> · ${esc(r.model)}</span></td><td class="m">${r.candidates}</td>
        <td class="m">${r.needs_review}${r.stale ? ` <span class="hint">(${r.stale} changed)</span>` : ''}</td>
        <td class="m">${r.conflicts}</td><td class="m">${r.active_claims}</td>
        <td><button type="button" class="btn btn-ghost" data-draft="${esc(r.draft_id)}">Review</button></td></tr>`).join('')}
    </tbody></table>` : '<p class="hint">No episode of this series has proposals yet. Analyse an episode, then use Extract knowledge on its Analysis tab.</p>'}
    <div data-draft-box></div>
    <h4>Active knowledge <span class="hint">revision ${data.revision}</span></h4>
    <div class="studio-actions"><button type="button" class="btn btn-primary" data-activate>Activate reviewed knowledge</button>
      <span class="hint">Creates revision ${data.revision + 1}. New dubs use it; queued and finished dubs keep theirs.</span></div>
    <p class="hint" role="status" data-status></p>
    ${data.claims.length ? `<table class="table"><thead><tr><th>Kind</th><th>Statement</th><th>About</th><th>From</th><th></th></tr></thead><tbody>
      ${data.claims.map(c => `<tr><td>${esc(KIND[c.kind] || c.kind)}${c.conflicted ? ' <span class="tag tag-outline" title="Another accepted claim contradicts this one; neither is used until you retire one">conflict</span>' : ''}</td>
        <td>${esc(c.statement)}${c.corrected ? ' <span class="hint">(your correction)</span>' : ''}</td>
        <td>${(c.subjects || []).map(s => esc(subject(s))).join(', ') || '—'}</td>
        <td class="m">${c.available_from ? `S${c.available_from[0]}E${c.available_from[1]}` : 'this film'}${c.revealed_from ? ` · known from S${c.revealed_from[0]}E${c.revealed_from[1]}` : ''}</td>
        <td><button type="button" class="btn btn-ghost" data-retire="${esc(c.id)}">Retire</button></td></tr>`).join('')}
    </tbody></table>` : '<p class="hint">Nothing is active yet.</p>'}
    ${data.external.length ? `<h4>From library metadata</h4>${data.external.map(e => `<p class="hint">${esc(e.statement)} · ${esc(e.source)} · ${esc(e.fetched_at)} (not evidence from the episode)</p>`).join('')}` : ''}`;
  const activate = async retire => {
    try {
      const result = await api('narrative/activate', { method: 'POST', json: {
        series_id: view.series, base_revision: data.revision, retire: retire ? [retire] : [] } });
      await loadSeries(box, view);
      const status = box.querySelector('[data-status]');
      if (status) status.textContent = `Revision ${result.revision} is active with ${result.claims} claims. ${result.note}`;
    } catch (error) { say(error.message); }
  };
  box.querySelector('[data-activate]').onclick = () => activate(null);
  box.querySelectorAll('[data-retire]').forEach(b => b.onclick = () => activate(b.dataset.retire));
  box.querySelectorAll('[data-draft]').forEach(b => b.onclick = () =>
    reviewDraft(box.querySelector('[data-draft-box]'), b.dataset.draft, names, () => loadSeries(box, view)));
}

async function reviewDraft(box, draftId, names, refresh) {
  box.innerHTML = '<p class="hint">Reading the proposals…</p>';
  let data;
  try { data = await api(`narrative/draft/${encodeURIComponent(draftId)}`); }
  catch (error) { box.innerHTML = `<p class="hint">${esc(error.message)}</p>`; return; }
  const subject = s => s.startsWith('character:') ? (names[s.slice(10)] || s.slice(10)) : s.split(':').pop();
  box.innerHTML = `<div class="panel narrative-draft">
    <h4>Proposals <span class="hint">${data.candidates.length} · extracted by ${esc(data.model)} · ${esc(data.state)}</span></h4>
    <p class="hint">Each proposal cites the lines it rests on. A correction replaces the wording and survives later extractions.</p>
    ${data.candidates.map(row => {
      const p = row.proposal;
      const done = row.review && !row.stale ? DECISION[row.review.decision] : '';
      return `<div class="narrative-claim" data-candidate="${esc(row.candidate_id)}" data-revision="${row.review_revision}">
        <p><strong>${esc(KIND[p.kind] || p.kind)}</strong> ${esc(p.statement)}
          ${p.conflict_group ? '<span class="tag tag-outline">alternatives exist</span>' : ''}
          ${done ? `<span class="tag tag-neutral">${done}</span>` : row.stale ? '<span class="tag tag-outline">changed since your review</span>' : ''}</p>
        <p class="hint">${(p.subjects || []).map(s => esc(subject(s))).join(', ') || 'no named subject'}${p.confidence != null ? ` · model score ${p.confidence} (uncalibrated)` : ''} · ${esc((p.uncertainties || []).join(' '))}</p>
        <details><summary class="hint">${row.evidence.length} supporting line${row.evidence.length === 1 ? '' : 's'}</summary>
          ${row.evidence.map(e => `<p class="hint"><span class="m">${clock(e.start_ms)}</span> ${esc(e.text)}</p>`).join('')}</details>
        <div class="studio-actions">
          <button type="button" class="btn btn-ghost" data-decide="accept">Accept</button>
          <button type="button" class="btn btn-ghost" data-decide="edit">Correct</button>
          <button type="button" class="btn btn-ghost" data-decide="reject">Reject</button>
          <button type="button" class="btn btn-ghost" data-decide="defer">Later</button>
          <input class="input narrative-correction" maxlength="400" placeholder="Corrected statement" hidden value="${esc(row.review?.correction || p.statement)}">
        </div></div>`;
    }).join('')}
    <p class="hint" role="status" data-draft-status></p></div>`;
  box.querySelectorAll('.narrative-claim').forEach(claim => {
    const field = claim.querySelector('.narrative-correction');
    claim.querySelectorAll('[data-decide]').forEach(button => button.onclick = async () => {
      const decision = button.dataset.decide;
      if (decision === 'edit' && field.hidden) { field.hidden = false; field.focus(); return; }
      try {
        await api('narrative/review', { method: 'POST', json: {
          draft_id: draftId, candidate_id: claim.dataset.candidate, decision,
          correction: decision === 'edit' ? field.value.trim() : null,
          expected_revision: Number(claim.dataset.revision) } });
        await reviewDraft(box, draftId, names, refresh);
      } catch (error) { box.querySelector('[data-draft-status]').textContent = error.message; }
    });
  });
}
