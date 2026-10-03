// How the review list is ordered and filtered.

export const ORDERS = [
  ['likely', 'Likeliest problems first'],
  ['timeline', 'Timeline'],
];

const start = row => row.source_start ?? row.start ?? 0;

export function orderRows(rows, order) {
  if (order !== 'likely') return [...rows];
  return [...rows].sort((a, b) =>
    (b.review_priority?.score || 0) - (a.review_priority?.score || 0) || start(a) - start(b));
}

// The order a review opens in: likeliest first when the run scored its lines.
export function defaultOrder(data) {
  return data?.settings?.review_order && data.segments?.some(s => s.review_priority?.score)
    ? 'likely' : 'timeline';
}

export const FILTERS = [
  ['all', 'All lines'], ['flagged', 'Any finding'], ['content', 'Wording'],
  ['timing', 'Timing'], ['technical', 'Audio'], ['performance', 'Performance'],
  ['delivery', 'Delivery'],
];

export function matchesFilter(row, filter) {
  if (filter === 'all') return true;
  const findings = row.cue?.findings || [];
  if (filter === 'flagged') return findings.length > 0 || row.issues.length > 0;
  return findings.some(f => f.kind === filter && f.disposition !== 'obsolete');
}
