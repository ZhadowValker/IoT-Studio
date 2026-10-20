// Agent settings. The API key is the user's own: it stays in this browser
// (sessionStorage by default; localStorage only if "remember" is ticked) and
// is sent to the backend proxy per request. Every storage call is wrapped
// because storage can throw (private windows, blocked site data).

import { getProvider } from './providers';

export interface AgentSettings {
  providerId: string;
  model: string;
  baseUrl: string;
  apiKey: string;
  remember: boolean;
  /** Auto-apply with undo is the decided default; kept explicit for the UI. */
  autonomy: 'auto';
}

const META_KEY = 'iot-studio.agent.settings';
const KEY_KEY = 'iot-studio.agent.key';

export function defaultSettings(): AgentSettings {
  const p = getProvider('anthropic');
  return {
    providerId: p.id,
    model: p.models[0] ?? '',
    baseUrl: p.baseUrl,
    apiKey: '',
    remember: false,
    autonomy: 'auto',
  };
}

function read(store: Storage | undefined, key: string): string | null {
  try {
    return store ? store.getItem(key) : null;
  } catch {
    return null;
  }
}

function write(store: Storage | undefined, key: string, value: string | null): void {
  try {
    if (!store) return;
    if (value === null) store.removeItem(key);
    else store.setItem(key, value);
  } catch {
    /* storage unavailable: settings simply do not persist */
  }
}

const local = (): Storage | undefined => {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
};
const session = (): Storage | undefined => {
  try {
    return window.sessionStorage;
  } catch {
    return undefined;
  }
};

export function loadSettings(): AgentSettings {
  const base = defaultSettings();
  try {
    const raw = read(local(), META_KEY);
    if (raw) {
      const meta = JSON.parse(raw) as Partial<AgentSettings>;
      if (meta.providerId) base.providerId = getProvider(meta.providerId).id;
      if (typeof meta.model === 'string') base.model = meta.model;
      if (typeof meta.baseUrl === 'string') base.baseUrl = meta.baseUrl;
      base.remember = meta.remember === true;
    }
  } catch {
    /* ignore corrupt settings */
  }
  base.apiKey =
    read(session(), KEY_KEY) ?? (base.remember ? read(local(), KEY_KEY) : null) ?? '';
  return base;
}

export function saveSettings(s: AgentSettings): void {
  // Never persist the key inside the metadata blob.
  write(
    local(),
    META_KEY,
    JSON.stringify({
      providerId: s.providerId,
      model: s.model,
      baseUrl: s.baseUrl,
      remember: s.remember,
    }),
  );
  write(session(), KEY_KEY, s.apiKey || null);
  write(local(), KEY_KEY, s.remember && s.apiKey ? s.apiKey : null);
}

export function clearKey(): void {
  write(session(), KEY_KEY, null);
  write(local(), KEY_KEY, null);
}
