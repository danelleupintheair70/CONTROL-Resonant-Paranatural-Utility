import { redirect } from 'react-router';
import { ensure, queryClient } from '../../lib/queries.js';
import { isView, viewLabel } from './controller.js';
import { castingQuery, exportQuery, studioQuery, studioVoicesQuery } from './queries.js';
import { Studio } from './Studio.jsx';

const studioPath = (sid, view) => `/studio/${encodeURIComponent(sid)}/${view}`;

// The session (and what the first view reads) before the page renders. A
// missing or unknown view goes to the one the studio was last on.
async function studioLoader({ params }) {
  const overview = await queryClient.fetchQuery(studioQuery(params.sid));
  if (!isView(params.view)) throw redirect(studioPath(params.sid, overview.session.view || 'overview'));
  const job = overview.active_job?.id;
  if (params.view === 'cast') await Promise.all([ensure(castingQuery(params.sid)), ensure(studioVoicesQuery)]).catch(() => null);
  if (params.view === 'export' && job) await ensure(exportQuery(params.sid, job)).catch(() => null);
  return { title: overview.session.title };
}

const handle = { nav: 'Dubs', title: match => `${match.data?.title || 'Studio'} — ${viewLabel(match.params.view)}` };

export const routes = [
  { path: 'studio', loader: () => redirect('/dubs') },
  { path: 'studio/:sid', element: <Studio />, loader: studioLoader, handle },
  { path: 'studio/:sid/:view', element: <Studio />, loader: studioLoader, handle },
];
