import { test } from 'node:test';
import assert from 'node:assert/strict';
import { locate, reelLayout } from '../../ui/src/lib/media.js';
import { distance, fold, pickerOptions } from '../../ui/src/lib/characters.js';

test('a reel of clips has its own timeline and any moment maps to a clip', () => {
  const layout = reelLayout([{ start: 10, end: 12 }, { start: 40, end: 43 }, { start: 90, end: 91 }]);
  assert.deepEqual(layout.offsets, [0, 2, 5]);
  assert.equal(layout.total, 6);
  assert.deepEqual(locate(layout, 0), { index: 0, offset: 0 });
  assert.deepEqual(locate(layout, 3.5), { index: 1, offset: 1.5 });
  assert.deepEqual(locate(layout, 99), { index: 2, offset: 1 });
  assert.deepEqual(locate(layout, -4), { index: 0, offset: 0 });
});

const CAST = [{ name: 'Kaito', lines: 120, episodes: 3 }, { name: 'Mina', lines: 40, episodes: 3 },
  { name: 'Sora', lines: 18, episodes: 1 }];

test('an empty picker leads with the voices it sounds like, then the cast', () => {
  const options = pickerOptions({ cast: CAST, suggestions: [{ name: 'Mina', similarity: 0.6 }] });
  assert.deepEqual(options.map(o => [o.kind, o.name]),
    [['closest', 'Mina'], ['cast', 'Kaito'], ['cast', 'Sora']]);
});

test('typing an existing name in any case never creates a second character', () => {
  const options = pickerOptions({ query: 'kaITO', cast: CAST });
  assert.deepEqual(options.map(o => [o.kind, o.name]), [['cast', 'Kaito']]);
});

test('a near miss offers the existing spelling before a new character', () => {
  const options = pickerOptions({ query: 'Kaitto', cast: CAST, value: 'Sora' });
  assert.deepEqual(options.map(o => o.kind), ['did-you-mean', 'new', 'clear']);
  assert.equal(options[0].name, 'Kaito');
  assert.equal(options[1].name, 'Kaitto');
});

test('search ignores accents and puts names that start with the query first', () => {
  const cast = [{ name: 'Hoshi', lines: 5 }, { name: 'Shiori', lines: 50 }, { name: 'Shion', lines: 1 }];
  assert.deepEqual(pickerOptions({ query: 'shi', cast }).filter(o => o.kind === 'cast').map(o => o.name),
    ['Shiori', 'Shion', 'Hoshi']);
  assert.equal(fold('Ryò '), 'ryo');
  assert.equal(distance('kaitto', 'kaito'), 1);
});
