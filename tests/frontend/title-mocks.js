// The React title page asks for one title (/api/library/item/<key>) and one
// episode (/api/series/<id>/episodes/<episode>) instead of whole lists. These
// answer from the same fixture a spec gives /api/library and the episode list,
// so the vanilla and React pages are tested against the same data.

export function itemKey(item) {
  if (item.tmdb_id) return 'tmdb-' + item.tmdb_id;
  if (item.tvdb_id) return 'tvdb-' + item.tvdb_id;
  return 't-' + item.title + (item.year ? '-' + item.year : '');
}

export async function mockLibraryItems(page, library) {
  await page.route('**/api/library/item/**', route => {
    const path = new URL(route.request().url()).pathname;
    const key = decodeURIComponent(path.slice(path.indexOf('/api/library/item/') + '/api/library/item/'.length));
    const item = (library.items || []).find(i => itemKey(i) === key);
    return item
      ? route.fulfill({ json: { item, target_languages: library.target_languages || ['en'] } })
      : route.fulfill({ status: 404, json: { error: `${key} is not in the current library scan` } });
  });
}

// `episodes` is the episode-list payload, or a function of the dub language returning it.
export async function mockEpisodeLookup(page, tvdbId, episodes) {
  await page.route(`**/api/series/${tvdbId}/episodes/*`, route => {
    const url = new URL(route.request().url());
    const target = url.searchParams.get('target_lang');
    const data = typeof episodes === 'function' ? episodes(target) : episodes;
    const id = Number(url.pathname.split('/').pop());
    const episode = data.episodes.find(e => e.id === id);
    return episode
      ? route.fulfill({ json: { episode, target_lang: target, show: { title: data.title, tvdb_id: tvdbId } } })
      : route.fulfill({ status: 404, json: { error: 'Episode not found in Sonarr or Plex' } });
  });
}
