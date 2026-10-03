import { useState } from 'react';
import { Link, redirect, useLoaderData, useNavigate } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { api, castParams, jobsFor, languageName, parseTitlePath, resolveTitleTab, titlePath } from '../../lib/legacy.js';
import { configQuery, ensure, queryClient } from '../../lib/queries.js';
import { useJobs } from '../../lib/jobs.js';
import { useOpenStudio } from '../../lib/studio.js';
import { isShow, titleHref } from '../../lib/library.js';
import { EpisodeAnalysis } from '../episode/EpisodeAnalysis.jsx';
import { castQuery, episodeItem, episodeQuery, identityBody, itemQuery, planQuery } from './queries.js';
import { QueueButton, StatusTag } from './parts.jsx';
import { EpisodesTab } from './EpisodesTab.jsx';
import { PlanTab } from './PlanTab.jsx';
import { VoicesTab } from './VoicesTab.jsx';
import { JobsTab } from './JobsTab.jsx';
import { MetaTab } from './MetaTab.jsx';
import { RecipesTab } from './RecipesTab.jsx';
import './title.css';

const TITLE_TABS = [['plan', 'Dub plan'], ['voices', 'Speakers & voices'], ['jobs', 'Jobs'], ['meta', 'Metadata'], ['recipes', 'Recipes']];

const samePath = (a, b) => {
  try { return decodeURIComponent(a) === decodeURIComponent(b); } catch { return a === b; }
};

// Everything the page needs before it renders: the title (or the episode and
// its show) and the settings plans inherit from. The plan itself starts
// loading here and fills in place, as the vanilla page did.
export async function titleLoader({ request }) {
  const url = new URL(request.url);
  const route = parseTitlePath(url.pathname);
  if (route.invalid) return { invalid: true };
  let data;
  try {
    [data] = await Promise.all([ensure(itemQuery(route.titleKey)), ensure(configQuery).catch(() => null)]);
  } catch (err) {
    if (err.status === 404) return { missing: true };
    throw err;
  }
  const parent = data.item;
  const targets = data.target_languages || ['en'];
  let item = parent;
  if (route.episodeId) {
    const found = await ensure(episodeQuery(parent.tvdb_id, route.episodeId, targets[0] || 'en'));
    item = episodeItem(parent, found.episode);
  }
  const tab = resolveTitleTab(item, route.titleTab);
  const path = titlePath(route.titleKey, route.episodeId, tab);
  if (!samePath(path, url.pathname)) throw redirect(path + url.search + url.hash);
  queryClient.prefetchQuery(planQuery(item));
  return { item, targets, tab, key: route.titleKey, episodeId: route.episodeId };
}

export const titleHandle = { nav: 'Library', title: match => (match.data?.item ? `${match.data.item.title} — ${match.data.tab}` : 'Title') };

function usePlan(item) {
  const query = planQuery(item);
  const { data: plan, error } = useQuery(query);
  const [saved, setStatus] = useState('');
  const status = saved || (error ? 'Could not load plan: ' + error.message : '');
  async function save(next) {
    queryClient.setQueryData(query.queryKey, next);
    setStatus('Saving…');
    try {
      await api('api/plan', { method: 'PUT', json: { title: item.title, plan: next, ...identityBody(item) } });
      setStatus('Saved ✓');
      return 'Saved ✓';
    } catch (err) {
      setStatus('Save failed: ' + err.message);
      return 'Save failed: ' + err.message;
    }
  }
  return { plan, status, setStatus, save, setValue: (key, value) => save({ ...(plan || {}), [key]: value }) };
}

function Stat({ label, id, children }) {
  return <div><p className="title-stat-head">{label}</p><p className="m title-stat-value" id={id}>{children}</p></div>;
}

function Hero({ item, targets, plan, onChooseEpisodes }) {
  const show = isShow(item);
  const openStudio = useOpenStudio();
  const { data: jobs } = useJobs();
  const { data: cast } = useQuery({ ...castQuery(item), retry: false });
  const target = plan?.target_lang || targets[0] || 'en';
  const langs = item.audio_langs?.length ? item.audio_langs.join(' · ') : (item.existing_audio || item.original);
  const notDownloaded = item.parent && !item.path;
  const lock = notDownloaded ? { disabled: true, title: 'Download this episode in Sonarr first' } : {};
  const castList = cast?.cast;
  return (
    <div className="panel title-hero">
      <div className="title-poster">
        <TitlePoster item={item} />
      </div>
      <div className="title-hero-body">
        <div className="title-hero-head">
          <div className="title-hero-name">
            <h2 className="title-name">{item.title}{item.year ? <> <span className="title-year">({item.year})</span></> : ''}</h2>
            <p className="m title-kind">{show ? 'TV Show' : item.parent ? 'Episode' : 'Movie'} · {item.original} · {langs}</p>
          </div>
          <div className="title-actions">
            {!show && <QueueButton item={item} kind="tease" targets={targets} label="Preview a tease" className="btn btn-secondary" id="tpTease" {...lock} />}
            {!show && <QueueButton item={item} kind="audition" targets={targets} label="Audition voices" className="btn btn-secondary" id="tpAudition" {...lock} />}
            {!show && item.path && <button type="button" className="btn btn-secondary" id="tpStudio"
              onClick={() => openStudio({ path: item.path, title: item.title,
                seriesRef: item.parent?.tvdb_id ? `series:${item.parent.tvdb_id}` : '' })}>Open studio</button>}
            <QueueButton item={item} kind="full" targets={targets} label={show ? 'Choose episodes' : 'Queue dub'}
              className="btn btn-primary title-queue" id="tpQueue" onShow={show ? onChooseEpisodes : undefined} {...lock} />
          </div>
        </div>
        <p className="title-explain">{show
          ? 'Choose episodes below. Each downloaded file gets its own job; missing episodes are never queued.'
          : `Queueing processes this ${item.parent ? 'episode' : 'movie'} file and writes an output with an extra audio track.`}</p>
        <div className="title-stats">
          <Stat label="Dub direction">{item.original} → {languageName(target)}</Stat>
          <Stat label="Audio tracks">{langs}</Stat>
          <Stat label="Jobs" id="tpStatJobs">{jobs ? String(jobsFor(item, jobs.jobs || []).length) : '—'}</Stat>
          <Stat label="Voices assigned" id="tpStatVoices">{castList ? (castList.length ? `${castList.filter(e => e.voice).length} / ${castList.length}` : '0') : '—'}</Stat>
        </div>
      </div>
    </div>
  );
}

