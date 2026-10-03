import { stamp } from './controller.js';

const QUICK = ['Wrong word', 'Rushed', 'Dragging', 'Too loud', 'Too quiet', 'Flat delivery',
  'Odd noise', 'Not in the original'];
const SEVERITIES = ['minor', 'noticeable', 'major'];

function NoteRow({ ctrl, note, fresh }) {
  // Text fields save when they are left, like the vanilla `change` event.
  const commit = field => e => { if (e.target.value !== (note[field] ?? '')) ctrl.patchNote(note, { [field]: e.target.value }); };
  // The Dialogue view opens the editor on the session's line.
  function openInEditor() {
    ctrl.remember({ line: note.line });
    if (ctrl.state.view === 'dialogue') ctrl.review?.focusLine(note.line);
    else ctrl.show('dialogue');
  }
  return (
    <div className="studio-note" data-id={note.id} data-fresh={String(note.id === fresh)}>
      <div className="studio-note-top">
        <button type="button" className="btn btn-ghost m" data-hear onClick={() => ctrl.hearNote(note)}>{stamp(note.at)}</button>
        <span className="tag tag-neutral">{note.source || 'no source'}</span>
        {note.line != null && <span className="hint">line {note.line + 1}</span>}
        {note.stale && <span className="review-marker">made on older audio</span>}
        <span className={`tag ${note.resolution === 'resolved' ? 'tag-neutral' : 'tag-accent'}`}>{(note.resolution || 'open').replace('_', ' ')}</span>
      </div>
      <div className="studio-note-fields">
        <input className="input" data-field="category" defaultValue={note.category} placeholder="What" aria-label="What" onBlur={commit('category')} />
        <select className="input" data-field="severity" aria-label="How bad" value={note.severity}
          onChange={e => ctrl.patchNote(note, { severity: e.target.value })}>
          {SEVERITIES.map(s => <option key={s}>{s}</option>)}
        </select>
        <input className="input" data-field="note" defaultValue={note.note} placeholder="Describe it" aria-label="Note" onBlur={commit('note')} />
      </div>
      <div className="studio-note-actions">
        {note.line != null && <button type="button" className="btn btn-ghost" data-edit onClick={openInEditor}>Open in editor</button>}
        <button type="button" className="btn btn-ghost" data-original onClick={() => ctrl.hearOriginal(note)}>Hear original here</button>
        {note.resolution !== 'resolved'
          ? <button type="button" className="btn btn-ghost" data-resolve onClick={() => ctrl.patchNote(note, { resolution: 'resolved' })}>Resolve</button>
          : <button type="button" className="btn btn-ghost" data-reopen onClick={() => ctrl.patchNote(note, { resolution: 'open' })}>Reopen</button>}
      </div>
    </div>
  );
}

// Notes on this run: quick marks, then each note with its moment, source and state.
export function NotesPanel({ ctrl }) {
  const { session, notes, fresh } = ctrl.state;
  const filter = session.filters?.notes || 'open';
  const shown = notes.filter(n => n.category !== 'verdict')
    .filter(n => filter === 'all' || (n.resolution || 'open') !== 'resolved')
    .sort((a, b) => a.at - b.at);
  return (
    <aside className="panel studio-notes" id="studioNotes" aria-label="Notes on this run">
      <div className="studio-notes-head"><h3>Notes</h3>
        <label className="review-filter">Show <select className="input" id="noteFilter" value={filter}
          onChange={e => ctrl.setNoteFilter(e.target.value)}>
          <option value="open">Open</option><option value="all">All</option></select></label>
      </div>
      <div className="studio-quick">
        {QUICK.map(q => <button key={q} type="button" className="btn btn-ghost" data-quick={q} onClick={() => ctrl.mark(q)}>+ {q}</button>)}
      </div>
      {shown.length
        ? shown.map(n => <NoteRow key={`${n.id}:${n.revision}`} ctrl={ctrl} note={n} fresh={fresh} />)
        : <p className="hint">No notes here yet. Press N while listening to mark a moment.</p>}
    </aside>
  );
}
