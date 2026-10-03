import { Library, libraryLoader } from './Library.jsx';
import { Title, titleHandle, titleLoader } from './Title.jsx';

// The library grid and one title's page (a film, a show, or one episode).
export const routes = [
  { path: 'library', element: <Library />, loader: libraryLoader, handle: { nav: 'Library', title: 'Library' } },
  { path: 'title/*', element: <Title />, loader: titleLoader, handle: titleHandle },
];
