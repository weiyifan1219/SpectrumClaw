import { useEffect, useState } from "react";

/**
 * useState that transparently persists to localStorage, so a page's
 * query results / run records survive unmounting when the user navigates
 * to another page and back. Records only reset on explicit user action
 * (clear / new query) or when localStorage is cleared.
 *
 * Mirrors the pattern ConsolePage already uses for its chat history.
 *
 * @param {string} key      unique localStorage key (namespace per page+field)
 * @param {*}      fallback  default value when nothing is stored yet
 */
export function usePersistentState(key, fallback) {
  const [value, setValue] = useState(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw != null) return JSON.parse(raw);
    } catch {
      /* corrupt or unavailable storage — fall back */
    }
    return fallback;
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* quota or unavailable — non-fatal, just skip persisting */
    }
  }, [key, value]);

  return [value, setValue];
}
