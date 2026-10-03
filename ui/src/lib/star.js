import { safeGet } from './storage.js';

// "Star us on GitHub": a quiet star next to the logo, plus a one-time
// sidebar nudge. Starring (or a click through) hides the nudge for good;
// "Not now" snoozes it so it doesn't nag on every visit.
export const REPO_URL = 'https://github.com/jhd3197/Doblarr';
export const STARRED_KEY = 'doblarr.starNudge.starred';
export const SNOOZE_KEY = 'doblarr.starNudge.snoozedUntil';
export const SNOOZE_MS = 14 * 24 * 60 * 60 * 1000;

export function nudgeDue(now = Date.now()) {
  if (safeGet(STARRED_KEY, '') === '1') return false;
  const until = Number(safeGet(SNOOZE_KEY, '0')) || 0;
  return now >= until;
}
