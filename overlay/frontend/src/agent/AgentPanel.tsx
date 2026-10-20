import { useCallback, useEffect, useState } from 'react';
import { PROVIDERS, getProvider } from './providers';
import { clearKey, loadSettings, saveSettings, type AgentSettings } from './settings';

// IoT-Studio agent panel (M0): launcher, provider/key settings and the shell
// the chat loop plugs into in M2. Self-contained: it uses only design tokens.

const accent = 'var(--color-accent-fg, #A70CFF)';
const border = '1px solid var(--color-border-default, rgba(255,255,255,0.09))';

const styles = {
  launcher: {
    position: 'fixed',
    right: 16,
    bottom: 16,
    zIndex: 1200,
    padding: '8px 14px',
    borderRadius: 999,
    border: `1px solid ${accent}`,
    background: 'linear-gradient(135deg, #A70CFF 0%, #5a0a8c 100%)',
    color: '#fff',
    fontWeight: 600,
    fontSize: 13,
    cursor: 'pointer',
    boxShadow: '0 4px 18px rgba(167,12,255,0.35)',
  },
  panel: {
    position: 'fixed',
    top: 48,
    right: 0,
    bottom: 0,
    width: 380,
    maxWidth: '100vw',
    zIndex: 1300,
    display: 'flex',
    flexDirection: 'column',
    background: 'var(--color-bg-canvas, #0a0a0c)',
    color: 'var(--color-fg-default, #eee)',
    borderLeft: border,
    fontSize: 13,
  },
  head: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 14px',
    borderBottom: border,
    fontWeight: 600,
  },
  body: { padding: 14, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 12 },
  label: { display: 'flex', flexDirection: 'column', gap: 4, color: 'var(--color-fg-muted, #999)' },
  input: {
    padding: '7px 9px',
    borderRadius: 6,
    border,
    background: 'var(--color-bg-input, #151518)',
    color: 'var(--color-fg-default, #eee)',
    fontSize: 13,
  },
  hint: { color: 'var(--color-fg-muted, #999)', fontSize: 12, lineHeight: 1.4 },
  btn: {
    padding: '7px 12px',
    borderRadius: 6,
    border: `1px solid ${accent}`,
    background: 'transparent',
    color: accent,
    cursor: 'pointer',
    fontWeight: 600,
  },
  btnPrimary: {
    padding: '7px 12px',
    borderRadius: 6,
    border: 'none',
    background: 'linear-gradient(135deg, #A70CFF 0%, #5a0a8c 100%)',
    color: '#fff',
    cursor: 'pointer',
    fontWeight: 600,
  },
  note: {
    padding: 10,
    borderRadius: 8,
    border,
    background: 'rgba(167,12,255,0.08)',
    color: 'var(--color-fg-muted, #999)',
    fontSize: 12,
    lineHeight: 1.5,
  },
} as const satisfies Record<string, React.CSSProperties>;

export function AgentPanel() {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<AgentSettings>(() => loadSettings());
  const [saved, setSaved] = useState(false);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [enabled, setEnabled] = useState(true);

  const provider = getProvider(settings.providerId);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/agent/status')
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (!cancelled && j && j.enabled === false) setEnabled(false);
      })
      .catch(() => {
        /* backend without the agent: keep the panel usable for settings */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const update = useCallback((patch: Partial<AgentSettings>) => {
    setSaved(false);
    setSettings((s) => ({ ...s, ...patch }));
  }, []);

  const onProvider = (id: string) => {
    const p = getProvider(id);
    update({ providerId: id, baseUrl: p.baseUrl, model: p.models[0] ?? '' });
    setUrlError(null);
  };

  const onSave = async () => {
    setUrlError(null);
    if (provider.editableUrl && settings.baseUrl) {
      try {
        const r = await fetch('/api/agent/check-url', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ base_url: settings.baseUrl }),
        });
        const j = await r.json();
        if (j && j.ok === false) {
          setUrlError(String(j.error ?? 'URL not allowed'));
          return;
        }
      } catch {
        /* offline check: saving still works */
      }
    }
    saveSettings(settings);
    setSaved(true);
  };

  if (!enabled) return null;

  return (
    <>
      <button
        type="button"
        style={styles.launcher}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        title="IoT-Studio AI agent"
      >
        {open ? 'Close agent' : 'AI agent'}
      </button>

      {open && (
        <aside style={styles.panel} aria-label="IoT-Studio AI agent">
          <div style={styles.head}>
            <span>AI agent</span>
            <button
              type="button"
              style={{ ...styles.btn, padding: '3px 8px' }}
              onClick={() => setOpen(false)}
            >
              ✕
            </button>
          </div>

          <div style={styles.body}>
            <div style={styles.note}>
              Pick a provider and enter your own API key. The key stays in this browser and is
              sent only with your requests; the server never stores it. Chat and project tools
              arrive in the next milestones.
            </div>

            <label style={styles.label}>
              Provider
              <select
                style={styles.input}
                value={settings.providerId}
                onChange={(e) => onProvider(e.target.value)}
              >
                {PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>

            <label style={styles.label}>
              Model
              <input
                style={styles.input}
                list="iot-agent-models"
                value={settings.model}
                placeholder="model id"
                onChange={(e) => update({ model: e.target.value })}
              />
              <datalist id="iot-agent-models">
                {provider.models.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </label>

            {provider.editableUrl && (
              <label style={styles.label}>
                Base URL
                <input
                  style={styles.input}
                  value={settings.baseUrl}
                  placeholder="https://…/v1"
                  onChange={(e) => update({ baseUrl: e.target.value })}
                />
                {urlError && <span style={{ color: '#ff6b6b' }}>{urlError}</span>}
              </label>
            )}

            {provider.needsKey && (
              <label style={styles.label}>
                API key
                <input
                  style={styles.input}
                  type="password"
                  autoComplete="off"
                  value={settings.apiKey}
                  placeholder="paste your key"
                  onChange={(e) => update({ apiKey: e.target.value })}
                />
              </label>
            )}

            <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input
                type="checkbox"
                checked={settings.remember}
                onChange={(e) => update({ remember: e.target.checked })}
              />
              Remember the key on this device
            </label>

            {provider.hint && <div style={styles.hint}>{provider.hint}</div>}

            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" style={styles.btnPrimary} onClick={onSave}>
                Save
              </button>
              <button
                type="button"
                style={styles.btn}
                onClick={() => {
                  clearKey();
                  update({ apiKey: '', remember: false });
                }}
              >
                Forget key
              </button>
              {saved && <span style={{ alignSelf: 'center', color: accent }}>Saved</span>}
            </div>

            <div style={styles.hint}>
              Mode: auto-apply with undo. The agent edits the project directly; every turn gets a
              checkpoint you can revert.
            </div>
          </div>
        </aside>
      )}
    </>
  );
}

export default AgentPanel;
