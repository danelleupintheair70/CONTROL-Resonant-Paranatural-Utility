// What the scene panel's controls are asking for, read from its form fields.
// The panel's inputs are uncontrolled (they are remounted whenever the line or
// its scene changes), so a change is collected from the DOM on each `input`
// event, exactly as the review editor collects its own fields.
//
// `state` lives for one review: { pendingTiming, pendingEvents, pendingSpace }
// keyed by line and by event, so moving to another line does not quietly drop
// a decision a reviewer already made.

export function createSceneState() {
  return { pendingTiming: new Map(), pendingEvents: new Map(), pendingSpace: new Map(), versions: [], context: 2 };
}

export function resetSceneState(state) {
  state.pendingTiming.clear(); state.pendingEvents.clear(); state.pendingSpace.clear();
  state.versions = []; state.context = 2;
}

// What the timing controls are asking for, or nothing when this line has no
// phrase plan on screen. Returning the anchors and pauses only when they
// differ from what the run already decided keeps an untouched line out of the
// re-render entirely.
function collectTiming(container, scene, row, state) {
  const plan = scene?.phrasing;
  if (!plan || plan.mode !== 'phrase') return {};
  const before = scene?.timing_edit || {};
  const patch = {};
  const anchors = [...container.querySelectorAll('.scene-phrases li')]
    .map(node => ({ phrase: node.dataset.phrase, at: node.querySelector('.scene-anchor')?.value }))
    .filter(a => a.at !== '' && a.at != null)
    .map(a => ({ phrase: a.phrase, edge: 'start', at: Number(a.at) }))
    .filter(a => Number.isFinite(a.at));
  const wasAnchors = (before.anchors || []).map(a => `${a.phrase}:${a.at}`).sort().join('|');
  if (anchors.map(a => `${a.phrase}:${a.at}`).sort().join('|') !== wasAnchors) patch.anchors = anchors;
  const pauses = [...container.querySelectorAll('.scene-protect')].map(node => ({
    pause: node.dataset.pause, protected: node.checked, kind: node.checked ? 'pause' : 'padding',
  }));
  const planned = new Map((plan.pauses || []).map(p => [p.pause_id, p.protected]));
  const overrides = new Map(Object.entries(before.pauses || {}));
  const changed = pauses.filter(p => {
    const current = overrides.has(p.pause) ? overrides.get(p.pause).protected : planned.get(p.pause);
    return p.protected !== current;
  });
  if (changed.length) patch.pauses = pauses.filter(p => p.protected !== planned.get(p.pause));
  const bypass = container.querySelector('#sceneBypass');
  if (bypass && bypass.checked !== !!before.bypass) patch.bypass_timing = bypass.checked;
  const overlap = container.querySelector('#sceneOverlap');
  if (overlap) {
    const was = before.overlap != null ? !!before.overlap
      : (scene?.collisions || []).some(r => r.accepted && !r.accepted.stale);
    if (overlap.checked !== was) patch.overlap = overlap.checked;
  }
  if (Object.keys(patch).length) {
    state.pendingTiming.set(row.index, { ...(state.pendingTiming.get(row.index) || {}), ...patch });
  } else state.pendingTiming.delete(row.index);
  return patch;
}

// What the space controls are asking for, or nothing when this line's space
// is already what the run decided. A bypass is kept as a bypass rather than
// rewritten as "dry": it says *this line* is to be left alone, and it has to
// survive a change to the scene rule above it.
function collectSpace(container, scene, row, state) {
  const select = container.querySelector('#sceneTreatment');
  if (!select || !scene?.treatment) return {};
  const before = scene?.treatment_edit || {};
  const bypass = container.querySelector('#sceneNoSpace')?.checked || false;
  const preset = select.value;
  const intensity = Number(container.querySelector('#sceneIntensity')?.value);
  if (bypass) {
    if (before.bypass) { state.pendingSpace.delete(row.index); return {}; }
    state.pendingSpace.set(row.index, { bypass: true });
    return { treatment: { bypass: true } };
  }
  const wasPreset = before.bypass ? 'dry' : (before.preset || scene.treatment.preset);
  const wasIntensity = before.intensity ?? scene.treatment.intensity;
  const movedPreset = preset !== wasPreset;
  const movedIntensity = Number.isFinite(intensity) && Math.abs(intensity - Number(wasIntensity ?? 1)) > 1e-6;
  if (!movedPreset && !movedIntensity && !before.bypass) {
    state.pendingSpace.delete(row.index);
    return {};
  }
  const patch = { preset };
  if (Number.isFinite(intensity)) patch.intensity = intensity;
  state.pendingSpace.set(row.index, patch);
  return { treatment: patch };
}

// Coverage decisions belong to the run, not to the line on screen: an event
// very often has no surviving cue at all. They are collected into their own
// map and submitted alongside the line edits.
function collectEvents(container, scene, state) {
  const known = new Map((scene?.events || []).map(e => [e.event_id, e]));
  container.querySelectorAll('.scene-event').forEach(node => {
    const id = node.dataset.event;
    const before = known.get(id);
    if (!before) return;
    const decision = node.querySelector('.scene-decision').value;
    const asset = node.querySelector('.scene-asset').value.trim();
    if (decision === before.decision && asset === (before.asset || '')) {
      state.pendingEvents.delete(id);
      return;
    }
    state.pendingEvents.set(id, { event: id, decision, ...(asset ? { asset } : {}) });
  });
  return [...state.pendingEvents.values()];
}

// The scene panel's part of a line edit: performance, take, timing and space.
export function collectScene({ container, scene, row, state }) {
  if (!container) return {};
  const el = id => container.querySelector(id);
  collectEvents(container, scene, state);
  if (!el('#sceneMode')) return {};
  const patch = {};
  const mode = el('#sceneMode').value;
  const traits = el('#sceneTraits').value.split(',').map(t => t.trim()).filter(Boolean);
  const direction = el('#sceneDirection').value;
  const gain = el('#sceneGain').value;
  const candidates = Number(el('#sceneCandidates').value) || 0;
  const chosen = container.querySelector('input[name="sceneTake"]:checked');
  const cue = row?.cue || {};
  if (mode !== (cue.intent?.mode || 'unknown')) patch.mode = mode;
  if (traits.join(',') !== (cue.intent?.traits || []).join(',')) patch.traits = traits;
  if (direction !== (cue.intent?.direction || '')) patch.direction = direction;
  if (gain !== '') patch.gain_db = Number(gain);
  if (candidates) patch.candidates = candidates;
  if (chosen && chosen.value !== scene?.selection?.take_id) patch.take = chosen.value;
  const line = row || { index: -1 };
  return { ...patch, ...collectTiming(container, scene, line, state), ...collectSpace(container, scene, line, state) };
}
