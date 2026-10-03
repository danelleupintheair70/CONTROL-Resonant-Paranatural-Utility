import { Dubs, dubsLoader } from './Dubs.jsx';
import { Watch, watchLoader } from './Watch.jsx';

// Routes for this area; see docs/react-migration.md.
export const routes = [
  { path: 'dubs', element: <Dubs />, loader: dubsLoader, handle: { nav: 'Dubs', title: 'Dubs' } },
  { path: 'watch/:id', element: <Watch />, loader: watchLoader, handle: { nav: 'Dubs', title: 'Watch' } },
];
