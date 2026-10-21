# IoT-Studio → agentic: plan

Branch: `agentic-iot-studio` (cut from `whitelabel-iot-studio` v2.4.0). The
white-label branch stays the stable, released line. Nothing here is built yet;
this document is the plan to review before any code.

## 1. Goal

Today a person writes the sketch, wires the circuit, compiles, runs, reads the
Serial Monitor and debugs. The goal is an **in-app agent that does that loop
for them**: from a request like *"ESP32 web page showing DHT22 temperature,
LED on motion"* it builds the circuit, writes the code, compiles, fixes
errors, runs the simulation, checks the result (serial output, the IoT-Gateway
page, pin states) and reports back, with the user able to approve, steer or
undo at every step.

## 2. What Velxio already gives us (and the gap)

| Exists | Where | Limitation for an agent |
|---|---|---|
| MCP server (stdio + SSE): `compile_project`, `create_circuit`, `update_circuit`, `import/export_wokwi_json`, `generate_code_files` | `backend/app/mcp/server.py`, `docs/MCP.md` | Stateless. It cannot see or drive the **running** app, so no run / observe / fix loop. `run_project` only compiles. |
| Live state in the browser | `useSimulatorStore` (boards, components, wires, `serialOutput`, `wifiStatus`, `running`), `useEditorStore` (files) | Not reachable from the backend or any external agent. |
| ESP32 runs in QEMU on the backend | `/api/simulation/ws`, `iot_gateway.py` | Output reaches the browser only. |
| Compile API | `services/compilation.ts` → `/api/compile` | Usable as is. |

**The gap is closed-loop access to the live session.** That is the core of
the plan; the LLM chat UI is the small part.

## 3. Architecture

```
 ┌────────────── browser (IoT-Studio) ─────────────┐        ┌── backend (FastAPI) ──┐
 │  Agent panel (chat, plan, tool timeline, diffs) │        │  /api/agent/llm  ──────────► LLM provider
 │        │                                        │ SSE/   │   (holds API key,     │   (Anthropic /
 │  Agent loop (plan → tool call → observe → …)  ◄─┼────────┤    streams tokens,    │    OpenAI-compat /
 │        │                                        │ fetch  │    rate/budget limit) │    Ollama Cloud)
 │  Tool registry  ──► stores / compile / run /    │        │  /api/agent/bridge ◄──────── MCP clients
 │  (typed, schema'd)    serial / gateway          │        │   (WS: external agents│   (Claude Code,
 └─────────────────────────────────────────────────┘        │    drive live session)│    Cursor)
                                                            └───────────────────────┘
```

Decisions and why:

1. **Agent loop runs in the browser; the backend is a thin LLM proxy.** The
   simulation state and tools live in the browser, so tool calls stay local
   (no round trips). The backend only holds the provider key, streams, and
   enforces limits. The key never reaches the browser.
2. **One typed tool registry, two front ends.** The same tool definitions
   power the in-app agent and (via a bridge WebSocket) external MCP clients,
   so Claude Code or Cursor can drive the open app too.
3. **Provider chosen in the UI (decided).** A provider picker in the agent
   panel: Anthropic, OpenAI, Google Gemini, OpenRouter, Groq, Ollama Cloud,
   local Ollama and any custom OpenAI-compatible endpoint. Two adapters cover
   all of them (Anthropic Messages API; OpenAI-style chat completions with
   tool calls); the rest are presets that only differ in base URL and model
   list.
