---
title: Namma Kanakku
emoji: 🏪
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 5.20.0
app_file: app.py
python_version: '3.11'
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

Millions of neighbourhood kirana and maligai shopkeepers across India manage daily credit (*khata* / *கடன் நோட்டு*) for regular customers on loose paper notebooks. In the rush of a counter with customers waiting:
1. **Speech is naturally multilingual**: Customers order in mixed English, Tamil, and Tanglish (*"thayir"*, *"half kilo thuvaram paruppu"*, *"kadala ennai"*, *"arisi"*).
2. **Debts are deeply sensitive**: Announcing a customer's total unpaid debt or over-limit warning aloud in earshot of other customers destroys trust and damages dignity.
3. **Accuracy is non-negotiable**: A software assistant cannot "hallucinate" or guess with pricing or customer debt.

**Namma-Kanakku** solves this with a privacy-first, deterministic Model Context Protocol (MCP) server connected to Alexa+.

---

## 🏛️ Architecture Truth

```
 ┌─────────────────────────────────────────────────────────────┐
 │                  Alexa+ (Speech & Language)                 │
 │  • Speech-to-text (English, Tamil words, Tanglish)          │
 │  • Multilingual translation & slot extraction               │
 │  • Calls KiranaFlow MCP tools over Streamable HTTP (/mcp)   │
 └──────────────────────────────┬──────────────────────────────┘
                                │ JSON-RPC 2.0 (Streamable HTTP)
 ┌──────────────────────────────▼──────────────────────────────┐
 │             KiranaFlow MCP Server (Python 3.10+)            │
 │  NO LLMs • NO External APIs • 100% Deterministic & Private  │
 │                                                             │
 │  1. Deterministic 6-Step Matching Pipeline:                 │
 │     Exact -> Phonetic -> Learned -> Rapidfuzz -> English    │
 │  2. Strict Discretion Rules:                                │
 │     Balances spoken ONLY in get_customer_balance            │
 │  3. Atomic Ledger Engine & Reversible Autoincrement Undo   │
 │  4. SQLite Persistence with Idempotent Demo Seeder          │
 │  5. MCP Apps Widget (`ui://khata-card`) + Screen Fallback   │
 └──────────────────────────────┬──────────────────────────────┘
                                │
 ┌──────────────────────────────▼──────────────────────────────┐
 │             Local SQLite Database (`kirana.db`)             │
 │  • customers  • catalog_items  • item_aliases               │
 │  • learned_aliases  • ledger_entries (seq PK)               │
 └─────────────────────────────────────────────────────────────┘
