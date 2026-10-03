import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseTitlePath, resolveTitleTab, titlePath } from '../../ui/src/lib/title-routing.js';

test('title routes round-trip encoded identities and episode tabs', () => {
  assert.deepEqual(parseTitlePath(titlePath('t-A/B & C', 42, 'jobs')), {
    titleKey: 't-A/B & C', episodeId: 42, titleTab: 'jobs', invalid: false,
  });
  assert.equal(parseTitlePath('/title/tmdb-42/meta').titleTab, 'meta');
  assert.equal(parseTitlePath('/title/tvdb-12/episode/3').titleTab, null);
});

test('malformed episode routes cannot silently select a different workspace', () => {
  for (const path of ['/title', '/title/%ZZ', '/title/a/episode', '/title/a/episode/0',
    '/title/a/episode/-1', '/title/a/episode/1x', '/title/a/episode/9007199254740992',
    '/title/a/episode/1/voices/extra']) assert.equal(parseTitlePath(path).invalid, true, path);
});

test('defaults and incompatible tabs resolve according to media type', () => {
  const show = { media_type: 'show' }, movie = { media_type: 'movie' };
  const episode = { media_type: 'episode', episode_id: 3 };
  assert.equal(resolveTitleTab(show), 'episodes');
  assert.equal(resolveTitleTab(movie), 'plan');
  assert.equal(resolveTitleTab(episode), 'analysis');
  assert.equal(resolveTitleTab(episode, 'voices'), 'voices');
  assert.equal(resolveTitleTab(movie, 'analysis'), 'plan');
  assert.equal(resolveTitleTab(show, 'plan'), 'plan');
  assert.equal(resolveTitleTab(movie, 'episodes'), 'plan');
  assert.equal(resolveTitleTab(episode, 'episodes'), 'analysis');
  assert.equal(resolveTitleTab(episode, 'jobs'), 'jobs');
});

test('research is a tab of shows and films, not of one episode', () => {
  assert.equal(resolveTitleTab({ media_type: 'show' }, 'research'), 'research');
  assert.equal(resolveTitleTab({ media_type: 'movie' }, 'research'), 'research');
  assert.equal(resolveTitleTab({ media_type: 'episode', episode_id: 3 }, 'research'), 'analysis');
});
