// Provider presets for the agent. Two wire formats cover all of them:
//  - 'anthropic' : Anthropic Messages API
//  - 'openai'    : OpenAI-style chat completions with tool calls
// Everything else is a preset that only changes base URL and model suggestions.

export type WireFormat = 'anthropic' | 'openai';

export interface ProviderPreset {
  id: string;
  label: string;
  format: WireFormat;
  baseUrl: string;
  /** Suggested models; the field stays free text because model names change. */
  models: string[];
  needsKey: boolean;
  /** The base URL is editable (custom / local endpoints). */
  editableUrl: boolean;
  hint?: string;
}

export const PROVIDERS: ProviderPreset[] = [
  {
    id: 'anthropic',
    label: 'Anthropic (Claude)',
    format: 'anthropic',
    baseUrl: 'https://api.anthropic.com',
    models: ['claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-5-5'],
    needsKey: true,
    editableUrl: false,
  },
  {
    id: 'openai',
    label: 'OpenAI',
    format: 'openai',
    baseUrl: 'https://api.openai.com/v1',
    models: [],
    needsKey: true,
    editableUrl: false,
    hint: 'Enter a chat model that supports tool calls.',
  },
  {
    id: 'gemini',
    label: 'Google Gemini',
    format: 'openai',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    models: [],
    needsKey: true,
    editableUrl: false,
    hint: 'Uses Gemini’s OpenAI-compatible endpoint.',
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    format: 'openai',
    baseUrl: 'https://openrouter.ai/api/v1',
    models: [],
    needsKey: true,
    editableUrl: false,
    hint: 'Any model id from openrouter.ai/models that supports tools.',
  },
  {
    id: 'groq',
    label: 'Groq',
    format: 'openai',
    baseUrl: 'https://api.groq.com/openai/v1',
    models: [],
    needsKey: true,
    editableUrl: false,
  },
  {
    id: 'nvidia',
    label: 'NVIDIA (build.nvidia.com / NIM)',
    format: 'openai',
    baseUrl: 'https://integrate.api.nvidia.com/v1',
    models: ['meta/llama-3.3-70b-instruct', 'meta/llama-3.1-405b-instruct'],
    needsKey: true,
    editableUrl: false,
    hint:
      'Key starts with nvapi-. Get one at build.nvidia.com. Pick a model that ' +
      'supports tool calling; the model id is shown on its page.',
  },
  {
    id: 'ollama-cloud',
    label: 'Ollama Cloud',
    format: 'openai',
    baseUrl: 'https://ollama.com/v1',
    models: [],
    needsKey: true,
    editableUrl: true,
    hint: 'Check the base URL against your Ollama Cloud account.',
  },
  {
    id: 'ollama-local',
    label: 'Ollama (local)',
    format: 'openai',
    baseUrl: 'http://host.docker.internal:11434/v1',
    models: [],
    needsKey: false,
    editableUrl: true,
    hint:
      'Runs on your machine. The server must be started with ' +
      'IOT_AGENT_ALLOW_PRIVATE_URLS=1 to reach private addresses.',
  },
  {
    id: 'custom',
    label: 'Custom (OpenAI-compatible)',
    format: 'openai',
    baseUrl: '',
    models: [],
    needsKey: true,
    editableUrl: true,
    hint: 'Any server that speaks the OpenAI chat-completions API.',
  },
];

export function getProvider(id: string): ProviderPreset {
  return PROVIDERS.find((p) => p.id === id) ?? PROVIDERS[0];
}
