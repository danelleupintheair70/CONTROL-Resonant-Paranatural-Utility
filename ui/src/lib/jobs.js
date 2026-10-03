import { useQuery } from '@tanstack/react-query';
import { jobsQuery } from './queries.js';
import { streamDown } from './events.js';

// The job queue, kept live by the event stream; polls every 30 s only while
// the stream is down.
export function useJobs() {
  return useQuery({ ...jobsQuery, refetchInterval: () => (streamDown() ? 30_000 : false) });
}

export function jobStatusClass(status) {
  return status === 'running' ? 'tag-accent'
    : status === 'failed' || status === 'cancelled' || status === 'planned' ? 'tag-outline' : 'tag-neutral';
}
