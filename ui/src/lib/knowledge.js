// Language knowledge helpers: list queries, correction scopes, template summaries.

export function entriesQuery({ locale = '', kind = '', scope = '', status = '', q = '', page = 1, pageSize = 25 }) {
  const params = new URLSearchParams();
  if (locale) params.set('locale', locale);
  if (kind) params.set('kind', kind);
  if (scope) params.set('scope', scope);
  if (status) params.set('status', status);
  if (q) params.set('q', q);
  params.set('page', String(page));
  params.set('page_size', String(pageSize));
  return `knowledge/entries?${params}`;
}

export function pageCount(total, pageSize) {
  return Math.max(1, Math.ceil(total / pageSize));
}

// Scope choices offered for a correction, given the refs available in context.
export function scopeOptions({ lineRef = '', titleRef = '', showRef = '' }) {
  const options = [];
  if (lineRef) options.push({ value: 'line', label: 'This line only', ref: lineRef });
  if (titleRef) options.push({ value: 'episode', label: 'This episode / movie', ref: titleRef });
  if (showRef) options.push({ value: 'show', label: 'This show', ref: showRef });
  options.push({ value: 'personal', label: 'My general library', ref: '' });
  return options;
}

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
