import { api } from '../../lib/api.js';

// The studio's server reads. The session overview stays cached only while the
// studio is open (a short gcTime), so reopening it reads the server again.
export const studioQuery = sid => ({
  queryKey: ['studio', sid, 'overview'],
  queryFn: () => api(`studio/sessions/${sid}`),
  staleTime: Infinity,
  gcTime: 5_000,
});

export const castingQuery = sid => ({
  queryKey: ['studio', sid, 'casting'],
  queryFn: () => api(`studio/sessions/${sid}/casting`),
  gcTime: 5_000,
});

// The engine's voice list for audition candidates; an empty list when it fails.
export const studioVoicesQuery = {
  queryKey: ['studio', 'voice-list'],
  queryFn: () => api('voices').then(r => r.voices || []).catch(() => []),
};

export const exportQuery = (sid, job) => ({
  queryKey: ['studio', sid, 'export', job],
  queryFn: () => api(`studio/sessions/${sid}/export?job_id=${job}`),
  staleTime: 0,
  gcTime: 5_000,
});

export const probeQuery = sid => ({
  queryKey: ['studio', sid, 'probe'],
  queryFn: () => api(`studio/sessions/${sid}/probe`),
  gcTime: 5_000,
});
