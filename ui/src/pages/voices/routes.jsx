import { NotPorted } from '../../shell/BootScreen.jsx';

// Routes for this area; see docs/react-migration.md.
export const routes = [
  { path: 'voices/*', element: <NotPorted />, handle: { nav: 'Voices', title: 'Voices' } },
  { path: 'knowledge', element: <NotPorted />, handle: { nav: 'Knowledge', title: 'Knowledge' } },
];
