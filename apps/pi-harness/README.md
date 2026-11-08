# WorkRAG Pi Agent worker

Pinned official packages: `@earendil-works/pi-agent-core`, `pi-ai`, and `pi-schema`, version **1.5.0**. Node >=22.19 is required; this workstation runs 22.20.0.

`server.mjs` runs a real Pi `Agent` per authenticated WebSocket request. `/health` reports engine, version and active requests. It listens on **127.0.0.1:8062**, requires a private Bearer transport token on `/run`, permits two concurrent requests, limits frames to 4 MiB, and aborts at a 190-second fallback deadline or when the connection closes. LangGraph enforces the configured turn timeout (normally 180 seconds) and bounded queue first.

Runtime boundary:

1. Keep LangBot as the bot, card, configured model and authorization owner.
2. Keep LangGraph load/reuse/followup/finalize, PostgreSQL memory, review, signed scopes and source validation.
3. Replace the current Agent-to-tools loop with one Pi-owned loop. Do not let both Pi and LangGraph execute the same tool call.
4. Run each request in an independent Pi Agent inside the Node service. Bounded WebSocket RPC bridges Pi `streamFn` and tools; Python forwards authorized calls on the owning Runner task through InvocationBridge. Do not copy model keys into Node.
5. Preserve the six-tool-call cap, 180-second deadline, cancellation, two-request concurrency, current-turn evidence gates and per-user isolation.
6. Keep an explicit `pi` / `legacy` engine rollback switch. Do not automatically replay a failed request through another engine.

Public text deltas stream live from LangBot. Planning remains private. Knowledge answers use a tool-free final stream after checking current-turn sources. No coding-agent shell, filesystem write tools, or LangBot management MCP is enabled.

From `G:\项目\WorkRAG`, normal `deployment/local.py start|stop|status` manages this worker too. Select an engine with `.\.venv\Scripts\python.exe deployment/select_agent_engine.py pi --target both`; rollback uses `legacy --target both`. Existing memory, documents and card configuration remain in place. On another workstation, install dependencies with `npm ci --ignore-scripts` here first. Keep the ignored `data/manuals/runtime/agent-deployment` directory private.

Verification:

- `npm test`: real Pi core with explicit mock model streams, scoped tools and interleaved Agents.
- `deployment/verify_pi_contract.py`: actual installed SDK + real Pi worker with mocked I/O; owner-task authorization, deltas, limits, provider/tool errors, cancellation and isolation.
- `deployment/verify_pi_real.py`: real DeepSeek and MCP knowledge, images, file and personal history in the debug processor.
- `deployment/verify_pi_release.py`: debug-only real streaming, grants, call limit, timeout/cleanup, restart and persisted history; restores settings in `finally`.

Installed-state report: `docs/Pi-Agent接入与验收.md`.

Source: https://github.com/earendil-works/pi/tree/main/packages/agent