function TitlePoster({ item }) {
  const [broken, setBroken] = useState(false);
  if (!item.poster || broken) return <div className="poster-fallback title-poster-img">{item.title}</div>;
  return <img className="poster-img title-poster-img" src={item.poster} alt="" onError={() => setBroken(true)} />;
}

function TabBody({ tab, item, targets, planState, goEpisode }) {
  const target = planState.plan?.target_lang || targets[0] || 'en';
  if (tab === 'recipes') {
    if (!planState.plan) return <div id="titleTabBody">Loading saved recipe settings…</div>;
    return (
      <div id="titleTabBody" className="panel">
        <RecipesTab item={item} target={target}
          onApplied={plan => {
            queryClient.setQueryData(planQuery(item).queryKey, plan);
            queryClient.invalidateQueries({ queryKey: ['cast'] });
          }} />
      </div>
    );
  }
  if (tab === 'episodes' && isShow(item)) {
    return (
      <div id="titleTabBody" className="panel episode-panel">
        <EpisodesTab item={item} target={target} targets={targets}
          onTarget={value => planState.setValue('target_lang', value)} onCast={goEpisode} />
      </div>
    );
  }
  if (tab === 'analysis' && item.episode_id) {
    return (
      <div id="titleTabBody" className="panel analysis-panel">
        <EpisodeAnalysis item={item} target={planState.plan?.target_lang || targets[0] || 'es'} />
      </div>
    );
  }
  let body;
  if (tab === 'plan') body = <PlanTab item={item} targets={targets} planState={planState} />;
  else if (tab === 'voices') body = <VoicesTab item={item} targets={targets} planState={planState} />;
  else if (tab === 'jobs') body = <JobsTab item={item} />;
  else body = <MetaTab item={item} targets={targets} />;
  return <div id="titleTabBody">{body}</div>;
}

function TitleView({ item, targets, tab, titleKey, episodeId }) {
  const navigate = useNavigate();
  const planState = usePlan(item);
  const show = isShow(item);
  const tabs = show ? [['episodes', 'Episodes'], ...TITLE_TABS.filter(([k]) => k !== 'recipes')]
    : item.episode_id ? [['analysis', 'Analysis'], ...TITLE_TABS] : TITLE_TABS;
  const goTab = next => navigate(titlePath(titleKey, episodeId, next));
  const goEpisode = (episode, next = 'analysis') => navigate(titlePath(titleKey, episode.id, next));
  const back = () => navigate(item.parent ? titleHref(item.parent, 'episodes') : '/library');

  return (
    <>
      <div className="title-topline">
        <button type="button" className="btn btn-ghost" id="titleBack" onClick={back}>← {item.parent ? item.parent.title : 'Library'}</button>
        <span className="m title-path">{item.path || ''}</span>
        <span className="title-tags">
          {show ? <span className="tag tag-accent">TV Show</span>
            : <><span className="tag tag-accent">{item.parent ? 'Episode' : 'Movie'}</span><StatusTag label={item.label} /></>}
          <span className="tag tag-neutral">{item.source}</span>
        </span>
      </div>
      <Hero item={item} targets={targets} plan={planState.plan} onChooseEpisodes={() => goTab('episodes')} />
      <div className="title-tabs">
        {tabs.map(([k, t]) => (
          <button key={k} type="button" className="tab" data-dtab={k} aria-current={tab === k ? 'page' : 'false'}
            onClick={() => goTab(k)}>{t}</button>
        ))}
      </div>
      <TabBody key={`${tab}:${castParams(item)}`} tab={tab} item={item} targets={targets}
        planState={planState} goEpisode={goEpisode} />
    </>
  );
}

export function Title() {
  const data = useLoaderData();
  let content;
  if (data.invalid) content = 'This episode or title URL is invalid. Open the title from Library.';
  else if (data.missing) {
    content = (
      <div className="panel title-missing">This title isn&apos;t in the current scan.{' '}
        <Link className="btn btn-ghost" id="titleBack" to="/library">← Library</Link></div>
    );
  } else {
    content = <TitleView key={data.key + ':' + (data.episodeId || '')} item={data.item} targets={data.targets}
      tab={data.tab} titleKey={data.key} episodeId={data.episodeId} />;
  }
  return <div id="titleRoot" className="title-root">{content}</div>;
}
