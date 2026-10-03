import { resolveTitleTab, titlePath } from './title-routing.js';

// Stable identity for a library item in the URL: an external id when the
// source provides one, else the title (+ year) as text.
export function itemKey(item) {
  if (item.tmdb_id) return 'tmdb-' + item.tmdb_id;
  if (item.tvdb_id) return 'tvdb-' + item.tvdb_id;
  return 't-' + item.title + (item.year ? '-' + item.year : '');
}

export function titleHref(item, tab) {
  return titlePath(itemKey(item), null, resolveTitleTab(item, tab));
}

export function isShow(item) {
  return item.media_type === 'show' || (!item.media_type && /^sonarr/i.test(item.source || ''));
}

export function statusClass(label) {
  return label === 'needs-dub' ? 'tag-accent' : (label === 'partial' || label === 'review') ? 'tag-outline' : 'tag-neutral';
}
