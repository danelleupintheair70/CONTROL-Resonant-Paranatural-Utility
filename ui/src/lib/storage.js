// localStorage that never throws: private windows and blocked storage fall
// back to the default.
export function safeGet(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } }
export function safeSet(k, v) { try { localStorage.setItem(k, v); } catch { /* not persisted */ } }
