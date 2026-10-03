import { test } from 'node:test';
import assert from 'node:assert/strict';
import { citedParts, languageColumns, seriesIdOf, voicesIn } from '../../ui/src/lib/research.js';

test('a title maps to the series its research is kept under', () => {
  assert.equal(seriesIdOf({ media_type: 'show', tvdb_id: 4242 }), 'show:tvdb:4242');
  assert.equal(seriesIdOf({ media_type: 'movie', tmdb_id: 77, tvdb_id: 5 }), 'movie:tmdb:77');
  assert.equal(seriesIdOf({ episode_id: 3, parent: { tvdb_id: 4242 } }), 'show:tvdb:4242');
  assert.equal(seriesIdOf({ media_type: 'movie' }), '');
});

test('voice columns put the original, then the dub language, then the rest', () => {
  const rows = [{ voice_actors: [{ name: 'Dana Wells', language: 'English' },
    { name: 'Lucia Prado', language: 'Spanish' }, { name: 'Aki Sora', language: 'Japanese' },
    { name: '空亜希', language: '' }] }];
  assert.deepEqual(languageColumns(rows, 'es-MX'), ['Japanese', 'Spanish', 'English', '']);
  assert.deepEqual(voicesIn(rows[0], 'Spanish').map(v => v.name), ['Lucia Prado']);
});

test('only citations of opened pages become links', () => {
  const blocks = citedParts('## Names\n- The guild is **la Cofradía** [1][3].\nPlain line.',
    [{ n: 1, url: 'https://wiki.example/guild' }, { n: null, url: 'https://unopened' }]);
  assert.equal(blocks[0].kind, 'heading');
  assert.equal(blocks[1].kind, 'item');
  assert.deepEqual(blocks[1].parts, [{ text: 'The guild is la Cofradía ' },
    { n: 1, url: 'https://wiki.example/guild' }, { text: '[3]' }, { text: '.' }]);
  assert.equal(blocks[2].parts[0].text, 'Plain line.');
});
