---
title: Namma Kanakku
emoji: 🏪
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# Namma-Kanakku (நம்ம கணக்கு) 🏪🎙️

> **"A voice khata that learns your shop's language, keeps your customers' debts private, and never guesses with money."**
> 
> *"உங்கள் கடையின் மொழியைப் பேசும், வாடிக்கையாளரின் மரியாதையைக் காக்கும் நவீன குரல் கணக்கு."*
> 
> *Submitted to the Alexa+ track of the "Build, Ship, Shape: Amazon Developer Hackathon 2026" (Code Engine: KiranaFlow).*

---

## 💡 The Problem & The Idea

Millions of neighbourhood kirana and maligai shopkeepers across India manage daily credit (*khata* / *கடன் நோட்டு*) for regular customers on loose paper notebooks. In the rush of a busy counter with hands full weighing dal or measuring oil:
1. **Speech is naturally multilingual**: Regulars order in mixed English, Tamil, and Tanglish (*"Karthik 3B ku rendu thayir and oru kadala ennai, udhaar"*).
2. **Debts are deeply sensitive**: Announcing a customer's total unpaid debt or over-limit warning aloud in earshot of other customers destroys trust and customer dignity.
3. **Accuracy is non-negotiable**: A software assistant cannot guess with inventory or customer debt.

**Namma-Kanakku** solves this with a privacy-first, deterministic Model Context Protocol (MCP) server connected to Alexa+, paired with a pure ASGI Counter Screen.

---

## 🏛️ Architecture Truth

```
 ┌─────────────────────────────────────────────────────────────┐
 │                  Alexa+ (Speech & Language)                 │
 │  • Speech-to-text (English, Tamil words, Tanglish)          │
 │  • Intent classification & slot extraction                  │
 │  • Calls Namma-Kanakku MCP tools over Streamable HTTP (/mcp)│
 └──────────────────────────────┬──────────────────────────────┘
                                │ JSON-RPC 2.0 (Streamable HTTP)
 ┌──────────────────────────────▼──────────────────────────────┐
 │             Namma-Kanakku MCP Server & Counter Engine       │
 │  NO External LLMs • 100% Deterministic Arithmetic & Privacy │
 │                                                             │
 │  1. Human Front-Door MCP Tools:                             │
 │     • write_entry: Single-turn or batch entry (Credit,      │
 │       Cash, Payment, Return, Stock Purchase)                │
 │     • fix_entry: Reversible undo & amend (restores balance, │
 │       stock deltas, and last payment date)                  │
 │     • ask_khata: Discreet balance & credit checks, daily    │
 │       profit summaries, low stock warnings                  │
 │     • update_shop: Teach shop vocabulary, prices, inventory │
 │                                                             │
 │  2. Data-Driven Intent Classification & Customer Habits:    │
 │     • Intent Lexicon (English, Tanglish, Tamil script)      │
 │     • Habit Promotion (>= 3 confirms, >= 80% dominance)     │
 │     • Conflict detection (0 rows saved on ambiguity)        │
 │                                                             │
 │  3. Dual-Channel Presentation:                              │
 │     • What Counter Hears: Audible spoken readback           │
 │     • What Shopkeeper Sees: Confidential screen notes       │
 │                                                             │
 │  4. Inventory & Gross Profit Math:                          │
 │     • Stock deltas & wholesale cost tracking per item       │
 │                                                             │
 │  5. Pure ASGI Counter Screen at / & Widget ui://khata-card  │
 └──────────────────────────────┬──────────────────────────────┘
                                │
 ┌──────────────────────────────▼──────────────────────────────┐
 │             Local SQLite Database (`kirana.db`)             │
 │  • customers  • catalog_items (stock, cost, reorder)        │
 │  • item_aliases  • intent_lexicon  • customer_habit         │
 │  • learned_aliases  • ledger_entries (seq PK, stock_delta)  │
 └─────────────────────────────────────────────────────────────┘
```

- **Alexa+ is the language model**: It understands spoken speech, handles mixed Tanglish, and passes structured inputs.
- **Namma-Kanakku contains NO LLM in the accounting path**: It executes deterministic row matching, atomic ledger updates, stock management, and discretion rules, returning structured data plus a discreet `spoken_summary` and `screen_note`.

---

## 🛡️ Product Acceptance Rules & Features

| Rule | Implementation Details |
| :--- | :--- |
| **Strict Discretion** | Spoken readback for credit sales, cash sales, payments, returns, and undo **never** reveals customer balances or debt warnings. Customer balance is spoken **only** when the shopkeeper explicitly queries via `ask_khata(kind="balance")`. |
| **Quiet Credit Check** | When evaluating customer credit (`ask_khata(kind="credit_check")`), Alexa speaks **strictly** *"Okay"* (if approved) or *"Please check the screen"* (if overdue or over limit). The customer's debt is never broadcast aloud. |
| **Atomic Writes** | If any item or event in a multi-item batch fails to resolve, **zero rows** are written to the database. |
| **Data-Driven Habits** | Customers with established habits ($\ge 3$ confirms, $\ge 80\%$ dominance) are automatically routed without manual button presses. Ambiguous entries ask ONE short question and save 0 rows. |
| **Reversible Undo & Amend** | Undoes entries strictly by sequential autoincrement ID (`seq DESC`), never timestamps. Restores previous balance, last payment date, and exact inventory stock deltas. |
| **Wholesale Profit Math** | Tracks retail price vs wholesale cost. `ask_khata(kind="today_summary")` reports cash sales, credit sales, collections, and estimated gross profit. |
| **Voice Data-Ownership** | Shopkeepers can teach custom dialect aliases (`"pasu thayir means curd 500ml"`), set prices, register customers, and update stock. |
| **Cold-Start Resilience** | Seeded with labelled fake demo data (`[DEMO DATA - NOT REAL]`). Re-seeds idempotently on startup. |

