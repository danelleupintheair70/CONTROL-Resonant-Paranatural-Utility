import { api } from '../../lib/legacy.js';
import { queryClient } from '../../lib/queries.js';

// Voices and knowledge data. Saving anything here invalidates what it changed.
export const catalogQuery = { queryKey: ['voice-catalog'], queryFn: () => api('voice-catalog').then(r => r.voices || []) };
export const charactersQuery = { queryKey: ['characters'],
  queryFn: () => api('characters').then(r => r.characters || []).catch(() => []) };
export const voiceQuery = key => ({ queryKey: ['voice', key],
  queryFn: () => api(`voice-catalog/voice?key=${encodeURIComponent(key)}`) });
export const profileQuery = id => ({ queryKey: ['character', id],
  queryFn: () => api(`characters/${encodeURIComponent(id)}/profile`), staleTime: 0 });
export const voiceTemplatesQuery = { queryKey: ['templates', 'voice', false],
  queryFn: () => api('templates?kind=voice').then(r => r.templates).catch(() => []) };
export const coverageQuery = { queryKey: ['knowledge', 'coverage'],
  queryFn: () => api('knowledge/coverage').catch(() => ({ locales: [] })), staleTime: 0 };

// After a voice or a character changes, the list, the voice and its character follow.
export function invalidateVoices() {
  for (const key of [['voice-catalog'], ['characters'], ['voice'], ['character']])
    queryClient.invalidateQueries({ queryKey: key });
}
