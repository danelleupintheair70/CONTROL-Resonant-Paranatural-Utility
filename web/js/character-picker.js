// Picking who a voice is, from the show's cast instead of typing it again.
//
// A free-text name is one typo away from a second "Mina" ("mina",
// "Minna"), and every copy splits the show's share and its voice tag in
// two. So a name is chosen like a select2 field: typing searches the cast
// (case and accents ignored), the voices this one sounds closest to come
// first, a near miss offers the existing spelling, and a new character is
// one explicit option, never what happens on blur.
//
//   characterPicker({ label, value, placeholder, cast, suggestions, sharedWith, onPick })
//   cast:        [{ name, lines, episodes }]   everyone named in the show
//   suggestions: [{ name, similarity }]        closest named voices
//   sharedWith:  name -> other groups in this episode already using it

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export const fold = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();

export function distance(a, b) {
  if (a === b) return 0;
  const row = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i += 1) {
    let prev = row[0];
    row[0] = i;
    for (let j = 1; j <= b.length; j += 1) {
      const keep = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = keep;
    }
  }
  return row[b.length];
}

// The options for a query, in order. Pure, so it is tested without a page.
export function pickerOptions({ query = '', value = '', cast = [], suggestions = [] }) {
  const q = fold(query);
  const names = new Map();
  cast.forEach(c => names.set(fold(c.name), c));
  suggestions.forEach(s => { if (!names.has(fold(s.name))) names.set(fold(s.name), { name: s.name, lines: 0, episodes: 0 }); });
  const options = [];
  const seen = new Set();
  const add = (option) => { if (!seen.has(fold(option.name))) { seen.add(fold(option.name)); options.push(option); } };
  if (!q) {
    suggestions.forEach(s => add({ kind: 'closest', name: s.name, similarity: s.similarity }));
    [...names.values()].forEach(c => add({ kind: 'cast', name: c.name, lines: c.lines, episodes: c.episodes }));
  } else {
    const ranked = [...names.values()]
      .map(c => ({ c, f: fold(c.name) }))
      .filter(({ f }) => f.includes(q))
      .sort((a, b) => (b.f.startsWith(q) - a.f.startsWith(q)) || (b.c.lines - a.c.lines));
    ranked.forEach(({ c }) => add({ kind: 'cast', name: c.name, lines: c.lines, episodes: c.episodes,
      similarity: suggestions.find(s => fold(s.name) === fold(c.name))?.similarity }));
    if (q.length >= 3) {
      [...names.values()]
        .map(c => ({ c, d: distance(q, fold(c.name)) }))
        .filter(({ d }) => d > 0 && d <= (q.length >= 6 ? 2 : 1))
        .sort((a, b) => a.d - b.d)
        .forEach(({ c }) => add({ kind: 'did-you-mean', name: c.name, lines: c.lines }));
    }
    if (!names.has(q)) options.push({ kind: 'new', name: query.trim().replace(/\s+/g, ' ').slice(0, 80) });
  }
  if (value) options.push({ kind: 'clear', name: '' });
  return options;
}

let counter = 0;

export function characterPicker({ label, value = '', placeholder = '', cast = [], suggestions = [], sharedWith = {}, onPick }) {
  const id = `cp-${++counter}`;
  const root = document.createElement('div');
  root.className = 'cp';
  root.innerHTML = `<input class="input cp-input" role="combobox" aria-autocomplete="list" aria-expanded="false"
      aria-controls="${id}" aria-label="${esc(label)}" placeholder="${esc(placeholder)}" value="${esc(value)}" autocomplete="off" spellcheck="false" maxlength="80">
    <ul class="cp-list" id="${id}" role="listbox" hidden></ul>`;
  const input = root.querySelector('input');
  const list = root.querySelector('ul');
  let options = [], active = 0, open = false;

  const describe = o => {
    if (o.kind === 'new') return `<span class="cp-new">New character “${esc(o.name)}”</span>`;
    if (o.kind === 'clear') return '<span class="cp-muted">Clear the name</span>';
    const bits = [];
    if (o.kind === 'did-you-mean') bits.push('did you mean?');
    if (o.similarity) bits.push(`sounds ${Math.round(o.similarity * 100)}% alike`);
    if (o.lines) bits.push(`${o.lines} line${o.lines === 1 ? '' : 's'}${o.episodes > 1 ? ` · ${o.episodes} episodes` : ''}`);
    if (sharedWith[o.name]?.length) bits.push(`joins ${sharedWith[o.name].join(', ')}`);
    return `<span class="cp-name">${esc(o.name)}</span>${bits.length ? `<span class="cp-meta">${esc(bits.join(' · '))}</span>` : ''}`;
  };
  const heading = { closest: 'Sounds closest', cast: 'In this show', 'did-you-mean': 'Did you mean', new: '', clear: '' };

  function render() {
    let last = '';
    list.innerHTML = options.map((o, i) => {
      const head = heading[o.kind] && o.kind !== last ? `<li class="cp-head" role="presentation">${heading[o.kind]}</li>` : '';
      last = o.kind;
      return `${head}<li role="option" id="${id}-${i}" class="cp-option cp-${o.kind}" data-i="${i}" aria-selected="${i === active}">${describe(o)}</li>`;
    }).join('') || '<li class="cp-head" role="presentation">Nobody named yet: type a name</li>';
    input.setAttribute('aria-activedescendant', options.length ? `${id}-${active}` : '');
    list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
  }
  function refresh() {
    const query = input.value === value ? '' : input.value;
    options = pickerOptions({ query, value, cast, suggestions });
    active = 0;
    render();
  }
  function show() {
    if (open) return;
    open = true;
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    refresh();
  }
  function hide() {
    open = false;
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.value = value;                // nothing typed is kept unless it was picked
  }
  function choose(option) {
    if (!option) return;
    value = option.name;
    hide();
    onPick?.(value);
  }

  input.addEventListener('focus', () => { input.select(); show(); });
  input.addEventListener('click', show);
  input.addEventListener('input', () => { show(); refresh(); });
  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); show(); active = Math.min(options.length - 1, active + 1); render(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(0, active - 1); render(); }
    else if (e.key === 'Enter') { e.preventDefault(); if (open) choose(options[active]); else show(); }
    else if (e.key === 'Escape' && open) { e.preventDefault(); e.stopPropagation(); hide(); }
    else if (e.key === 'Tab') hide();
  });
  list.addEventListener('mousedown', e => {
    const item = e.target.closest('[data-i]');
    if (!item) return;
    e.preventDefault();                 // keep focus so blur does not close first
    choose(options[Number(item.dataset.i)]);
  });
  input.addEventListener('blur', () => setTimeout(() => { if (!root.contains(document.activeElement)) hide(); }, 0));
  return root;
}
