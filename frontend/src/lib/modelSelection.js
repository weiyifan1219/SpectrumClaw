export const MODEL_KEY = "sc_model";
export const MODEL_CHANGED_EVENT = "spectrumclaw:model-changed";

export function loadModelSelection() {
  try {
    return localStorage.getItem(MODEL_KEY);
  } catch {
    return null;
  }
}

export function saveModelSelection(id) {
  try {
    localStorage.setItem(MODEL_KEY, id);
  } catch {
    /* ignore storage failures */
  }
  try {
    window.dispatchEvent(new CustomEvent(MODEL_CHANGED_EVENT, { detail: { id } }));
  } catch {
    /* ignore non-browser environments */
  }
}

export function subscribeModelSelection(handler) {
  const onLocalChange = (event) => handler(event.detail?.id ?? loadModelSelection());
  const onStorageChange = (event) => {
    if (event.key === MODEL_KEY) handler(event.newValue);
  };
  window.addEventListener(MODEL_CHANGED_EVENT, onLocalChange);
  window.addEventListener("storage", onStorageChange);
  return () => {
    window.removeEventListener(MODEL_CHANGED_EVENT, onLocalChange);
    window.removeEventListener("storage", onStorageChange);
  };
}
