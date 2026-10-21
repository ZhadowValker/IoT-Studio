import { useCallback, useEffect, useRef, useState } from 'react';
import { PROVIDERS, getProvider } from './providers';
import { clearKey, loadSettings, saveSettings, type AgentSettings } from './settings';
import { setAgentOpen, useAgentOpen } from './agentUi';
import { callLlm, fetchModels, type ChatMessage } from './llmClient';
import { runTurn, type AgentEvent } from './loop';
import { restoreCheckpoint, takeCheckpoint, type Checkpoint } from './tools';

// IoT-Studio agent panel (M0): provider/key settings (opened from the toolbar
// launcher, see AgentLauncher.tsx) and the shell
// the chat loop plugs into in M2. Self-contained: it uses only design tokens.

const accent = 'var(--color-accent-fg, #A70CFF)';
const border = '1px solid var(--color-border-default, rgba(255,255,255,0.09))';

const styles = {
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
  chat: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
  feed: { flex: 1, overflowY: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 8 },
  user: {
    alignSelf: 'flex-end',
    maxWidth: '88%',
    padding: '7px 10px',
    borderRadius: 10,
    background: 'linear-gradient(135deg, #A70CFF 0%, #5a0a8c 100%)',
    color: '#fff',
    whiteSpace: 'pre-wrap',
  },
  bot: {
    alignSelf: 'flex-start',
    maxWidth: '92%',
    padding: '7px 10px',
    borderRadius: 10,
    border,
    background: 'var(--color-bg-input, #151518)',
    whiteSpace: 'pre-wrap',
    lineHeight: 1.45,
  },
  step: {
    alignSelf: 'stretch',
    padding: '4px 8px',
    borderRadius: 6,
    border,
    fontSize: 12,
    color: 'var(--color-fg-muted, #999)',
  },
  err: {
    alignSelf: 'stretch',
    padding: '7px 10px',
    borderRadius: 8,
    border: '1px solid #ff6b6b',
    color: '#ff9b9b',
    fontSize: 12,
  },
  composer: { borderTop: border, padding: 10, display: 'flex', flexDirection: 'column', gap: 8 },
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

type ChatItem =
  | { id: number; kind: 'user' | 'bot' | 'err' | 'note'; text: string }
  | { id: number; kind: 'step'; name: string; args: string; writes: boolean; result: string; ok: boolean };

type DistributiveOmit<T, K extends keyof never> = T extends unknown ? Omit<T, K> : never;

export function AgentPanel() {
  const open = useAgentOpen();
  const [settings, setSettings] = useState<AgentSettings>(() => loadSettings());
  const [saved, setSaved] = useState(false);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [view, setView] = useState<'chat' | 'settings'>(() => {
    const st = loadSettings();
    return getProvider(st.providerId).needsKey && !st.apiKey ? 'settings' : 'chat';
  });
  const [items, setItems] = useState<ChatItem[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [usage, setUsage] = useState<{ input: number; output: number; steps: number } | null>(null);
  const [testMsg, setTestMsg] = useState<string | null>(null);
  const [fetched, setFetched] = useState<string[]>([]);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const history = useRef<ChatMessage[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const feedRef = useRef<HTMLDivElement | null>(null);
  const idRef = useRef(0);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight });
  }, [items, busy]);

  const push = useCallback((item: DistributiveOmit<ChatItem, 'id'>) => {
    idRef.current += 1;
    setItems((cur) => [...cur, { ...item, id: idRef.current } as ChatItem]);
  }, []);

  const onEvent = useCallback(
    (e: AgentEvent) => {
      if (e.type === 'assistant') push({ kind: 'bot', text: e.text });
      else if (e.type === 'error') push({ kind: 'err', text: e.text });
      else if (e.type === 'usage') setUsage({ input: e.input, output: e.output, steps: e.steps });
      else if (e.type === 'tool')
        push({ kind: 'step', name: e.name, args: e.args, writes: e.writes, result: e.result, ok: e.ok });
    },
    [push],
  );

  const send = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft('');
    push({ kind: 'user', text });
    setBusy(true);
    setCheckpoints((c) => [...c, takeCheckpoint()]);
    const ctl = new AbortController();
    abortRef.current = ctl;
    try {
      await runTurn({ settings, history: history.current, userText: text, onEvent, signal: ctl.signal });
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  };

  const undoTurn = () => {
    const cp = checkpoints[checkpoints.length - 1];
    if (!cp || busy) return;
    restoreCheckpoint(cp);
    setCheckpoints((c) => c.slice(0, -1));
    history.current.push({
      role: 'user',
      content: '[The user undid your last turn. The project files were restored to how they were before it.]',
    });
    push({ kind: 'note', text: 'Last turn undone: project files restored.' });
  };

  const newChat = () => {
    if (busy) return;
    history.current = [];
    setItems([]);
    setUsage(null);
    setCheckpoints([]);
  };

  const loadModels = async () => {
    setTestMsg('Loading models…');
    try {
      const ids = await fetchModels(settings);
      setFetched(ids);
      setTestMsg(`${ids.length} chat models found. Start typing in Model to pick one.`);
    } catch (e) {
      setTestMsg(`Failed: ${(e as Error).message}`);
    }
  };

  const testConnection = async () => {
    setTestMsg('Testing…');
    try {
      const r = await callLlm(settings, 'Reply with the single word OK.', [{ role: 'user', content: 'ping' }], []);
      setTestMsg(`Connected. Model replied: "${r.content.trim().slice(0, 40) || '(empty)'}"`);
    } catch (e) {
      setTestMsg(`Failed: ${(e as Error).message}`);
    }
  };

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
      {open && (
        <aside style={styles.panel} aria-label="IoT-Studio AI agent">
          <div style={styles.head}>
            <span>AI agent</span>
            <span style={{ display: 'flex', gap: 6 }}>
              <button
                type="button"
                style={{ ...styles.btn, padding: '3px 8px' }}
                onClick={() => setView((v) => (v === 'chat' ? 'settings' : 'chat'))}
                title={view === 'chat' ? 'Provider, model and key' : 'Back to the chat'}
              >
                {view === 'chat' ? 'Settings' : 'Chat'}
              </button>
              <button
                type="button"
                style={{ ...styles.btn, padding: '3px 8px' }}
                onClick={() => setAgentOpen(false)}
              >
                ✕
              </button>
            </span>
          </div>

          {view === 'chat' ? (
            <div style={styles.chat}>
              <div style={styles.feed} ref={feedRef}>
                {items.length === 0 && (
                  <div style={styles.note}>
                    Tell me what to build or fix, for example: “Blink the LED on GPIO 2 and print the
                    state to serial”. I edit the files, compile, run and check the result. Every turn
                    can be undone.
                  </div>
                )}
                {items.map((it) =>
                  it.kind === 'user' ? (
                    <div key={it.id} style={styles.user}>{it.text}</div>
                  ) : it.kind === 'bot' ? (
                    <div key={it.id} style={styles.bot}>{it.text}</div>
                  ) : it.kind === 'err' ? (
                    <div key={it.id} style={styles.err}>{it.text}</div>
                  ) : it.kind === 'note' ? (
                    <div key={it.id} style={styles.hint}>{it.text}</div>
                  ) : it.kind === 'step' ? (
                    <details key={it.id} style={styles.step}>
                      <summary style={{ cursor: 'pointer' }}>
                        {it.ok ? (it.writes ? '✎ ' : '• ') : '⚠ '}
                        {it.name}
                        {it.args ? ` (${it.args})` : ''}
                      </summary>
                      <pre style={{ whiteSpace: 'pre-wrap', margin: '6px 0 0', maxHeight: 180, overflow: 'auto' }}>
                        {it.result}
                      </pre>
                    </details>
                  ) : null,
                )}
                {busy && <div style={styles.hint}>Working…</div>}
              </div>
              <div style={styles.composer}>
                <textarea
                  style={{ ...styles.input, resize: 'none', height: 64 }}
                  value={draft}
                  placeholder="Ask the agent…  (Enter to send, Shift+Enter for a new line)"
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                />
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  {busy ? (
                    <button type="button" style={styles.btn} onClick={() => abortRef.current?.abort()}>
                      Stop
                    </button>
                  ) : (
                    <button type="button" style={styles.btnPrimary} onClick={() => void send()}>
                      Send
                    </button>
                  )}
                  <button
                    type="button"
                    style={{ ...styles.btn, opacity: checkpoints.length && !busy ? 1 : 0.4 }}
                    disabled={!checkpoints.length || busy}
                    onClick={undoTurn}
                    title="Restore the project files to before the last agent turn"
                  >
                    Undo turn
                  </button>
                  <button type="button" style={{ ...styles.btn, borderColor: 'transparent' }} onClick={newChat}>
                    New chat
                  </button>
                </div>
                {usage && (
                  <div style={styles.hint}>
                    {settings.model} · steps {usage.steps} · tokens in {usage.input} / out {usage.output}
                  </div>
                )}
              </div>
            </div>
          ) : (
          <div style={styles.body}>
            <div style={styles.note}>
              Pick a provider and enter your own API key. The key stays in this browser and is sent only with your requests; the server never stores it. </div>

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
                {[...new Set([...provider.models, ...fetched])].map((m) => (
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
              <button type="button" style={styles.btn} onClick={() => void testConnection()}>
                Test
              </button>
              <button type="button" style={styles.btn} onClick={() => void loadModels()}>
                Models
              </button>
              {saved && <span style={{ alignSelf: 'center', color: accent }}>Saved</span>}
            </div>
            {testMsg && <div style={styles.hint}>{testMsg}</div>}

            <div style={styles.hint}>
              Mode: auto-apply with undo. The agent edits the project directly; every turn gets a
              checkpoint you can revert.
            </div>
          </div>
          )}
        </aside>
      )}
    </>
  );
}

export default AgentPanel;
