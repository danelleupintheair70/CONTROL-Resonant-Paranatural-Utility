// Matching typed names against a show's cast: case and accents ignored,
// near misses found by edit distance.

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
