import { Library, libraryLoader } from './Library.jsx';
import { Title, titleHandle, titleLoader } from './Title.jsx';
import { AudioLanguages } from './AudioLanguages.jsx';

// The library grid, its audio languages, and one title's page (a film, a show, or one episode).
export const routes = [
  { path: 'library', element: <Library />, loader: libraryLoader, handle: { nav: 'Library', title: 'Library' } },
  { path: 'library/audio', element: <AudioLanguages />, handle: { nav: 'Library', title: 'Audio languages' } },
  { path: 'title/*', element: <Title />, loader: titleLoader, handle: titleHandle },
];