4. **Bring your own key (decided).** The user enters the API key in the panel.
   It is kept in the browser (session-only by default, "remember on this
   device" optional) and sent per request to the backend proxy in a header.
   The server never stores or logs it and has no key of its own. The proxy
   refuses private / loopback / link-local base URLs (SSRF guard) unless the
   deployer sets `IOT_AGENT_ALLOW_PRIVATE_URLS=1`, which local Ollama needs.
5. **Auto-apply with undo (decided).** The agent edits the project directly.
   Every agent turn starts with an automatic checkpoint (files, boards, parts,
   wires); the panel shows each change as it happens and has one-click
   "undo this turn" plus a per-step revert. Destructive actions the agent
   cannot undo (there are none in the tool set) would still need approval.

## 4. Tool surface (v1)

Read: `get_project` (files, boards, parts, wires), `get_serial(since?, board)`,
`get_wifi_status`, `get_compile_log`, `get_pin_states`, `list_components`,
`search_examples`.
Write: `write_file`, `edit_file` (patch), `add_component`, `connect_pins`,
`remove_component`, `set_board`, `set_sensor_value`.
Act: `compile`, `run`, `stop`, `reset`, `wait_for_serial(pattern, timeout)`,
`http_get_gateway(path)` (fetches the sketch's web page through
`/api/gateway`), `press_button` / `set_input`.
Linux boards (Raspberry Pi 3 variants): `terminal_send(text)`,
`terminal_read(since?)`, so the agent can run shell commands and Python on
the emulated Pi.

**Every board family (decided).** Tools take a `board` argument and resolve
the board kind at call time: AVR (Uno/Nano/Mega/ATtiny), ESP32 / S3 / C3,
RP2040 / Pico / Pico W, STM32, Raspberry Pi 3, plus MicroPython mode. A
capability table maps each kind to what it supports (compile target, serial
vs terminal, WiFi/gateway, flashing path) and the agent prompt is generated
from it, so a new board kind needs one table entry, not new tools.
Meta: `ask_user`, `checkpoint`, `undo_to_checkpoint`.

Tools return small structured results (errors summarised, serial truncated to
the tail) to keep context and cost down.

## 5. Where the code lives (important)

This repo does **not** contain Velxio's source; `build.py` clones it and
`rebrand.py` patches it. Agent code follows the same model:

- New files live in this repo under `overlay/` and are copied into the cloned
  tree by a new `apply_overlay()` step in `build.py` (idempotent, runs after
  `rebrand`):
  - `overlay/frontend/src/agent/**` — panel, loop, tools, provider client
  - `overlay/backend/app/agent/**` — `/api/agent/*` router, provider adapters,
    budget limiter, bridge
- A few **small anchored hook patches** in `rebrand.py` style, with
  `IOT_STUDIO_STRICT=1` catching upstream drift:
  - `backend/app/main.py`: `include_router(agent.router, prefix="/api/agent")`
  - `frontend/src/pages/EditorPage.tsx`: mount `<AgentPanel />`
  - `docker/nginx.conf`: disable buffering for `/api/agent/` (SSE)
- Config is in the panel (provider, model, base URL, key). The only server
  settings are optional: `IOT_AGENT_ALLOW_PRIVATE_URLS=1` (local Ollama) and
  `IOT_AGENT=off` to remove the feature. With no key entered the panel shows
  setup help and the app behaves exactly as today.

## 6. Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | `overlay/` + `apply_overlay()` + hook patches, empty panel renders in the built app | Image builds in CI; panel toggles; stock behaviour unchanged |
| M1 | Tool registry + read-only tools + board capability table; panel shows live project/serial through the tools | Unit tests for each tool against the stores, across board kinds |
| M2 | LLM proxy + loop + chat; read/write/compile/run tools; approval UI + undo | "Blink GPIO2 every second" works end to end on ESP32 |
| M3 | Closed-loop skills: *build-and-verify* (compile → fix errors, ≤ N tries → run → `wait_for_serial` → check gateway page) and *circuit-from-description* | The DHT22 + PIR + LDR web-server sketch is produced from one prompt and its page loads |
| M4 | Bridge for external MCP clients (pairing code per session) | Claude Code drives the open app and reads serial |
| M5 | CI smoke tests: headless scenarios (compile + run + assert serial) on the QEMU backend; cost/latency report | Green on every release build |
| M6 | Hardening: budgets, redaction, prompt-injection tests, docs | Checklist in section 7 passes |

Each milestone is a separate PR into `agentic-iot-studio`; the branch merges
back to the release line only when M2 is solid.

## 6a. Status

- **M0 done:** overlay, hooks, panel, provider/key settings, URL guard.
- **M1/M2 mostly done (code + run loop):** tool registry, LLM proxy
  (Anthropic + OpenAI-compatible), chat UI, per-turn checkpoint with undo of
  project files, test-connection. Verified in a browser against a scripted
  mock model (tool calls, file edit, undo) and by unit tests for the proxy.
  **Not yet verified against a real model or a real compile/run.**
- **Still to do from M1/M2:** circuit tools (add/wire/remove parts, sensor
  values, button presses), checkpoint of circuit state, Raspberry Pi terminal
  tools, streaming replies, board capability table in the prompt.
- **Next:** M3 build-and-verify skills and circuit-from-description.

## 7. Risks and safeguards

- **Prompt injection.** Serial output, the gateway page, library docs and
  imported projects are untrusted text. They are passed as clearly delimited
  *data*, never as instructions; no tool can read host files, run shell
  commands or reach the network beyond the compile and gateway APIs.
- **Runaway cost/loops.** Hard caps on steps per turn, compile retries, tokens
  per session and per day; visible counters in the panel.
- **Destructive edits.** Checkpoint before each turn, diff + approve, one-click
  undo; the agent never deletes projects.
- **Emulator limits.** WSL2 is slow, so `wait_for_serial` uses generous
  timeouts and reports "no output yet" rather than failing.
- **Upstream drift.** Hook patches are anchored and strict in CI; the overlay
  avoids importing Velxio internals beyond the stores and APIs listed above.
- **Licence.** Velxio is AGPLv3 (plus commercial licence). The overlay is
  published under AGPLv3 with the rest of this repo; the NOTICE stays.
- **Secrets.** The user's key lives only in their browser and in the request
  header to the proxy; it is never written to disk, logs or the image, and the
  proxy strips it from error output.

## 8. Decisions (confirmed)

1. **Provider:** selectable in the UI (section 3, item 3).
2. **Key:** entered by the user, kept in the browser, proxied per request
   (section 3, item 4).
3. **Scope:** every board family, including Raspberry Pi variants.
4. **Autonomy:** auto-apply with undo (section 3, item 5).

Still open (defaults assumed, easy to change): the default model suggested
per provider, and the daily token budget shown in the panel.
