// Pure core of the Raspberry Pi shell tool (no app imports, so it can be
// unit-tested with a fake bridge). A command is wrapped between two marker
// lines carrying a random nonce. The markers are printed by printf, so the
// shell's echo of what we typed contains "@@B%s@@", never the expanded marker,
// and only the real output matches.

export interface ShellBridge {
  onSerialData: ((char: string) => void) | null;
  sendSerialText(text: string): void;
  sendSerialBytes(bytes: number[]): void;
  sendAndWaitForPrompt(text: string, timeoutMs?: number): Promise<void>;
}

export interface ShellResult {
  output: string;
  exit_code: number | null;
  timed_out: boolean;
  truncated: boolean;
}

const ANSI = /\x1b\[[0-9;?]*[A-Za-z]|\x1b[=>]/g;
const MAX_OUT = 8000;

export function wrapCommand(cmd: string, nonce: string): string {
  return `printf '@@B%s@@\\n' ${nonce}; ( ${cmd} ) 2>&1; printf '@@E%s:%d@@\\n' ${nonce} $?\n`;
}

export function extract(raw: string, nonce: string): { output: string; code: number } | null {
  const text = raw.replace(ANSI, '').replace(/\r/g, '');
  const b = text.indexOf(`@@B${nonce}@@\n`);
  if (b < 0) return null;
  const rest = text.slice(b + `@@B${nonce}@@\n`.length);
  const m = new RegExp(`@@E${nonce}:(\\d+)@@`).exec(rest);
  if (!m) return null;
  return { output: rest.slice(0, m.index), code: Number(m[1]) };
}

function clip(s: string): { out: string; truncated: boolean } {
  if (s.length <= MAX_OUT) return { out: s, truncated: false };
  return { out: `${s.slice(0, 3000)}\n...[${s.length - 7000} chars cut]...\n${s.slice(-4000)}`, truncated: true };
}

let busy = false;

/** Run one single-line shell command in the guest and return its output. The
 *  foreground program (e.g. the project's script) is interrupted first. */
export async function runShell(
  bridge: ShellBridge,
  cmd: string,
  timeoutMs: number,
  signal?: AbortSignal,
): Promise<ShellResult> {
  if (/[\r\n]/.test(cmd.trim())) throw new Error('One line only. For several lines, write a script with pi_write_file and run it.');
  if (busy) throw new Error('Another pi_run is still in progress.');
  busy = true;
  const nonce = Math.random().toString(36).slice(2, 10);
  let raw = '';
  const prev = bridge.onSerialData;
  bridge.onSerialData = (ch: string) => {
    raw += ch;
    prev?.(ch);
  };
  try {
    bridge.sendSerialBytes([0x03]); // Ctrl-C: free the foreground
    await bridge.sendAndWaitForPrompt('\n', 2500);
    raw = '';
    bridge.sendSerialText(wrapCommand(cmd.trim(), nonce));
    const t0 = Date.now();
    for (;;) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      const hit = extract(raw, nonce);
      if (hit) {
        const c = clip(hit.output.replace(/^\n+/, '').replace(/\n+$/, ''));
        return { output: c.out, exit_code: hit.code, timed_out: false, truncated: c.truncated };
      }
      if (Date.now() - t0 > timeoutMs) {
        bridge.sendSerialBytes([0x03]);
        const text = raw.replace(ANSI, '').replace(/\r/g, '');
        const b = text.indexOf(`@@B${nonce}@@\n`);
        const c = clip(b >= 0 ? text.slice(b + `@@B${nonce}@@\n`.length) : '');
        return { output: c.out, exit_code: null, timed_out: true, truncated: c.truncated };
      }
      await new Promise((r) => setTimeout(r, 100));
    }
  } finally {
    bridge.onSerialData = prev;
    busy = false;
  }
}