---

## ⚡ Deterministic Matching Pipeline

1. **Exact Alias Match**: Normalized text match against catalog aliases (Unicode Tamil script is transliterated to Latin first: e.g. `தயிர்` $\rightarrow$ `thayir`).
2. **Phonetic Key Match**: Normalizes spelling variants by collapsing `th/t`, `dh/d`, `aa/a`, `ee/i`, `oo/u`, `zh/l`, `w/v`, and double letters (e.g., `thoovaram paruppu` $\rightarrow$ `Toor Dal`).
3. **Learned Aliases**: If an ambiguous or custom word is confirmed $\ge 2$ times (and at least $2\times$ over any alternative), it auto-resolves with *"I understood X as Y"*.
4. **Fuzzy Match (Rapidfuzz WRatio)**: Accepts only if `score >= 90`, maps to a unique SKU, and score gap to runner-up is $\ge 8$.
5. **English Guess Fallback**: Runs the pipeline on Alexa+'s `english_guess` if the spoken word was unlisted.
6. **Disambiguation Safety**: Generic words (`oil`, `dal`, `soap`, `rice`) return `NEEDS_CLARIFICATION` with candidate options. Never silently guesses with money.

---

## 🚀 Quickstart: Local Run for Judges

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.13)
- Git

### 2. Install Dependencies
```bash
git clone https://github.com/monishchandran2007-hub/Namma-Kanakku.git
cd Namma-Kanakku
pip install -r requirements.txt
```

### 3. Run Automated Verification Suite
```bash
pytest -v
```
*(Runs 74 comprehensive automated tests verifying discretion, atomicity, intent lexicon, customer habits, undo/amend, profit calculations, and Counter Screen contracts.)*

### 4. Start the MCP Server & Counter Screen
```bash
python server.py
```
The server will start on `http://127.0.0.1:7860`:
- **Counter Screen**: `http://127.0.0.1:7860/` (pure ASGI, zero Gradio, responsive tablet UI with microphone support)
- **Streamable HTTP MCP Endpoint**: `http://127.0.0.1:7860/mcp`
- **MCP Apps Widget Preview**: `http://127.0.0.1:7860/widget` (previews `ui://khata-card` in light/dark mode)
- **Real-Time State Polling API**: `http://127.0.0.1:7860/api/state`
- **Fallback Live Ledger Dashboard**: `http://127.0.0.1:7860/ledger`
- **Health Check**: `http://127.0.0.1:7860/healthz`

### 5. Run Smoke Test & Latency Benchmark
In a separate terminal:
```bash
python smoke_test.py
```
*Outputs JSON-RPC validation, tool list discovery, widget retrieval (`ui://khata-card`), and real 50-call latency benchmark.*

---

## 📚 Submission Documentation

- 🛠️ [NOTES.md](file:///d:/Amazon%20aws/NOTES.md): Architecture research, official API citations, VERIFY matrix, and Tamil Intent Lexicon table marked `# NEEDS_NATIVE_REVIEW`.
- ⚠️ [FRICTION_LOG.md](file:///d:/Amazon%20aws/FRICTION_LOG.md): Authentic developer friction log covering Python MCP SDK 2.x migration, Gradio SPA shadowing, Windows terminal encoding, and partner preview gating.
- 💡 [PRODUCT_FEEDBACK.md](file:///d:/Amazon%20aws/PRODUCT_FEEDBACK.md): Constructive feedback on the MCP Python SDK, Streamable HTTP transport, UI metadata rendering, and Alexa+ multilingual tools.
- 🎬 [DEMO_SCRIPT.md](file:///d:/Amazon%20aws/DEMO_SCRIPT.md): Complete 3-minute video submission script with 30s hook, Tanglish voice scenes, quiet credit check demonstration, and profit reporting.
- 📜 [TERMS.md](file:///d:/Amazon%20aws/TERMS.md) & [PRIVACY.md](file:///d:/Amazon%20aws/PRIVACY.md): Terms of service and privacy policy ensuring shopkeeper local data ownership.

---

## 📋 Labelled Demo Data Notice

> **[DEMO DATA - NOT REAL]**
> All customer records (e.g., Ramesh Teacher, Priya Madam), phone numbers (`9800000001` - `9800000005`), and item balances are strictly simulated test fixtures created solely for hackathon demonstration.

---

## 📄 License

This project is licensed under the [MIT License](file:///d:/Amazon%20aws/LICENSE).
