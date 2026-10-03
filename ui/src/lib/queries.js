import { QueryClient } from '@tanstack/react-query';
import { api, loadLanguages } from './legacy.js';

// One cache for every page. Loaders fill it before a route renders
// (`queryClient.ensureQueryData`); components read it with useQuery, and the
// event stream invalidates what an event changed.
export const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: false, refetchOnWindowFocus: false } },
});

export const jobsQuery = { queryKey: ['jobs'], queryFn: () => api('jobs') };
export const statusQuery = { queryKey: ['status'], queryFn: () => api('status') };
export const configQuery = { queryKey: ['config'], queryFn: () => api('config') };
export const hardwareQuery = { queryKey: ['hardware'], queryFn: () => api('hardware').catch(() => null) };
// The library scan can take seconds on a cold server; only pages that list it wait for it.
export const libraryQuery = { queryKey: ['library'], queryFn: () => api('library'), staleTime: 5 * 60_000 };
// languages.js keeps its own session cache (languageName reads it synchronously).
export const languagesQuery = { queryKey: ['languages'], queryFn: loadLanguages, staleTime: Infinity };

export const ensure = query => queryClient.ensureQueryData(query);
