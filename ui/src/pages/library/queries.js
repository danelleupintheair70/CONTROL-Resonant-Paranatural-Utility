import { api, castParams } from '../../lib/legacy.js';
import { queryClient } from '../../lib/queries.js';
import { itemKey } from '../../lib/library.js';

// One title by its URL key. Navigating from the Library page reuses the
// loaded scan; a deep link asks the server for that title alone.
export function itemQuery(key) {
  return {
    queryKey: ['library-item', key],
    queryFn: () => api(`library/item/${encodeURIComponent(key)}`),
    staleTime: 5 * 60_000,
    initialData: () => {
      const library = queryClient.getQueryData(['library']);
      const item = library?.items?.find(i => itemKey(i) === key);
      return item ? { item, target_languages: library.target_languages || ['en'] } : undefined;
    },
  };
}

// A show's episodes in one dub language (the show page lists them).
export function seriesEpisodesQuery(tvdbId, target) {
  return {
    queryKey: ['series-episodes', tvdbId, target],
    queryFn: () => api(`series/${tvdbId}/episodes?target_lang=${encodeURIComponent(target)}&refresh=false`),
  };
}

// One episode: from the show's list when it is loaded, else asked for alone.
export function episodeQuery(tvdbId, episodeId, target) {
  return {
    queryKey: ['episode', tvdbId, episodeId, target],
    queryFn: () => api(`series/${tvdbId}/episodes/${episodeId}?target_lang=${encodeURIComponent(target)}`),
    initialData: () => {
      const list = queryClient.getQueryData(['series-episodes', tvdbId, target]);
      const episode = list?.episodes?.find(e => e.id === episodeId);
      return episode ? { episode, target_lang: target } : undefined;
    },
  };
}

// The library item an episode page works on (the shape the vanilla UI built).
export function episodeItem(parent, ep) {
  return { ...parent, parent, media_type: 'episode', episode_id: ep.id,
    season: ep.season, episode_number: ep.episode, path: ep.path,
    title: `${parent.title} · S${String(ep.season).padStart(2, '0')}E${String(ep.episode).padStart(2, '0')} — ${ep.title}`,
    audio_langs: ep.audio_langs, label: ep.status, status: ep.status };
}

const identity = item => castParams(item).toString();

// A title's dub plan; an episode inherits its show's plan under its own.
export function planQuery(item) {
  return {
    queryKey: ['plan', identity(item), item.parent ? identity(item.parent) : ''],
    queryFn: async () => {
      const data = await api('plan?' + castParams(item));
      if (item.parent) {
        const parentPlan = await api('plan?' + castParams(item.parent));
        return { ...parentPlan.plan, ...data.plan };
      }
      return data.plan || {};
    },
  };
}

export const castQuery = item => ({
  queryKey: ['cast', identity(item)],
  queryFn: () => api('cast?' + castParams(item)),
});

export const voicesQuery = { queryKey: ['voices'], queryFn: () => api('voices') };

// The body the plan and cast endpoints take to name a title.
export function identityBody(item) {
  if (item.episode_id && !item.path) return { key: `episode:${item.tvdb_id}:${item.episode_id}` };
  if (item.path) return { path: item.path };
  if (item.tmdb_id) return { tmdb_id: item.tmdb_id };
  if (item.tvdb_id) return { tvdb_id: item.tvdb_id };
  return {};
}