```

- **Alexa+ is the language model**: It understands spoken speech, handles mixed Tanglish, and passes structured inputs (`item_name`, `quantity`, `unit`, `english_guess`, `original_spoken`).
- **KiranaFlow contains NO LLM**: It executes arithmetic, deterministic row matching, atomic ledger updates, and discretion rules, returning structured data plus a discreet `spoken_summary` and `screen_note`.

---

## 🛡️ Product Acceptance Rules & Features

| Rule | Implementation Details |
| :--- | :--- |
| **Strict Discretion** | `spoken_summary` for credit logs, payments, undos, and overdue accounts **never** mentions customer balances or limit statuses. Balance is spoken **only** when the shopkeeper explicitly asks via `get_customer_balance`. |
| **Atomic Writes** | If any customer or item requires clarification or is unrecognized, **zero** rows are written to the database. |
| **Spoken Read-Back** | Every successful entry confirms itemized totals followed by the safety prompt: *"Say undo if that's wrong."* |
| **Reversible Undo** | Undoes credits or payments strictly by sequential autoincrement ID (`seq DESC`), never by clock timestamp. Restores customer balances and original payment dates. |
| **Overdue Nudge** | When logging for a customer unpaid for 30+ days, adds a discreet visual `screen_note` suggesting a reminder (never spoken aloud). |
| **Voice Data-Ownership** | Shopkeeper can teach custom aliases (`teach_item_alias`), update prices (`set_item_price`), add items (`add_catalog_item`), and register customers (`add_customer`). |
| **Cold-Start Resilience** | Seeded with labelled fake demo data (`[DEMO DATA - NOT REAL]`). Re-seeds idempotently on startup so free-tier cloud sleep resets remain testable. |

---

## ⚡ 6-Step Deterministic Matching Pipeline

1. **Exact Alias Match**: Normalized text match against catalog aliases (Unicode Tamil script is transliterated to Latin first: e.g. `தயிர்` $\rightarrow$ `thayir`).
2. **Phonetic Key Match**: Normalizes spelling variants by collapsing `th/t`, `dh/d`, `aa/a`, `ee/i`, `oo/u`, `zh/l`, `w/v`, and double letters (e.g., `thoovaram paruppu` $\rightarrow$ `Toor Dal`).
3. **Learned Aliases**: If an ambiguous or custom word is confirmed $\ge 2$ times (and at least $2\times$ over any alternative), it auto-resolves with *"I understood X as Y"*.
4. **Fuzzy Match (Rapidfuzz WRatio)**: Accepts only if `score >= 90`, maps to a unique SKU, and score gap to runner-up is $\ge 8$.
5. **English Guess Fallback**: Runs the pipeline on Alexa+'s `english_guess` if the spoken word was unlisted.
6. **Disambiguation Safety**: Generic words (`oil`, `dal`, `soap`, `rice`) return `NEEDS_CLARIFICATION` with up to 3 candidate options. Never silently guesses.

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
*(Runs 36 comprehensive automated tests verifying discretion, atomicity, matching, data-ownership, and MCP Apps widget contracts.)*

### 4. Start the MCP Server
```bash
python server.py
```
The server will start on `http://127.0.0.1:8000`:
- **Streamable HTTP MCP Endpoint**: `http://127.0.0.1:8000/mcp`
- **Fallback Live Ledger Dashboard**: `http://127.0.0.1:8000/ledger` (auto-refreshes every 5 seconds)
- **MCP Apps Widget Inspector**: `http://127.0.0.1:8000/widget` (previews `ui://khata-card` in light/dark mode)
- **Health Check**: `http://127.0.0.1:8000/healthz`

### 5. Run Smoke Test & Latency Benchmark
In a separate terminal:
```bash
python smoke_test.py
```
*Outputs JSON-RPC validation, tool list discovery (10 tools), widget retrieval (`ui://khata-card`), and real 50-call latency benchmark:*
- **p50 (median)**: **12.92 ms**
- **p95**: **21.86 ms**
- **Average**: **14.63 ms**

---

## 📚 Submission Documentation

- 🛠️ [NOTES.md](file:///d:/Amazon%20aws/NOTES.md): Architecture research, official API citations, and VERIFY matrix.
- ⚠️ [FRICTION_LOG.md](file:///d:/Amazon%20aws/FRICTION_LOG.md): Authentic developer friction log covering Python MCP SDK 2.x migration, Windows terminal encoding, and partner preview gating.
- 💡 [PRODUCT_FEEDBACK.md](file:///d:/Amazon%20aws/PRODUCT_FEEDBACK.md): Constructive feedback on the MCP Python SDK, Starlette ASGI layer, and Alexa+ multilingual tools.
- 🎬 [DEMO_SCRIPT.md](file:///d:/Amazon%20aws/DEMO_SCRIPT.md): Complete 3-minute video submission script with 30s hook, Tanglish voice scenes, discretion rule demonstration, and shopkeeper perspective.

---

## ☁️ Deployment Guide (Render Free Tier)

Deploy as a **Free Web Service** on [Render](https://render.com) (no credit card required):

| Setting | Value |
| :--- | :--- |
| **Environment** | `Python` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `python server.py` |
| **Health Check Path** | `/healthz` |
| **Environment Variables** | `PORT=10000`, `PYTHONUNBUFFERED=1`, `RESET_KEY=<optional-secret>` |

A ready-to-use [render.yaml](file:///d:/Amazon%20aws/render.yaml) blueprint is included in this repository.

---

## 📋 Labelled Demo Data Notice

> **[DEMO DATA - NOT REAL]**
> All customer records (e.g., Ramesh Teacher, Priya Madam), phone numbers (`9800000001` - `9800000005`), and item balances are strictly simulated test fixtures created solely for hackathon demonstration.

---

## 📄 License

This project is licensed under the [MIT License](file:///d:/Amazon%20aws/LICENSE).
