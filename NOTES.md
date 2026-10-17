# KiranaFlow: Stage 0 Notes & Verification Matrix

Confirmed facts extracted from official Amazon Developer documentation, Model Context Protocol specifications, and Devpost Hackathon rules.

---

## 1. Confirmed Facts (with Official Source URLs)

### Hackathon Rules & Track Reality
* **Devpost Submission Deadline**: October 23, 2026, 12:00 PM PDT. Judging period: November 9, 2026 – November 20, 2026.
  * *Source*: [Devpost Timeline](https://amazonappdev2026.devpost.com/)
* **Alexa+ Tooling Access Notice**: Official Alexa+ developer tools (Category SDK, MCP Toolkit, CLI, and Web Simulator) are in private preview for select partners and are not accessible to public hackathon participants. Devpost rules state participants can build a self-hosted Model Context Protocol (MCP) server or simulated conversational experience demonstrated via web UI/simulator.
  * *Source*: [Devpost Alexa+ Track FAQ & Rules](https://amazonappdev2026.devpost.com/rules)
* **Judging Criteria & Bonus**: Tech Implementation, Design, Potential Impact, Quality of the Idea (equally weighted). Submissions with a real friction log covering tools used can earn up to a 10% judging bonus. Video must be under 3 minutes, with strongest material in the first 30 seconds.
  * *Source*: [Devpost Rules & Judging Criteria](https://amazonappdev2026.devpost.com/rules)

### Alexa+ MCP Protocol & Lifecycle
* **Streamable HTTP Transport Required**: Alexa+ MCP servers must support Streamable HTTP. The legacy standalone HTTP+SSE transport was deprecated in the MCP specification (2025-11-25) in favor of Streamable HTTP.
  * *Source*: [Alexa+ MCP Quickstart Guide](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart)
* **Lifecycle & Session Handling**: Alexa+ acts as an MCP client. It sends standard JSON-RPC 2.0 `initialize` (`protocolVersion: "2025-03-26"` or later) and `tools/call`. Alexa+ does not provide an explicit session ID; context is maintained by Alexa across conversation history.
  * *Source*: [Alexa+ MCP Client and App Lifecycle](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-client-lifecycle)
* **Tool Call Response UI Metadata**: Alexa+ renders custom visuals if `resourceUri` is defined in the tool response (`result._meta.ui.resourceUri`). If no `resourceUri` is present, Alexa+ falls back to its native data-only rendering.
  * *Source*: [Alexa+ MCP Client and App Lifecycle](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-client-lifecycle)
* **UI Layout & Surface Adaptability**: Alexa renders UI payloads inside a sandboxed iframe. Devices scale via two viewports: Block (horizontal scroll for native Alexa+ screens) and Card (vertical scroll). The host communicates via postMessage delivering `hostContext` (`deviceClass`, `maxWidth`, `maxHeight`, `theme`, `displayMode`, `isMobile`, etc.).
  * *Source*: [Alexa+ MCP Design Guide: Layout and Rendering](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-addon-layout-and-rendering)

### MCP Apps Standard
* **UI Preloading & Scheme**: UI resources use the `ui://` URI scheme. In MCP Apps, tool definitions advertise `_meta.ui.resourceUri` in `tools/list` so the host can preload the UI.
  * *Source*: [MCP Apps Specification Overview](https://modelcontextprotocol.io/extensions/apps/overview)
* **PostMessage Handshake**: 
  1. Iframe sends `ui/initialize` request to parent with `appCapabilities`.
  2. Host responds with `hostContext`.
  3. Iframe fires `ui/notifications/initialized` notification.
  4. Host streams tool input via `ui/notifications/tool-input`.
  * *Source*: [MCP Apps Specification Overview](https://modelcontextprotocol.io/extensions/apps/overview)

### CLI & addon.json Constraints
* **Documented CLI Commands**:
  - `alexa-ai configure`
  - `alexa-ai new mcp --name <name> --locale <locale> --mcp-server-url <url>`
  - `alexa-ai deploy`
  - `alexa-ai submit`
  * *Source*: [Alexa AI CLI Reference](https://developer.amazon.com/docs/alexaplus/add-ons/alexa-ai-cli-reference)
* **addon.json Schema & Limits**:
  - `shortDescription`: String, required, $\le$ 123 characters.
  - `fullDescription`: String, required, $\le$ 4000 characters.
  - `examplePhrases`: Array of 3–4 strings, required, each $\le$ 200 characters.
  - `manifestVersion`: String, required, `"1.0"`.
  - `mediaAssets.icons.light`: Required 6 exact sizes: `72x72`, `64x64`, `88x88`, `126x126`, `180x180`, `241x241`.
  * *Source*: [Alexa+ MCP Quickstart Guide - addon.json Reference](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart)

### Cloud Infrastructure (Render Free Tier)
* **Payment Requirement**: No credit card required to deploy free web services on Render.
  * *Source*: [Render Free Services](https://render.com/docs/free)
* **Sleep Behavior**: Free web services spin down after 15 minutes of inactivity; cold starts take 30–60 seconds.
  * *Source*: [Render Free Services](https://render.com/docs/free)
* **Ephemeral Disk**: Local filesystem is wiped on spin-down, restart, or redeploy. Any persistent data in SQLite must be idempotently recreated and seeded with labelled demo data on application start.
  * *Source*: [Render Free Services](https://render.com/docs/free)

---

## 2. VERIFY List

| Item | Status | Finding & Verified Detail | Action / Design Defense |
| :--- | :---: | :--- | :--- |
| **(a) Streamable HTTP setup in installed mcp version** | **VERIFIED BY RUNNING** | Installed `mcp==2.3.0`. In `mcp>=2.0.0`, `FastMCP` was renamed to `MCPServer` (`from mcp.server.mcpserver import MCPServer`). Importing `from mcp.server.fastmcp import FastMCP` throws `ModuleNotFoundError`. `MCPServer.streamable_http_app(streamable_http_path='/mcp')` returns a Starlette ASGI app. | Use `MCPServer` from `mcp.server.mcpserver`, or support both by aliasing. Mount at `/mcp` with stateless HTTP configuration. |
| **(b) ui.resourceUri placement on tools** | **VERIFIED** | Alexa+ client lifecycle expects `resourceUri` in the `tools/call` response under `result._meta.ui.resourceUri`. The MCP Apps spec also allows `_meta.ui.resourceUri` in `tools/list` tool metadata. | Provide `_meta.ui.resourceUri` in both tool registration metadata (`@server.tool(meta={"ui": ...})`) and tool call response payload (`_meta: {"ui": {"resourceUri": "ui://khata-card"}}`). |
| **(c) MCP Apps resource mime type & postMessage handshake** | **VERIFIED** | MIME type for `ui://` resources is `text/html` (or `text/html;profile=mcp-app`). Handshake sequence: `ui/initialize` $\rightarrow$ host response $\rightarrow$ `ui/notifications/initialized` $\rightarrow$ `ui/notifications/tool-input`. | Serve the self-contained widget via `@server.resource("ui://khata-card", mime_type="text/html")`. Include vanilla JS handling both the MCP Apps handshake and window messages. Provide data-only fallback for standard Alexa clients. |
| **(d) whether `--mcp-server-url` takes base URL or `/mcp` URL** | **VERIFY / DEFENSIVE** | Docs show `--mcp-server-url "https://mcp.example.com"`. However, Streamable HTTP is mounted at `/mcp`. It is unverified whether Alexa's internal crawler hits the exact URL or appends `/mcp`. | Provide dual routing: Mount Streamable HTTP at `/mcp` AND handle `/` by redirecting (307) or forwarding to `/mcp`. |
| **(e) en-IN locale support** | **VERIFY** | `alexa-ai` CLI docs currently document `--locale en-US` as default and show only `en-US` in examples. ASK supports `en-IN`, but Alexa+ Private Preview may enforce `en-US`. | Set primary locale to `en-US` (as documented in CLI preview), while training matching pipelines to support Tanglish/Tamil transliteration. Note `en-IN` in documentation. |
| **(f) Render free-tier card requirement, sleep, filesystem** | **VERIFIED** | No credit card required. Sleeps after 15 min idle. Ephemeral filesystem resets on restart. | SQLite database initializes on startup; idempotently seeds realistic labelled demo data (`DEMO_MODE=True`). Cold starts fully self-contained. |
| **(g) addon.json fields constraints** | **VERIFIED** | `shortDescription` ($\le$ 123 chars), `fullDescription` ($\le$ 4000 chars), `examplePhrases` (3–4 phrases, each $\le$ 200 chars), light icon 6 sizes. | Write schema-compliant `addon-package/addon.json` matching these exact limits. |
| **(h) Starting workspace state** | **VERIFIED BY RUNNING** | `d:\Amazon aws` is currently an empty directory. The draft `server.py`, `smoke_test.py`, and `requirements.txt` mentioned in prompt were not pre-populated. | Implement fresh, hardened implementations adhering strictly to Stage 1+ specifications. |

---

## 3. Implementation Plan

* **Stage 1 (Core Hardening)**:
  - Database schema (`kirana.db`) with tables: `customers`, `catalog_items`, `item_aliases`, `ledger_entries`, `learned_aliases`.
  - Deterministic 6-step matching pipeline:
    1. Exact alias match (with Tamil $\rightarrow$ Latin script transliteration).
    2. Phonetic key matching (collapsing th/t, dh/d, aa/a, ee/i, oo/u, zh/l, double letters).
    3. Learned alias resolution ($\ge 2$ confirmations and $\ge 2\times$ runner-up).
    4. Rapidfuzz WRatio on phonetic keys (score $\ge 90$, unique SKU, gap $\ge 8$).
    5. Fallback matching on `english_guess`.
    6. Return `NEEDS_CLARIFICATION` (up to 3 options) or `ITEM_NOT_RECOGNIZED`.
  - Five core ledger tools: `log_credit_entry`, `record_payment`, `get_customer_balance`, `undo_last_entry`, `get_overdue_accounts`.
  - Discretion rules (spoken balance only in `get_customer_balance`; screen-only notes for overdue/limits).
  - Atomic transactions in SQLite.
  - 20+ comprehensive pytest tests running against SQLite and verified real output.
* **Stage 2 (Data Ownership Tools)**:
  - Implement `teach_item_alias`, `set_item_price`, `add_catalog_item`, `add_customer`.
  - Pytest tests covering voice price changes, alias teaching, customer addition, idempotency.
* **Stage 3 (Protocol Conformance & Benchmarking)**:
  - Wire up `MCPServer` with `/mcp` Streamable HTTP, `/healthz`, `/ledger` fallback dashboard, and optional `/reset`.
  - Run MCP client over Streamable HTTP; verify `initialize`, `tools/list`, `tools/call`.
  - Measure tool latency over 50 calls; calculate and report real p50/p95 latency.
* **Stage 4 (Deployment Configuration)**:
  - Pinned `requirements.txt`, Render `render.yaml` configuration, `.gitignore`, MIT `LICENSE`, `README.md`, verified `addon.json`.
* **Stage 5 (MCP Apps Khata Widget)**:
  - Build self-contained HTML widget `ui://khata-card` with postMessage handshake, light/dark mode, customer highlighting, itemized receipts.
* **Stage 6 (Submission Documentation)**:
  - `README.md` with architecture diagram, `FRICTION_LOG.md` with real issues encountered, `PRODUCT_FEEDBACK.md`, and `DEMO_SCRIPT.md` under 3 minutes.

---

## 4. Intent Lexicon & Native Tamil Review Matrix

All Tamil script entries seeded into the database `intent_lexicon` table are flagged with `# NEEDS_NATIVE_REVIEW` to allow local Tamil-speaking kirana shopkeepers to validate dialect variations and colloquial spoken forms.

| Word / Phrase | Script / Lang | Event Type | Weight | Status & Notes |
| :--- | :---: | :---: | :---: | :--- |
| `கடன்` (Kadan) | Tamil (`ta`) | `CREDIT_SALE` | 1.0 | `# NEEDS_NATIVE_REVIEW` — Standard literary/spoken term for credit/loan. |
| `பாக்கி` (Baakki) | Tamil (`ta`) | `CREDIT_SALE` | 0.8 | `# NEEDS_NATIVE_REVIEW` — Colloquial term meaning remaining balance or tab. |
| `கணக்கு` (Kanakku) | Tamil (`ta`) | `CREDIT_SALE` | 1.0 | `# NEEDS_NATIVE_REVIEW` — Spoken shorthand for "put on my account" (*kanakkula*). |
| `எழுதிக்கோ` (Ezhudhiko) | Tamil (`ta`) | `CREDIT_SALE` | 1.0 | `# NEEDS_NATIVE_REVIEW` — Informal command: "write it down". |
| `எழுதிக்கொள்ளுங்கள்` | Tamil (`ta`) | `CREDIT_SALE` | 1.0 | `# NEEDS_NATIVE_REVIEW` — Polite honorific form: "please write it down". |
| `பணம்` (Panam) | Tamil (`ta`) | `CASH_SALE` | 1.0 | `# NEEDS_NATIVE_REVIEW` — Common noun for cash/money. |
| `காசு` (Kaasu) | Tamil (`ta`) | `CASH_SALE` | 1.0 | `# NEEDS_NATIVE_REVIEW` — Colloquial term for coins/cash payment. |
| `ரூபாய்` (Roobai) | Tamil (`ta`) | `CASH_SALE` | 0.7 | `# NEEDS_NATIVE_REVIEW` — Currency unit (Rupees); denotes cash value context. |
| `கொடுத்தார்` (Koduthaar) | Tamil (`ta`) | `PAYMENT_RECEIVED` | 1.0 | `# NEEDS_NATIVE_REVIEW` — Honorific past tense: "he/she gave [money]". |
| `செலுத்தினார்` (Seluthinaar) | Tamil (`ta`) | `PAYMENT_RECEIVED` | 1.0 | `# NEEDS_NATIVE_REVIEW` — Formal verb: "paid/settled". |
| `தீர்த்தார்` (Theerthaar) | Tamil (`ta`) | `PAYMENT_RECEIVED` | 1.0 | `# NEEDS_NATIVE_REVIEW` — Colloquial: "cleared the debt". |
| `திரும்ப` (Thirumba) | Tamil (`ta`) | `RETURN` | 1.0 | `# NEEDS_NATIVE_REVIEW` — Adverb: "back / return". |
| `திருப்பி` (Thiruppi) | Tamil (`ta`) | `RETURN` | 1.0 | `# NEEDS_NATIVE_REVIEW` — Verb participle: "returned / handed back". |
| `சரக்கு` (Sarakku) | Tamil (`ta`) | `STOCK_PURCHASE` | 1.0 | `# NEEDS_NATIVE_REVIEW` — Universal commercial term for stock / goods. |
| `மொத்த கொள்முதல்` | Tamil (`ta`) | `STOCK_PURCHASE` | 1.0 | `# NEEDS_NATIVE_REVIEW` — Wholesale procurement. |

### Classification Architecture & Rules
1. **No Customer Mentioned**:
   - If items are recognized $\rightarrow$ default to `CASH_SALE`.
   - Spoken feedback: "Cash sale of ₹[amount] logged."
2. **Customer + Amount + Payment Cue (No Items)**:
   - Matches `PAYMENT_RECEIVED`.
   - Spoken feedback: "Payment of ₹[amount] received from [customer]." (NEVER speaks new balance).
3. **Customer + Items + No Cues**:
   - Query `customer_habit`:
     - If customer has $\ge 3$ confirmations and $\ge 80\%$ dominance for `CREDIT_SALE` or `CASH_SALE`, auto-classify.
     - Otherwise, disambiguate with ONE short question: *"Should I put this on [Customer]'s account or was it paid in cash?"* and write **0 rows** until confirmed.
4. **Conflicting Cues**:
   - If conflicting cues detected in utterance (e.g. "cash" and "udhaar"), write **0 rows** and ask clarifying question.
5. **Multi-Item / Multi-Event Atomic Batch**:
   - Process multiple items atomically. If any item is ambiguous, roll back entirely and ask.
6. **Strict Discretion**:
   - NEVER read out customer balances, outstanding amounts, or debt warnings over audio in receipt confirmation. Balance is spoken ONLY if shopkeeper explicitly asks via `ask_khata(question="what is Ramesh balance", kind="balance")`.

