import { NotPorted } from '../../shell/BootScreen.jsx';

// Routes for this area; see docs/react-migration.md.
export const routes = [
  { path: 'dubs', element: <NotPorted />, handle: { nav: 'Dubs', title: 'Dubs' } },
  { path: 'watch/:id', element: <NotPorted />, handle: { nav: 'Dubs', title: 'Watch' } },
];
