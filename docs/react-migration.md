# Moving the web UI to React

The vanilla UI in `web/` grew page by page, and its routing shows it: a deep
link such as `/title/<key>/episode/<id>/analysis` first paints Overview (the
only section not `hidden` in `index.html`), waits for `/api/languages`, then
downloads the whole library to find one show, then every episode of the series
to find one, and each step repaints the page. The new UI loads what a route
needs first and renders it once.

## Stack

- **Vite + React 19, plain JS/JSX.** Same language as today, so the pure
  modules (`settings-model.js`, `title-routing.js`, `review-order.js`, …) and
  their `node --test` suites move over unchanged.
- **React Router (data mode).** Every route declares a `loader`; the router
  resolves it before rendering. A boot screen covers the app until the first
  route is ready, and later navigations show one progress bar, never a half
  page.
- **TanStack Query** as the cache behind the loaders (`ensureQueryData`), so
  going back to a page is instant and SSE events invalidate exactly the data
  they change.
- **Existing CSS.** `web/styles/**` is imported as is, so pages look the same;
  inline `style=""` strings from the template literals become classes as each
  page is ported.

## Consistency bar

The Playwright specs in `tests/frontend/*.spec.js` select by role, label and
text, with the API mocked through `page.route`. They are the acceptance test:
a page is ported when its specs pass against the React build. Specs change only
where a page now calls a narrower endpoint (the mock follows the request), never
to loosen an assertion.

## Layout during the move

- `ui/` holds the new app (`ui/src`, `ui/index.html`, `vite.config.js`).
  `npm run dev:ui` proxies `/api` to the running server.
- `web/` keeps serving production until cutover, so the app is never half
  migrated for anyone using it.
- The server serves `ui/dist` instead of `web/` when `DOBLARR_UI=react` is
  set, which is how the specs run against the new build.

## Server endpoints for single items

- `GET /api/library/item/{key}`: one library item by its URL key
  (`tmdb-…`, `tvdb-…`, `t-<title>-<year>`), read from the scan cache.
- `GET /api/series/{tvdb_id}/episodes/{episode_id}`: one episode with its
  parent show, so an episode page never pulls the whole series.

## Phases

1. **Shell.** Vite scaffold, router, sidebar, top bar, theme, boot screen,
   event stream, server flag, Playwright project for the React build.
   Overview and Settings.
2. **Library and Title.** Library grid with filters; title page with its tabs
   (episodes, plan, voices, jobs, meta, recipes) on the single-item endpoints.
3. **Episode.** Analysis, evidence, terms, scene review: the route the move
   started from.
4. **Dubs.** Jobs table, queue controls, review, Watch.
5. **Voices and Knowledge.**
6. **Studio.** The largest page (cast, player, experiments, export).
7. **Cutover.** `ui/dist` becomes the served UI; `web/js` and `index.html`
   are deleted; Dockerfiles gain a Node build stage; CI, `MANIFEST.in`,
   `dev.ps1`/`dev.sh` and the README follow.
