import { getProvider } from './providers';
import type { AgentSettings } from './settings';

// Neutral (OpenAI-style) conversation format. The backend adapts it to the
// provider's wire format, so the loop never cares which provider is in use.

export interface ToolCall {
  id: string;
  type: 'function';
  function: { name: string; arguments: string };
}

export type ChatMessage =
  | { role: 'user'; content: string }
  | { role: 'assistant'; content: string; tool_calls?: ToolCall[] }
  | { role: 'tool'; tool_call_id: string; content: string };

export interface ToolSpec {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

export interface LlmReply {
  content: string;
  tool_calls: { id: string; name: string; arguments: string }[];
  finish_reason: string | null;
  usage: { input: number; output: number };
}

export class LlmClientError extends Error {}

function buildRequest(settings: AgentSettings, system: string, messages: ChatMessage[], tools: ToolSpec[]) {
  const provider = getProvider(settings.providerId);
  const baseUrl = (provider.editableUrl ? settings.baseUrl : provider.baseUrl).trim();
  if (!baseUrl) throw new LlmClientError('Enter the provider base URL in the settings.');
  if (!settings.model.trim()) throw new LlmClientError('Enter a model id in the settings.');
  if (provider.needsKey && !settings.apiKey.trim()) {
    throw new LlmClientError('Enter your API key in the settings.');
  }
  return {
    headers: { 'Content-Type': 'application/json', 'X-Agent-Key': settings.apiKey.trim() },
    body: JSON.stringify({
      format: provider.format,
      base_url: baseUrl,
      model: settings.model.trim(),
      system,
      messages,
      tools,
    }),
  };
}

async function post(path: string, req: { headers: Record<string, string>; body: string }, signal?: AbortSignal) {
  try {
    return await fetch(path, { method: 'POST', signal, ...req });
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    throw new LlmClientError('Could not reach the IoT-Studio backend.');
  }
}

async function failure(res: Response): Promise<LlmClientError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error page */
  }
  const msg = (body as { error?: string } | null)?.error;
  return new LlmClientError(msg ?? `The agent backend answered ${res.status}.`);
}

export async function callLlm(
  settings: AgentSettings,
  system: string,
  messages: ChatMessage[],
  tools: ToolSpec[],
  signal?: AbortSignal,
): Promise<LlmReply> {
  const res = await post('/api/agent/llm', buildRequest(settings, system, messages, tools), signal);
  if (!res.ok) throw await failure(res);
  return (await res.json()) as LlmReply;
}

/** Same turn, but `onText` gets the reply as the model writes it. Falls back
 *  to the one-shot call when the stream is unavailable (old backend, proxy
 *  that buffers or strips it). */
export async function callLlmStream(
  settings: AgentSettings,
  system: string,
  messages: ChatMessage[],
  tools: ToolSpec[],
  onText: (delta: string) => void,
  signal?: AbortSignal,
): Promise<LlmReply> {
  const req = buildRequest(settings, system, messages, tools);
  const res = await post('/api/agent/llm/stream', req, signal);
  if (res.status === 404 || res.status === 405) return callLlm(settings, system, messages, tools, signal);
  if (!res.ok) throw await failure(res);
  if (!res.body) return callLlm(settings, system, messages, tools, signal);

  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  let done: LlmReply | null = null;
  const handle = (line: string) => {
    if (!line.trim()) return;
    let ev: { t?: string; d?: string; reply?: LlmReply; message?: string };
    try {
      ev = JSON.parse(line);
    } catch {
      return;
    }
    if (ev.t === 'text' && ev.d) onText(ev.d);
    else if (ev.t === 'done' && ev.reply) done = ev.reply;
    else if (ev.t === 'error') throw new LlmClientError(ev.message ?? 'The model stream failed.');
  };
  try {
    for (;;) {
      const { value, done: end } = await reader.read();
      if (end) break;
      buf += dec.decode(value, { stream: true });
      let i: number;
      while ((i = buf.indexOf('\n')) >= 0) {
        handle(buf.slice(0, i));
        buf = buf.slice(i + 1);
      }
    }
    handle(buf);
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    if (e instanceof LlmClientError) throw e;
    throw new LlmClientError('The model stream was interrupted.');
  }
  if (!done) throw new LlmClientError('The model stream ended without an answer.');
  return done;
}

/** Chat-capable model ids only: reranker, embedding, guard, speech and image
 *  models answer 404 on chat completions, which is easy to pick by mistake. */
const NOT_CHAT = /(rerank|embed|retriev|guard|reward|safety|parakeet|riva|whisper|tts|asr|clip|diffus|sdxl|image|vision-only|nv-)/i;

export async function fetchModels(settings: AgentSettings): Promise<string[]> {
  const provider = getProvider(settings.providerId);
  const baseUrl = (provider.editableUrl ? settings.baseUrl : provider.baseUrl).trim();
  if (!baseUrl) throw new LlmClientError('Enter the provider base URL first.');
  if (provider.needsKey && !settings.apiKey.trim()) throw new LlmClientError('Enter your API key first.');
  const res = await fetch('/api/agent/models', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Agent-Key': settings.apiKey.trim() },
    body: JSON.stringify({ format: provider.format, base_url: baseUrl }),
  });
  let body: { models?: string[]; error?: string } | null = null;
  try {
    body = await res.json();
  } catch {
    /* ignore */
  }
  if (!res.ok || !body?.models) throw new LlmClientError(body?.error ?? `Model list failed (${res.status}).`);
  return body.models.filter((m) => !NOT_CHAT.test(m));
}
