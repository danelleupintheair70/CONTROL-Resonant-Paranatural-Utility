// Title research helpers: which series a title is, and how to show what the
// catalogues and research runs found.

const LANGUAGE_NAMES = { en: 'English', es: 'Spanish', ja: 'Japanese', pt: 'Portuguese', fr: 'French',
  de: 'German', it: 'Italian', ko: 'Korean', zh: 'Chinese' };

// The series id research and the published cast are kept under: a show (or
// an episode's show) by its TVDB id, a film by its TMDB id.
export function seriesIdOf(item) {
  if (item?.parent) return item.parent.tvdb_id ? `show:tvdb:${item.parent.tvdb_id}` : '';
  const show = item?.media_type === 'show' || (!item?.media_type && /^sonarr/i.test(item?.source || ''));
  if (show) return item.tvdb_id ? `show:tvdb:${item.tvdb_id}` : '';
  return item?.tmdb_id ? `movie:tmdb:${item.tmdb_id}` : '';
}

// Voice columns: the original first, then the dub's language, then the rest.
export function languageColumns(characters, target = 'es') {
  const seen = [];
  for (const c of characters || []) {
    for (const v of c.voice_actors || []) {
      const lang = v.language || '';
      if (!seen.includes(lang)) seen.push(lang);
    }
  }
  const wanted = LANGUAGE_NAMES[String(target).split('-')[0]] || '';
  const rank = lang => (lang === 'Japanese' ? 0 : lang === wanted ? 1 : lang ? 2 : 3);
  return seen.sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

export function voicesIn(character, language) {
  return (character.voice_actors || []).filter(v => (v.language || '') === language);
}

// A Markdown answer as blocks of text and [n] citations linked to their pages.
// Only citations of pages the run opened become links; nothing is rendered as HTML.
export function citedParts(text, sources = []) {
  const urls = new Map((sources || []).filter(s => s.n != null).map(s => [Number(s.n), s.url]));
  const blocks = [];
  for (const raw of String(text || '').split(/\n+/)) {
    const line = raw.trim();
    if (!line) continue;
    let kind = 'para';
    let body = line;
    if (/^#{1,6}\s/.test(line)) { kind = 'heading'; body = line.replace(/^#+\s*/, ''); }
    else if (/^[-*]\s/.test(line)) { kind = 'item'; body = line.slice(2); }
    body = body.replace(/\*\*(.+?)\*\*/g, '$1');
    const parts = [];
    let last = 0;
    for (const m of body.matchAll(/\[(\d{1,3})\]/g)) {
      if (m.index > last) parts.push({ text: body.slice(last, m.index) });
      const n = Number(m[1]);
      parts.push(urls.has(n) ? { n, url: urls.get(n) } : { text: m[0] });
      last = m.index + m[0].length;
    }
    if (last < body.length) parts.push({ text: body.slice(last) });
    blocks.push({ kind, parts });
  }
  return blocks;
}
