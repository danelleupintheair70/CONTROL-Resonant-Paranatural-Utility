import { createBrowserRouter, redirect } from 'react-router';
import { ensure, languagesQuery } from './lib/queries.js';
import { Shell } from './shell/Shell.jsx';
import { BootScreen, NotPorted, RouteError } from './shell/BootScreen.jsx';
import { Overview, overviewLoader } from './pages/Overview.jsx';
import { Settings, settingsLoader } from './pages/Settings.jsx';

// Every route loads its data in `loader` before it renders: the boot screen
// covers the first load, a progress bar later ones, and a page never paints
// half-filled. `handle.nav` names the sidebar section, `handle.title` the tab.
export const router = createBrowserRouter([{
  path: '/',
  element: <Shell />,
  HydrateFallback: BootScreen,
  errorElement: <RouteError />,
  // Language names appear on most pages; the catalog is small and cached.
  loader: () => ensure(languagesQuery).then(() => null),
  children: [{
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Overview />, loader: overviewLoader, handle: { nav: 'Overview', title: 'Overview' } },
      { path: 'settings', loader: () => redirect('/settings/connections') },
      { path: 'settings/:tab', element: <Settings />, loader: settingsLoader, handle: { nav: 'Settings', title: 'Settings' } },
      { path: 'library', element: <NotPorted />, handle: { nav: 'Library', title: 'Library' } },
      { path: 'title/*', element: <NotPorted />, handle: { nav: 'Library', title: 'Title' } },
      { path: 'dubs', element: <NotPorted />, handle: { nav: 'Dubs', title: 'Dubs' } },
      { path: 'studio/*', element: <NotPorted />, handle: { nav: 'Dubs', title: 'Studio' } },
      { path: 'watch/:id', element: <NotPorted />, handle: { nav: 'Dubs', title: 'Watch' } },
      { path: 'voices/*', element: <NotPorted />, handle: { nav: 'Voices', title: 'Voices' } },
      { path: 'knowledge', element: <NotPorted />, handle: { nav: 'Knowledge', title: 'Knowledge' } },
      { path: '*', loader: () => redirect('/') },
    ],
  }],
}]);
