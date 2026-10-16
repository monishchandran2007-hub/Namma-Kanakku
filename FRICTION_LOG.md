# KiranaFlow - Developer Friction Log

> **Context**: Real engineering friction encountered while building **KiranaFlow** for the Alexa+ track of the *Amazon Developer Hackathon 2026* (October 2026).
>
> All entries document authentic issues, reproduction steps, root causes, and verified workarounds.

---

## 1. Official Python MCP SDK 2.x Migration (`FastMCP` → `MCPServer`)

### Friction
When initializing the MCP server using typical patterns found across the MCP community, blogs, and tutorials:
```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("KiranaFlow")
```
Python fails immediately with:
```
ModuleNotFoundError: No module named 'mcp.server.fastmcp'
```

### Root Cause
In version `2.0.0+` of the official Python SDK (`mcp==2.3.0`), the high-level server implementation was relocated and refactored from `mcp.server.fastmcp` to `mcp.server.mcpserver.MCPServer`. The package structure was cleaned up, but online documentation, tutorials, and early examples still predominantly cite `FastMCP`.

### Resolution & Verified Code
Update the import to use `MCPServer`:
```python
from mcp.server.mcpserver import MCPServer
mcp = MCPServer(name="KiranaFlow", version="1.0.0")
```
Similarly, for client testing, the Streamable HTTP transport is located at:
```python
from mcp.client.streamable_http import streamable_http_client
```
*(Notice the underscore: `streamable_http`, not `streamablehttp`)*.

---

## 2. Alexa+ Developer Tooling in Partner Preview

### Friction
The hackathon instructions and track announcements refer to Alexa+ CLI commands (e.g. `alexa-ai deploy`, `alexa-ai test`) and the Alexa Simulator. However, on running these tools or checking developer portal accounts, non-partner accounts receive authorization errors or command-not-found. Devpost community discussions confirmed that the Alexa+ local simulator is in private preview for select partner organizations.

### Impact on Independent Developers
Independent hackathon participants cannot verify conversational audio rendering through the proprietary simulator without preview access.

### Resolution & Workaround
1. Decoupled the architecture cleanly according to MCP standards:
   - Alexa+ handles ASR, Tanglish translation, and slot extraction.
   - KiranaFlow handles deterministic business logic, ledger safety, and MCP protocol delivery over standard **Streamable HTTP** (`/mcp`).
2. Built a comprehensive local test harness:
   - `test_stage1.py`, `test_stage2.py`, `test_stage5.py` (36 pytest unit tests).
   - `smoke_test.py` performing authentic JSON-RPC 2.0 handshake (`initialize`, `tools/list`, `resources/read`, `tools/call`) and measuring p50/p95 latency over 50 sequential calls.
   - Built a browser-accessible fallback ledger (`/ledger`) and interactive widget inspector (`/widget`) so judges can inspect every state transition visually.

---

## 3. Windows Terminal Default Encoding (`cp1252`) vs Indic Unicode Scripts

### Friction
When testing Tamil script input transliteration (e.g., `தயிர்` for curd, `துவரம் பருப்பு` for toor dal) on Windows workstations running PowerShell or Command Prompt:
```
UnicodeEncodeError: 'charmap' codec can't encode characters in position 0-4: character maps to <undefined>
```

### Root Cause
Standard Windows console sessions default to legacy code pages (such as `cp1252` or `cp437`), which fail to encode Indic Unicode code points in terminal print statements, even when the underlying Python string is valid UTF-8.

