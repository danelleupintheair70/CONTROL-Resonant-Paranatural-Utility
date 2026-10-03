import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { ensure, hardwareQuery, jobsQuery, libraryQuery, statusQuery } from '../lib/queries.js';
import { useJobs } from '../lib/jobs.js';
import { useLogLines } from '../lib/events.js';
import { hardwareSummary } from '../lib/hardware.js';
import { itemKey, titleHref } from '../lib/library.js';
import { Poster } from '../components/Poster.jsx';

export async function overviewLoader() {
  // Jobs, counts and the GPU card are quick; recent titles wait on the library
  // scan inside their own section, so a cold scan never holds the page.
  await Promise.all([ensure(jobsQuery), ensure(statusQuery).catch(() => null), ensure(hardwareQuery)]);
  return null;
}

const byRecent = (a, b) => (b.updated_at || '').localeCompare(a.updated_at || '');

function Stat({ id, value, label, labelId, accent, title }) {
  return (
    <div className="panel stat-card" title={title}>
      <p id={id} className={`m stat-value${accent ? ' stat-accent' : ''}`}>{value}</p>
      <p id={labelId} className="stat-label">{label}</p>
    </div>
  );
}

function RecentTitles({ jobs }) {
  const titles = [...new Set([...jobs].sort(byRecent).map(j => j.title))].slice(0, 8);
  const { data: library, isPending } = useQuery({ ...libraryQuery, enabled: titles.length > 0 });
  if (!titles.length) return <div className="overview-empty">Nothing yet — queue a dub from the Library.</div>;
  if (isPending) return <div className="overview-empty">Loading the library…</div>;
  const items = titles.map(t => (library?.items || []).find(i => i.title === t)).filter(Boolean);
  if (!items.length) return <div className="overview-empty">Recent jobs are for titles no longer in the scan.</div>;
  return items.map(item => (
    <Link key={itemKey(item)} to={titleHref(item)} className="poster-card poster-link">
      <Poster item={item} />
      <div className="poster-body"><div className="poster-title">{item.title}</div></div>
    </Link>
  ));
}

function InProgress({ jobs }) {
  const active = jobs.filter(j => j.status === 'running' || j.status === 'queued');
  if (!active.length) return <div className="panel overview-card overview-muted">Nothing in progress — queue a dub from the Library.</div>;
  return active.map(j => (
    <div key={j.id} className="panel overview-card">
      <div className="progress-head">
        <span className="progress-title">{j.title}</span>
        <span className="m progress-langs">{j.source_lang} → {j.target_lang}</span>
        <span className={`tag ${j.status === 'running' ? 'tag-accent' : 'tag-neutral'} progress-stage`}>
          {j.status === 'running' ? (j.message || j.stage || 'running') : 'queued'}</span>
      </div>
      <div className="bar progress-bar"><span style={{ width: `${j.progress || 0}%` }} /></div>
      <div className="m progress-pct">{j.progress || 0}%{j.status === 'running' && j.message ? ` — ${j.message}` : ''}</div>
    </div>
  ));
}

const EVENT = { done: 'Dub completed', failed: 'Job failed', running: 'Processing', queued: 'Queued' };
const EVENT_TAG = { done: 'tag-neutral', failed: 'tag-outline', running: 'tag-accent', queued: 'tag-neutral' };

function Activity({ jobs }) {
  const recent = [...jobs].sort(byRecent).slice(0, 6);
  if (!recent.length) return <tr><td colSpan="4" className="overview-muted">No activity yet.</td></tr>;
  return recent.map(j => (
    <tr key={j.id}>
      <td className="m activity-time">{(j.updated_at || '').slice(11, 16)}</td>
      <td>{EVENT[j.status] || j.status}</td>
      <td>{j.title}</td>
      <td><span className={`tag ${EVENT_TAG[j.status] || 'tag-neutral'}`}>{j.status}</span></td>
    </tr>
  ));
}

function LogPanel() {
  const lines = useLogLines();
  return (
    <details className="panel log-panel">
      <summary>Logs <span className="m log-sub">live from the server (last 200 lines)</span></summary>
      <pre id="logBox" className="m log-box" ref={el => { if (el) el.scrollTop = el.scrollHeight; }}>{lines.join('\n')}</pre>
    </details>
  );
}

export function Overview() {
  const { data } = useJobs();
  const { data: status } = useQuery(statusQuery);
  const { data: hw } = useQuery(hardwareQuery);
  const jobs = data?.jobs || [];
  const counts = data?.counts || {};
  const gpu = hardwareSummary(hw, hw?.memory);
  // No scan yet means no needs-dub count; the library scan fills it.
  const needsScan = status?.counts?.needs_dub == null;
  const { data: library } = useQuery({ ...libraryQuery, enabled: needsScan });
  const needsDub = status?.counts?.needs_dub ?? library?.counts?.needs_dub ?? '—';

  return (
    <div className="page">
      <div className="cards4">
        <Stat id="statRunning" value={counts.running || 0} label="Jobs running" accent />
        <Stat id="statQueued" value={counts.queued || 0} label="Queued" />
        <Stat id="statNeedsDub" value={needsDub} label={<>Flagged <span className="m">needs-dub</span></>} />
        <Stat id="statGpu" labelId="statGpuLabel" value={gpu.percent == null ? '—' : `${gpu.percent}%`}
          label={gpu.memory ? `${gpu.device} · ${gpu.memory}` : `${gpu.device} · ${gpu.label}`}
          title={[gpu.label, ...(hw?.notes || [])].join('\n')} />
      </div>

      <h3 className="overview-heading">Recent titles</h3>
      <div id="recentTitles" className="poster-grid overview-posters"><RecentTitles jobs={jobs} /></div>

      <h3 className="overview-heading">In progress</h3>
      <div id="inProgress" className="overview-stack"><InProgress jobs={jobs} /></div>

      <h3 className="overview-heading overview-heading-tight">Recent activity</h3>
      <div className="panel activity-panel">
        <table className="table">
          <thead><tr><th className="activity-col-time">Time</th><th>Event</th><th>Item</th><th className="activity-col-result">Result</th></tr></thead>
          <tbody id="activityBody"><Activity jobs={jobs} /></tbody>
        </table>
      </div>

      <LogPanel />
    </div>
  );
}
