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
3. **Provider-agnostic adapter.** One interface, adapters for Anthropic and
   OpenAI-compatible endpoints (covers Ollama Cloud and local Ollama).
4. **Human in the loop by default.** Read-only tools run freely; anything that
   changes the project goes through a diff/approve step. A per-session "auto"
   mode and an undo checkpoint before each agent turn.

## 4. Tool surface (v1)

Read: `get_project` (files, boards, parts, wires), `get_serial(since?, board)`,
`get_wifi_status`, `get_compile_log`, `get_pin_states`, `list_components`,
`search_examples`.
Write: `write_file`, `edit_file` (patch), `add_component`, `connect_pins`,
`remove_component`, `set_board`, `set_sensor_value`.
Act: `compile`, `run`, `stop`, `reset`, `wait_for_serial(pattern, timeout)`,
`http_get_gateway(path)` (fetches the sketch's web page through
`/api/gateway`), `press_button` / `set_input`.
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
- Config through env: `IOT_AGENT_PROVIDER`, `IOT_AGENT_MODEL`,
  `IOT_AGENT_API_KEY` (compose / `.env`, never baked into the image),
  `IOT_AGENT_MAX_TOKENS_PER_DAY`. With no key set the panel shows setup help
  and the app behaves exactly as today.

## 6. Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Decisions below confirmed; `overlay/` + `apply_overlay()` + hook patches, empty panel renders in the built app | Image builds in CI; panel toggles; stock behaviour unchanged |
| M1 | Tool registry + read-only tools; panel shows live project/serial through the tools | Unit tests for each tool against the stores |
| M2 | LLM proxy + loop + chat; read/write/compile/run tools; approval UI + undo | "Blink GPIO2 every second" works end to end on ESP32 |
| M3 | Closed-loop skills: *build-and-verify* (compile → fix errors, ≤ N tries → run → `wait_for_serial` → check gateway page) and *circuit-from-description* | The DHT22 + PIR + LDR web-server sketch is produced from one prompt and its page loads |
| M4 | Bridge for external MCP clients (pairing code per session) | Claude Code drives the open app and reads serial |
| M5 | CI smoke tests: headless scenarios (compile + run + assert serial) on the QEMU backend; cost/latency report | Green on every release build |
| M6 | Hardening: budgets, redaction, prompt-injection tests, docs | Checklist in section 7 passes |

Each milestone is a separate PR into `agentic-iot-studio`; the branch merges
back to the release line only when M2 is solid.

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
- **Secrets.** Provider keys only via environment on the server; never in the
  image, the repo, logs or the browser.

## 8. Decisions needed before M0

1. **LLM provider and model** for v1: Anthropic, an OpenAI-compatible
   endpoint, or Ollama Cloud / local Ollama. The adapter makes this a config
   choice, but the default affects prompts and tool-call format.
2. **Who pays / where the key lives:** one server-side key from the deployer
   (default in this plan) or bring-your-own-key entered in the UI.
3. **v1 scope:** ESP32 + Arduino C++ first (our tested path), or also AVR /
   Pico / MicroPython from the start.
4. **Autonomy default:** approve every change (default) or auto-apply with
   undo.
