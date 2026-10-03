import { api } from './api.js';
import { escapeHtml as esc } from './dom.js';

// The names and terms an episode keeps saying (doblarr/key_terms.py): how
// this dub says each one, how the official dub in the same language says it
// when the file has one, and the wording kept for the show. A wording kept
// here is the show's: every later translation uses it, and a line that says
// the term another way is rewritten.

const clock = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

function drifts(row) {
  const ours = row.ours;
  return Boolean(ours && (ours.share < 1 || ours.variants.length));
}

function sideText(side, count) {
  if (!side || !side.rendering) return '<span class="hint">—</span>';
  const held = Math.round(side.share * count);
  const other = side.variants.map(v => `<span class="terms-variant" title="${v.cues.length} line${v.cues.length === 1 ? '' : 's'}">${esc(v.rendering)}</span>`).join('');
  return `${esc(side.rendering)}${held < count ? ` <span class="hint m">${held}/${count}</span>` : ''}${other}`;
}

export function termsSection(data) {
  const terms = data.terms;
  if (!terms || (!terms.rows.length && !terms.other_saved.length)) return '';
  const rows = [...terms.rows].sort((a, b) =>
    (drifts(b) - drifts(a)) || ((a.kind === 'name') - (b.kind === 'name')) || (b.count - a.count));
  const drifting = rows.filter(drifts).length;
  const kept = rows.filter(r => r.saved).length + terms.other_saved.length;
  const official = terms.official?.title;
  return `<details class="analysis-terms"${drifting ? ' open' : ''}>
    <summary>Names and terms <span class="hint">${rows.length} said more than once${drifting ? ` · <strong>${drifting}</strong> said more than one way` : ''}${kept ? ` · ${kept} kept for the show` : ''}</span></summary>
    <p class="hint">Words the episode keeps saying. Keep one wording for the show and every episode uses it; lines that say it another way are rewritten when the dub is made.${official ? ` The official ${esc(official)} dub is transcribed beside ours: its translators saw the picture, so take its wording as a suggestion.` : ''}${terms.show ? '' : ' This episode is not linked to a show yet, so nothing can be kept.'}</p>
    <div class="terms-table" role="table" aria-label="Names and terms">
      <div class="terms-row terms-headrow" role="row"><span role="columnheader">Says</span><span role="columnheader">Our dub</span>${official ? `<span role="columnheader">${esc(official)} dub</span>` : ''}<span role="columnheader">For the show</span></div>
      ${rows.map((row, n) => `<div class="terms-row${drifts(row) ? ' terms-drift' : ''}${official ? '' : ' terms-two'}" role="row" data-term-row="${n}">
        <span role="cell"><button type="button" class="terms-open" data-term-lines="${n}" aria-expanded="false">${esc(row.term)}</button> <span class="hint m">${row.count}×</span></span>
        <span role="cell">${sideText(row.ours, row.count)}</span>
        ${official ? `<span role="cell">${row.dub?.rendering ? `<button type="button" class="analysis-suggest analysis-suggest-alt" data-term-use="${n}" title="Use the official dub's wording">${esc(row.dub.rendering)}</button>` : '<span class="hint">not heard</span>'}</span>` : ''}
        <span role="cell" class="terms-keep">${terms.show ? `<input class="input" data-term-input="${n}" value="${esc(row.saved?.rendering || row.ours?.rendering || row.dub?.rendering || '')}" aria-label="Wording of ${esc(row.term)} for the show">
          ${row.saved ? `${row.saved.reviewed ? '<span class="terms-kept">kept</span>' : ''}<button type="button" class="btn btn-ghost" data-term-save="${n}">${row.saved.reviewed ? 'Change' : 'Confirm'}</button><button type="button" class="btn btn-ghost" data-term-forget="${n}">Forget</button>`
            : `<button type="button" class="btn btn-ghost" data-term-save="${n}">Keep</button>`}` : ''}</span>
        <div class="terms-lines" data-term-detail="${n}" hidden>${row.lines.map(l => `<p><span class="m">${clock(l.start || 0)}</span> ${esc(l.text)}<br><span class="terms-ours">${esc(l.ours || '—')}</span>${official ? `<br><span class="hint">${esc(official)}: ${esc(l.dub || '—')}</span>` : ''}</p>`).join('')}</div>
      </div>`).join('')}
    </div>
    ${terms.other_saved.length ? `<p class="hint terms-other">Also kept for the show: ${terms.other_saved.map((s, i) => `<span class="terms-saved">${esc(s.term)} → ${esc(s.rendering)}${s.reviewed ? '' : ` <button type="button" class="btn btn-ghost" data-other-confirm="${i}" title="Saved but not confirmed, so translations do not use it yet">Confirm</button>`}</span>`).join(' · ')}</p>` : ''}
  </details>`;
}

export function mountTerms(box, data, { path, reload, say }) {
  const terms = data.terms;
  if (!terms) return;
  const rows = [...terms.rows].sort((a, b) =>
    (drifts(b) - drifts(a)) || ((a.kind === 'name') - (b.kind === 'name')) || (b.count - a.count));
  const keep = async (source, rendering) => {
    try {
      await api('analysis/terms', { method: 'PUT', json: { path, source, rendering, locale: terms.locale } });
      await reload();
      say(rendering ? `“${source}” is “${rendering}” for the whole show now.` : `“${source}” has no set wording now.`);
    } catch (error) { say(error.message); }
  };
  box.querySelectorAll('[data-term-lines]').forEach(b => b.onclick = () => {
    const detail = box.querySelector(`[data-term-detail="${b.dataset.termLines}"]`);
    detail.hidden = !detail.hidden;
    b.setAttribute('aria-expanded', String(!detail.hidden));
  });
  box.querySelectorAll('[data-term-use]').forEach(b => b.onclick = () => {
    const input = box.querySelector(`[data-term-input="${b.dataset.termUse}"]`);
    if (input) { input.value = rows[Number(b.dataset.termUse)].dub.rendering; input.focus(); }
  });
  box.querySelectorAll('[data-term-save]').forEach(b => b.onclick = () => {
    const n = Number(b.dataset.termSave);
    const value = box.querySelector(`[data-term-input="${n}"]`).value.trim();
    if (value) keep(rows[n].term, value);
  });
  box.querySelectorAll('[data-term-forget]').forEach(b => b.onclick = () => keep(rows[Number(b.dataset.termForget)].term, ''));
  box.querySelectorAll('[data-other-confirm]').forEach(b => b.onclick = () => {
    const saved = terms.other_saved[Number(b.dataset.otherConfirm)];
    keep(saved.term, saved.rendering);
  });
}
