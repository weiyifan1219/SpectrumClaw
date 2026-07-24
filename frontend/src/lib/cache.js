/**
 * Small localStorage cache for read-mostly page data.
 * Cached data is intentionally allowed to be stale: it keeps the UI usable
 * while a background request refreshes the value.
 */
export function readCachedValue(key, fallback = null) {
  try {
    const raw = localStorage.getItem(key);
    if (raw == null) return fallback;
    const parsed = JSON.parse(raw);
    return parsed && Object.prototype.hasOwnProperty.call(parsed, "value")
      ? parsed.value
      : parsed;
  } catch {
    return fallback;
  }
}

export function writeCachedValue(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify({ value, updatedAt: Date.now() }));
  } catch {
    /* Storage may be unavailable or full; network data remains authoritative. */
  }
}