### Resolution & Workaround
1. Added Unicode normalization and phonetic Latin transliteration in [matching.py](file:///d:/Amazon%20aws/matching.py) so Tamil script characters are deterministically mapped to phonetic Latin representations (`thayir`, `toor dal`) before logging.
2. In all terminal outputs, sanitized strings or ensured standard ASCII fallback formatting.
3. Recommended setting `PYTHONIOENCODING=utf-8` in environment configurations.

---

## 4. MCP Apps UI Handshake & Metadata Placement Ambiguity

### Friction
The MCP Apps specification introduces interactive UI cards embedded inside AI assistant interfaces. However, different client prototypes interpret the metadata location differently:
- Some client implementations inspect `meta.ui.resourceUri` on the **tool schema** returned during `tools/list`.
- Other clients expect `_meta.ui.resourceUri` inside the **tool call result** payload returned by `tools/call`.

### Resolution & Workaround
KiranaFlow implements dual-layer metadata:
1. In `server.py`, every tool that produces a visual card specifies `meta={"ui": {"resourceUri": "ui://khata-card"}}` during discovery.
2. Every tool handler returns `_meta: {"ui": {"resourceUri": "ui://khata-card"}}` inside the JSON result dictionary.
3. The widget HTML (`widget.html`) implements a postMessage bridge that responds to standard MCP Apps lifecycle messages:
   - `ui/initialize`
   - `ui/notifications/initialized`
   - `host-context-changed` (theme change: light vs dark)
   - `ui/notifications/tool-input` (live updates during tool execution)

---

## 5. Ledger Discretion vs Assistant "Helpfulness"

### Friction
Standard conversational assistants are trained to be as informative as possible—reciting total balances, credit limits, and historical statements after every action. In a busy Indian kirana store, where customers stand side-by-side at the counter:
- Announcing *"Ramesh Teacher has an unpaid balance of Rs 3,450 and is near his limit"* destroys customer privacy and causes immense social friction.

### Resolution & Workaround
Enforced an architectural hard constraint in the MCP server:
- `log_credit_entry`, `record_payment`, `undo_last_entry`, and `get_overdue_accounts` strictly return **zero** customer balances in `spoken_summary`.
- Balance is spoken **exclusively** when the shopkeeper explicitly invokes `get_customer_balance`.
- Sensitive notifications (such as 30-day overdue nudges or credit limit proximity) are rendered solely on the screen (`screen_note` and the `ui://khata-card` widget), never spoken aloud.

---

## 6. Cloud Platform Dependency Conflicts: Gradio 6.x `[mcp]` vs Official `mcp==2.3.0`

### Friction
When deploying to free cloud hosting on Hugging Face Spaces (Gradio SDK), the build failed during package resolution with:
```
ERROR: Cannot install gradio[mcp,oauth]==6.30.0 and mcp==2.3.0 because these package versions have conflicting dependencies.
gradio[mcp,oauth] 6.30.0 depends on mcp<2.0.0 and >=1.21.0; extra == "mcp"
```

### Root Cause
Hugging Face's default Gradio builder injected `gradio[oauth,mcp]==6.30.0`. Gradio's internal `mcp` extra had pinned `mcp<2.0.0`, conflicting directly with the official modern `mcp==2.3.0` specification used across our server.

### Resolution & Workaround
1. Pinned `sdk_version: 5.20.0` in the Space's `README.md` metadata (Gradio 5.x does not bundle the conflicting `mcp<2.0.0` sub-dependency).
2. Removed redundant `gradio` declarations from `requirements.txt` so pip cleanly installs the modern `mcp==2.3.0` stack.

---

## 7. Cloud Watchdog Killing CPU Workloads: Hugging Face ZeroGPU Service SIGTERM

### Friction
When deploying the CPU-based MCP server to Hugging Face Spaces, the container started normally, bound to port 7860, but was abruptly killed within 15 seconds of launch:
```
Exit code: 3. Reason: No @spaces.GPU function detected during startup
Starting Namma-Kanakku on port 7860...
```

### Root Cause
Hugging Face Spaces runs a supervisor service on port 7861 that inspects Python processes at startup. Even when the hardware is configured for CPU (`hardware: cpu-basic`), if the environment detects the `spaces` package or ZeroGPU infrastructure hooks, the supervisor service requires at least one registered `@spaces.GPU` entrypoint. If the count of registered GPU functions is 0, the supervisor concludes the application misconfigured its GPU requests and immediately issues a `SIGTERM`.

### Resolution & Workaround
Register a lightweight, no-op placeholder decorated with `@spaces.GPU`:
```python
try:
    import spaces

    @spaces.GPU
    def _gpu_warmup():
        """No-op placeholder satisfying ZeroGPU startup count on CPU space."""
        pass
except Exception:
    pass
```
Because the `@spaces.GPU` decorator registers the function metadata during module import without actually allocating GPU hardware, the supervisor count test passes immediately. Since the function is never called, zero GPU quotas are consumed.

---

## 8. Dual-Stack Routing: Gradio SPA Catch-All vs Starlette MCP Endpoints

### Friction
When mounting the Starlette MCP application (`/mcp`, `/widget`, `/healthz`, `/ledger`) alongside Gradio in `app.py`:
- Visiting `/widget` or loading the interactive card in an `<iframe>` recursively rendered the Gradio UI instead of the widget HTML.
- Requests to `/healthz` returned the Gradio SPA fallback instead of JSON.

### Root Cause
Gradio mounts an internal single-page application (SPA) catch-all route at `/` that captures unhandled paths before sub-mounted apps (e.g. `gradio_app.mount("/mcp-app", starlette_app)`) can process root-relative paths like `/widget` or `/healthz`.

### Resolution & Workaround
Directly inject the Starlette app routes at index 0 of Gradio's internal FastAPI router so that dedicated endpoints take priority over the SPA catch-all:
```python
for route in reversed(starlette_app.routes):
    gradio_fastapi.routes.insert(0, route)
```
This guarantees `/mcp`, `/widget`, `/healthz`, and `/ledger` respond with their authentic payloads, while preserving Gradio's interactive UI at root.

