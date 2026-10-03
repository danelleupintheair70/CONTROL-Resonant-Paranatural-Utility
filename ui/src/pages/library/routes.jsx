import { NotPorted } from '../../shell/BootScreen.jsx';

// Routes for this area; see docs/react-migration.md.
export const routes = [
  { path: 'library', element: <NotPorted />, handle: { nav: 'Library', title: 'Library' } },
  { path: 'title/*', element: <NotPorted />, handle: { nav: 'Library', title: 'Title' } },
];
