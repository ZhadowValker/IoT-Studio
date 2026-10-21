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

export async function callLlm(
  settings: AgentSettings,
  system: string,
  messages: ChatMessage[],
  tools: ToolSpec[],
  signal?: AbortSignal,
): Promise<LlmReply> {
  const provider = getProvider(settings.providerId);
  const baseUrl = (provider.editableUrl ? settings.baseUrl : provider.baseUrl).trim();
  if (!baseUrl) throw new LlmClientError('Enter the provider base URL in the settings.');
  if (!settings.model.trim()) throw new LlmClientError('Enter a model id in the settings.');
  if (provider.needsKey && !settings.apiKey.trim()) {
    throw new LlmClientError('Enter your API key in the settings.');
  }

  let res: Response;
  try {
    res = await fetch('/api/agent/llm', {
      method: 'POST',
      signal,
      headers: { 'Content-Type': 'application/json', 'X-Agent-Key': settings.apiKey.trim() },
      body: JSON.stringify({
        format: provider.format,
        base_url: baseUrl,
        model: settings.model.trim(),
        system,
        messages,
        tools,
      }),
    });
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    throw new LlmClientError('Could not reach the IoT-Studio backend.');
  }

  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) {
    const msg = (body as { error?: string } | null)?.error;
    throw new LlmClientError(msg ?? `The agent backend answered ${res.status}.`);
  }
  return body as LlmReply;
}
