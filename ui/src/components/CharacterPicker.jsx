import { useEffect, useId, useRef, useState } from 'react';
import { pickerOptions } from '../lib/characters.js';

// Picking who a voice is, from the show's cast instead of typing it again.
//
// A free-text name is one typo away from a second "Mina" ("mina", "Minna"),
// and every copy splits the show's share and its voice tag in two. So a name
// is chosen like a select2 field: typing searches the cast (case and accents
// ignored), the voices this one sounds closest to come first, a near miss
// offers the existing spelling, and a new character is one explicit option,
// never what happens on blur.
//
//   <CharacterPicker label value placeholder cast suggestions sharedWith onPick autoFocus />
//   label:       the input's accessible name
//   value:       the current name ('' for none); follows the prop when it changes
//   cast:        [{ name, lines, episodes }]   everyone named in the show
//   suggestions: [{ name, similarity }]        closest named voices
//   sharedWith:  name -> other groups in this episode already using it
//   onPick:      (name) => void, '' when the name is cleared
//   autoFocus:   focus (and open) once mounted

const HEADING = { closest: 'Sounds closest', cast: 'In this show', 'did-you-mean': 'Did you mean', new: '', clear: '' };

function Describe({ option: o, sharedWith }) {
  if (o.kind === 'new') return <span className="cp-new">New character “{o.name}”</span>;
  if (o.kind === 'clear') return <span className="cp-muted">Clear the name</span>;
  const bits = [];
  if (o.kind === 'did-you-mean') bits.push('did you mean?');
  if (o.similarity) bits.push(`sounds ${Math.round(o.similarity * 100)}% alike`);
  if (o.lines) bits.push(`${o.lines} line${o.lines === 1 ? '' : 's'}${o.episodes > 1 ? ` · ${o.episodes} episodes` : ''}`);
  if (sharedWith[o.name]?.length) bits.push(`joins ${sharedWith[o.name].join(', ')}`);
  return <><span className="cp-name">{o.name}</span>{bits.length > 0 && <span className="cp-meta">{bits.join(' · ')}</span>}</>;
}

export function CharacterPicker({ label, value = '', placeholder = '', cast = [], suggestions = [], sharedWith = {},
  onPick, autoFocus = false }) {
  const id = useId();
  const rootRef = useRef(null);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const [picked, setPicked] = useState(value);
  const [text, setText] = useState(value);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  // A new name from outside (a save elsewhere) replaces what is shown.
  const [seen, setSeen] = useState(value);
  if (seen !== value) {
    setSeen(value);
    setPicked(value);
    if (!open) setText(value);
  }

  const query = text === picked ? '' : text;
  const options = open ? pickerOptions({ query, value: picked, cast, suggestions }) : [];

  useEffect(() => {
    if (!autoFocus) return undefined;
    const timer = setTimeout(() => inputRef.current?.focus(), 0);
    return () => clearTimeout(timer);
  }, [autoFocus]);
  useEffect(() => {
    if (open) listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView?.({ block: 'nearest' });
  }, [open, active, text]);

  function show() { if (!open) { setOpen(true); setActive(0); } }
  function hide() { setOpen(false); setText(picked); }       // nothing typed is kept unless it was picked
  function choose(option) {
    if (!option) return;
    setPicked(option.name);
    setText(option.name);
    setOpen(false);
    onPick?.(option.name);
  }
  function onKeyDown(e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); show(); setActive(Math.min(options.length - 1, active + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(Math.max(0, active - 1)); }
    else if (e.key === 'Enter') { e.preventDefault(); if (open) choose(options[active]); else show(); }
    else if (e.key === 'Escape' && open) { e.preventDefault(); e.stopPropagation(); hide(); }
    else if (e.key === 'Tab') hide();
  }

  let last = '';
  return (
    <div className="cp" ref={rootRef}>
      <input ref={inputRef} className="input cp-input" role="combobox" aria-autocomplete="list" aria-expanded={open ? 'true' : 'false'}
        aria-controls={id} aria-label={label} placeholder={placeholder} value={text} autoComplete="off" spellCheck="false" maxLength={80}
        aria-activedescendant={open && options.length ? `${id}-${active}` : ''}
        onFocus={e => { e.target.select(); show(); }} onClick={show}
        onChange={e => { setText(e.target.value); setOpen(true); setActive(0); }}
        onKeyDown={onKeyDown}
        onBlur={() => setTimeout(() => { if (!rootRef.current?.contains(document.activeElement)) hide(); }, 0)} />
      <ul className="cp-list" id={id} role="listbox" hidden={!open} ref={listRef}
        onMouseDown={e => {
          const item = e.target.closest('[data-i]');
          if (!item) return;
          e.preventDefault();                 // keep focus so blur does not close first
          choose(options[Number(item.dataset.i)]);
        }}>
        {options.length ? options.flatMap((o, i) => {
          const rows = [];
          if (HEADING[o.kind] && o.kind !== last) rows.push(<li key={`h-${i}`} className="cp-head" role="presentation">{HEADING[o.kind]}</li>);
          last = o.kind;
          rows.push(<li key={i} role="option" id={`${id}-${i}`} className={`cp-option cp-${o.kind}`} data-i={i}
            aria-selected={i === active ? 'true' : 'false'}><Describe option={o} sharedWith={sharedWith} /></li>);
          return rows;
        }) : <li className="cp-head" role="presentation">Nobody named yet: type a name</li>}
      </ul>
    </div>
  );
}
