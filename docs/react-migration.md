# The React UI

The web UI moved from vanilla JavaScript modules in `web/` to React in `ui/`
in October 2026. The vanilla routing was the reason: a deep link such as
`/title/<key>/episode/<id>/analysis` first painted Overview, waited for the
language list, downloaded the whole library to find one show, then every
episode of the series to find one, and repainted the page at each step.

## How a page loads now

- Every route in `ui/src/router.jsx` declares a `loader`. React Router runs it
  before the route renders, so a page draws once with its data.
- The first load shows one boot screen (`#boot`, painted by `ui/index.html`
  before any script runs). Later navigations keep the current page and show a
  thin progress bar until the next one is ready.
- Loaders fill one TanStack Query cache (`ui/src/lib/queries.js`, plus a
  `queries.js` per area). Components read it with `useQuery`; the SSE stream
  (`ui/src/lib/events.js`) invalidates what an event changed, and job lists
  poll only while the stream is down.
- An episode page reads `GET /api/library/item/{key}` and
  `GET /api/series/{tvdb_id}/episodes/{episode_id}` instead of the whole
  library and series.
- Data a page can show later (the library behind Overview's recent titles, a
  character's "where they talk") loads inside its own section, so a cold
  library scan never holds a page.

## Layout

- `ui/src/shell/`: sidebar, header, boot screen, new-dub dialog.
- `ui/src/pages/<area>/`: one folder per area with its `routes.jsx`, page
  components, `queries.js` and CSS (library + title, episode, dubs, voices +
  knowledge, studio). Overview and Settings sit directly in `pages/`.
- `ui/src/components/`: pieces several areas use (media player, character
  picker, knowledge correction).
- `ui/src/lib/`: API transport, storage, query cache, events, and pure
  helpers tested with `node --test`.
- `ui/src/styles/`: the shared CSS carried over from `web/styles` unchanged;
  page-specific classes live next to their components.

## Building and serving

- `npm run dev:ui` serves the UI with live reload on :5363 and proxies `/api`
  to a running server on :6363.
- `npm run build:ui` writes `ui/dist`, which `doblarr serve` serves from a
  checkout. A wheel carries it as `doblarr/web` (`setup.py`), and both
  Dockerfiles build it in a Node stage.
- Built assets have content-hashed names and are served `immutable`;
  `index.html` and the public files revalidate.

## Consistency

The browser specs in `tests/frontend/*.spec.js` were the acceptance bar during
the move: each page was ported until its specs passed against the React build,
with the element ids, labels and text they select kept. Spec changes were
limited to mocking the two new single-item endpoints
(`tests/frontend/title-mocks.js`) and reading the settings field list from
Node instead of the page.
