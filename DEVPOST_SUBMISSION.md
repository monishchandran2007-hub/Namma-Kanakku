# Devpost Hackathon Submission: Namma-Kanakku (நம்ம கணக்கு)

**Submission Title**: Namma-Kanakku (நம்ம கணக்கு): Voice Khata for Neighbourhood Shops  
**Elevator Pitch**: A voice khata that learns each shop's language, keeps customers' debts private, and never guesses with money.  
**Track**: Alexa+ Track — Build, Ship, Shape: Amazon Developer Hackathon 2026  
**GitHub Repository**: `https://github.com/monishchandran2007-hub/Namma-Kanakku`  
**Live Deployment / Counter Screen**: `https://nnnneek123-namma-kanakku.hf.space`  

---

### 💡 Inspiration & The Real Problem

At a busy Indian neighbourhood kirana or maligai counter, the shopkeeper's hands are full: weighing dal, pouring oil, counting cash, and handing out change. When a regular customer says *"kanakkula ezhuthikonga"* (write it on my account), writing it in a mobile app requires wiping dusty hands, unlocking a smartphone, searching the name, and typing. Entries get postponed, and small debts get forgotten.

During our shopkeeper interviews, one shopkeeper shared a fundamental insight:
> *"Enga kadaila kai eppavum ennaiyum paruppuma irukkum. Customer kitta balance-ah sathama solla koodadhu. Voice-la solli screen-la paatha dhaan mariyaadhai."*  
> *(In our shop, hands are always covered in oil and dal. We must never shout a customer's balance aloud. Speaking it by voice and seeing it on screen is what keeps respect.)*

Existing voice assistants are built to be helpful by speaking everything aloud: *"Ramesh has an unpaid balance of 3,450 rupees and is over his limit."* In a crowded shop, shouting a customer's debt destroys trust and damages customer dignity. Furthermore, ordinary voice skills either invent prices or break when spoken to in everyday Tanglish (*"Karthik 3B ku rendu thayir and oru kadala ennai, udhaar"*).

We built **Namma-Kanakku** to fix all of this.

---

### 🏪 What It Does

Namma-Kanakku connects to Alexa+ via the official Model Context Protocol (MCP) using modern Streamable HTTP. It delivers a privacy-first, deterministic accounting assistant paired with a real-time Counter Screen:

1. **Understands Natural Multilingual Speech**:
   Shopkeepers speak in natural English, Tamil words, or Tanglish:
   *"Karthik 3B ku rendu thayir and oru kadala ennai, udhaar."*
   Alexa+ extracts the slots, and Namma-Kanakku automatically scores cues via an `intent_lexicon` (English, Tanglish, and Tamil script) to classify the event as a credit sale, cash sale, payment, return, or stock purchase.

2. **Strict Discretion & Dual-Channel Privacy**:
   - **What Counter Hears**: Audible readback confirms only the items and amount (*"Logged 2 packet Curd 500ml, 1 packet Groundnut Oil 1L for Karthik 3B, total 260 rupees. Say undo if that's wrong."*). It NEVER speaks customer balances or debt warnings aloud.
   - **What Shopkeeper Sees**: Overdue warnings (e.g. *"Unpaid for 35 days"*), credit limit breaches, and wholesale profit margins appear strictly on the shopkeeper's confidential screen.

3. **Quiet Credit Check**:
   When a shopkeeper checks if an overdue customer can take more goods on credit (*"credit check for Ramesh Teacher"*), Alexa speaks **strictly** *"Okay"* (if approved) or *"Please check the screen"* (if overdue or over limit). The customer's debt is never broadcast aloud.

4. **Data-Driven Habits**:
   For regular customers without explicit payment cues, Namma-Kanakku checks `customer_habit`. If the customer has $\ge 3$ confirmations and $\ge 80\%$ dominance, it auto-classifies without manual button presses. If ambiguous, it asks ONE short question (*"Should I put this on Ramesh's account or was it paid in cash?"*) and writes **zero rows** until confirmed.

5. **Multi-Item Batch Atomicity & Reversible Undo**:
   If any item in a multi-item batch is unrecognized or requires clarification, **zero rows** are written. On *"Aiyyo thappu, undo pannu!"*, the engine rolls back strictly by sequential ID (`seq DESC`), restoring previous customer balance, last payment date, and exact physical inventory stock deltas.

6. **Wholesale Profit & Inventory Tracking**:
   Tracks retail prices against wholesale costs. Asking *"today's summary"* calculates cash sales, credit sales, payments collected, and estimated gross profit.

7. **Voice Data-Ownership**:
   Shopkeepers can teach custom dialect words (*"Remember pasu thayir means Curd 500ml"*), update prices, add products, or register new customers.

---

### 🛠️ How We Built It

- **Language Intelligence**: Alexa+ handles automatic speech recognition, multilingual translation, and slot extraction.
- **MCP Protocol**: Built on the official Python MCP SDK (`mcp==2.3.0`) implementing the **Streamable HTTP** transport at `/mcp`.
- **Accounting & Ledger Engine**: Built in pure Python (`engine.py`, `ledger.py`, `matching.py`) with 100% deterministic arithmetic in SQLite (`kirana.db`). There are **NO external LLMs** in the financial calculation path.
- **Deterministic 6-Step Matching**: Exact alias $\rightarrow$ phonetic key collapsing $\rightarrow$ learned aliases $\rightarrow$ Rapidfuzz WRatio ($\ge 90$, gap $\ge 8$) $\rightarrow$ English guess fallback $\rightarrow$ disambiguation safety.
- **Pure ASGI Counter Screen**: Served by Starlette/Uvicorn at `/` (zero Gradio, zero dev terms like "tab 1" or "Run:"). Features 2-second real-time polling (`/api/state`) and Web Speech API microphone input.
- **MCP Apps Khata Card**: Interactive card widget (`widget.html`) implementing the official postMessage lifecycle (`ui/initialize`, `ui/notifications/tool-input`) served at `ui://khata-card` and previewable at `/widget`.

---

### 🧗 Challenges We Ran Into (See FRICTION_LOG.md)

1. **Python MCP SDK 2.x Architecture Shift**: The SDK refactored `FastMCP` into `MCPServer` in `mcp.server.mcpserver`. We adapted our entire server to the new specification.
2. **Gradio SPA Catch-All Shadowing**: Gradio's internal catch-all router captured sub-mounted routes (`/widget`, `/ledger`, `/healthz`). We eliminated Gradio entirely, switching to `sdk: docker` with a pure Starlette ASGI server.
3. **Windows Terminal Unicode Encoding**: PowerShell and CMD default to `cp1252`, crashing on Tamil Unicode script. We built deterministic phonetic Latin normalization pipelines.
4. **Multi-Item Batch Atomicity**: Prevented partial database corruption by implementing strict two-phase atomic validation and serializing reversible `stock_delta_json`.

All authentic bugs, stack traces, and workarounds are documented in our [FRICTION_LOG.md](file:///d:/Amazon%20aws/FRICTION_LOG.md).

---

### 🏆 Accomplishments That We're Proud Of

- **74 Passing Automated Unit Tests**: Comprehensive test suites (`test_stage1.py`, `test_stage2.py`, `test_stage5.py`, `test_stage8.py`, `test_stage10.py`) verifying discretion, atomicity, habit learning, inventory rollback, and contract rules.
- **Sub-15ms Latency**: Verified median latency (p50) of **12.92 ms** and 95th percentile (p95) of **21.86 ms** over 50 sequential MCP tool calls.
- **Zero Hallucination Guarantee**: Complete decoupling of language understanding (Alexa+) from ledger execution (local SQLite).
- **Dual-Channel Human Experience**: Transforming an accounting chore into an interface that protects customer dignity and empowers busy shopkeepers.

---

### 📖 What We Learned

We learned that in voice computing, what you *don't* say is just as important as what you do say. In retail POS software, privacy cannot be an afterthought; it must be an architectural hard boundary enforced at the protocol level.

---

### 🚀 What's Next for Namma-Kanakku

1. Direct integration with UPI QR payment generation on the Counter Screen when a customer settles dues.
2. WhatsApp / SMS payment receipts sent quietly to regular customers upon credit logging.
3. Expanded support for Kannada, Telugu, and Malayalam dialect lexicons.
