import { useRouteError } from 'react-router';

// Covers the app until the first route's data is in, so a deep link renders
// its page once instead of passing through Overview and partial states.
export function BootScreen() {
  return <div id="boot" role="status">Loading Doblarr…</div>;
}

// A loader that failed: say what failed, keep the shell around it.
export function RouteError() {
  const error = useRouteError();
  const message = error?.status === 404 ? (error.data || 'Not found') : (error?.message || String(error));
  return (
    <div className="page">
      <div className="panel route-error" role="alert">
        <p className="route-error-title">This page couldn&apos;t load.</p>
        <p className="hint">{message}</p>
      </div>
    </div>
  );
}

// Routes still served by the vanilla UI until their phase lands.
export function NotPorted() {
  return (
    <div className="page">
      <div className="panel route-error">
        <p className="route-error-title">Not moved to React yet.</p>
        <p className="hint">This page still lives in the vanilla UI. See docs/react-migration.md.</p>
      </div>
    </div>
  );
}
