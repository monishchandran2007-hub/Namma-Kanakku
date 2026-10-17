"""
server.py - Streamable HTTP MCP Server & Pure ASGI Counter Screen for Namma-Kanakku.

Features:
- Official MCP Python SDK 2025-11-25+ Streamable HTTP transport served at /mcp.
- Pure ASGI Counter Screen at / (zero Gradio, zero dev terms like "tab", "Run:", or tool names).
- Dual-channel presentation: Spoken Audio Readback vs Confidential Screen Notes.
- Front-Door MCP Tools:
  1. write_entry: Single-turn or batch entry (CREDIT_SALE, CASH_SALE, PAYMENT, RETURN, STOCK).
  2. fix_entry: Reversible undo and amendment (restores balance, stock deltas, last payment date).
  3. ask_khata: Discretion queries ('balance', 'credit_check', 'morning_brief', 'today_summary', 'overdue', 'low_stock').
  4. update_shop: Catalog and language configuration (teach alias, set price, add item, add customer, set stock/cost).
- Backwards-compatible legacy wrappers for all 9 earlier tools.
- Auxiliary plain HTTP endpoints:
  - /api/state: JSON polling endpoint for live ledger, customer dues, inventory, and stats.
  - /api/command: Natural language voice/text command executor for counter screen.
  - /widget: Self-contained MCP Apps Khata Card widget (ui://khata-card).
  - /ledger: Plain HTML fallback ledger.
  - /healthz: Health check JSON.
  - /reset: Demo reset endpoint.
"""

import os
import json
import sqlite3
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field

from mcp.server.mcpserver import MCPServer
from starlette.responses import JSONResponse, HTMLResponse, RedirectResponse
from starlette.requests import Request

from database import get_connection, seed_demo_data, DEFAULT_DB_PATH
import ledger
import data_ownership
import engine

# Ensure database is initialized with labelled demo data on startup
seed_demo_data(force=False)

# Global version counter for state polling
_STATE_VERSION = 1

def increment_state_version():
    global _STATE_VERSION
    _STATE_VERSION += 1
    return _STATE_VERSION

# Initialize MCPServer
mcp_server = MCPServer(
    name="Namma-Kanakku",
    version="2.0.0",
    description="A voice khata that learns each shop's language, keeps customers' debts private, and never guesses with money."
)

# Pydantic Schemas for Tools
class ItemInput(BaseModel):
    item_name: str = Field(description="Spoken name of the item in English, Tanglish, or Tamil script (e.g. 'toor dal', 'thayir', 'sunflower oil', 'தயிர்')")
    quantity: Union[float, int, str] = Field(default=1.0, description="Quantity. For loose items by weight, specify in kg or grams (e.g. 0.5, 'half kilo', '250g').")
    unit: Optional[str] = Field(default=None, description="Optional unit (e.g., 'kg', 'g', 'packet', 'piece', 'bunch').")
    english_guess: Optional[str] = Field(default=None, description="Optional English translation guess provided by Alexa+ if word is Tamil/Tanglish/Hindi.")
    original_spoken: Optional[str] = Field(default=None, description="Original ambiguous word when answering a clarification, used to record a learned alias.")

class EventInput(BaseModel):
    event_type: Optional[str] = Field(default=None, description="Optional event type: CREDIT_SALE, CASH_SALE, PAYMENT_RECEIVED, RETURN, STOCK_PURCHASE")
    customer_name: Optional[str] = Field(default=None, description="Name of the customer (optional for cash sales / stock purchases)")
    items: Optional[List[ItemInput]] = Field(default=None, description="List of items in this event")
    amount: Optional[float] = Field(default=None, description="Total amount or payment amount")
    payment_mode: Optional[str] = Field(default=None, description="CASH, UPI, or CREDIT")
    utterance: Optional[str] = Field(default=None, description="Spoken utterance text")

# ============================================================================
# 1. FRONT-DOOR MCP TOOLS (HUMAN-CENTRIC INTERFACE)
# ============================================================================

@mcp_server.tool(
    name="write_entry",
    description=(
        "Log a credit sale, cash sale, payment, return, or wholesale stock purchase in one step. "
        "Automatically classifies natural kirana speech in English, Tanglish, and Tamil script. "
        "Strictly atomic: saves nothing unless all items resolve. "
        "Discretion: Never announces customer balance or debt warnings aloud; only speaks items and total."
    ),
    meta={"ui": {"resourceUri": "ui://khata-card"}}
)
def write_entry(
    events: Optional[List[EventInput]] = None,
    utterance: Optional[str] = None,
    customer_name: Optional[str] = None,
    items: Optional[List[ItemInput]] = None,
    amount: Optional[float] = None,
    payment_mode: Optional[str] = None,
    event_type: Optional[str] = None
) -> Dict[str, Any]:
    events_dicts = [e.model_dump() for e in events] if events else None
    items_dicts = [it.model_dump() for it in items] if items else None
    res = engine.write_entry(
        events=events_dicts,
        utterance=utterance,
        customer_name=customer_name,
        items=items_dicts,
        amount=amount,
        payment_mode=payment_mode,
        event_type=event_type
    )
    if res.get("success"):
        increment_state_version()
    return res

@mcp_server.tool(
    name="fix_entry",
    description=(
        "Undo or amend recent ledger entries. "
        "Ordered strictly by sequential ID (never timestamps). "
        "Restores previous customer balance, last payment date, and inverts inventory stock deltas. "
        "Discretion: Confirms undo without speaking customer balance."
    ),
    meta={"ui": {"resourceUri": "ui://khata-card"}}
)
def fix_entry(
    action: str = "undo",
    customer_name: Optional[str] = None,
    amend_fields: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    res = engine.fix_entry(
        action=action,
        customer_name=customer_name,
        amend_fields=amend_fields
    )
    if res.get("success"):
        increment_state_version()
    return res

@mcp_server.tool(
    name="ask_khata",
    description=(
        "Query the khata with voice discretion: "
        "- 'balance': Speaks balance aloud (permitted on explicit request). "
        "- 'credit_check': Speaks ONLY 'Okay' or 'Please check the screen'; detailed warnings go to screen note. "
        "- 'morning_brief': Speaks count of overdue accounts; customer details go to screen note. "
        "- 'today_summary': Reports cash/credit sales, collections, and gross profit. "
        "- 'low_stock': Reports inventory items at or below reorder level."
    ),
    meta={"ui": {"resourceUri": "ui://khata-card"}}
)
def ask_khata(
    question: str,
    kind: Optional[str] = None,
    customer_name: Optional[str] = None,
    amount: Optional[float] = None
) -> Dict[str, Any]:
    return engine.ask_khata(
        question=question,
        kind=kind,
        customer_name=customer_name,
        amount=amount
    )

@mcp_server.tool(
    name="update_shop",
    description=(
        "Manage shop catalog and language vocabulary: "
        "teach local language aliases, set prices, add products, register customers, or update stock and wholesale costs."
    ),
    meta={"ui": {"resourceUri": "ui://khata-card"}}
)
def update_shop(
    action: str,
    alias: Optional[str] = None,
    item_name_or_sku: Optional[str] = None,
    new_price: Optional[float] = None,
    sku: Optional[str] = None,
    display_name: Optional[str] = None,
    price: Optional[float] = None,
    cost: Optional[float] = None,
    stock: Optional[float] = None,
    unit: str = "packet",
    is_loose: bool = False,
    aliases: Optional[List[str]] = None,
    customer_name: Optional[str] = None,
    phone: Optional[str] = None,
    credit_limit: float = 2000.0
) -> Dict[str, Any]:
    res = engine.update_shop(
        action=action,
        alias=alias,
        item_name_or_sku=item_name_or_sku,
        new_price=new_price,
        sku=sku,
        display_name=display_name,
        price=price,
        cost=cost,
        stock=stock,
        unit=unit,
        is_loose=is_loose,
        aliases=aliases,
        customer_name=customer_name,
        phone=phone,
        credit_limit=credit_limit
    )
    if res.get("success"):
        increment_state_version()
    return res


# ============================================================================
# 2. BACKWARDS-COMPATIBLE LEGACY TOOLS
# ============================================================================

@mcp_server.tool(name="log_credit_entry", description="Legacy wrapper for credit entries.", meta={"ui": {"resourceUri": "ui://khata-card"}})
def log_credit_entry(customer_name: str, items: List[ItemInput]) -> Dict[str, Any]:
    items_dicts = [it.model_dump() for it in items]
    res = ledger.log_credit_entry(customer_name, items_dicts)
    if res.get("success"):
        increment_state_version()
    return res

@mcp_server.tool(name="record_payment", description="Legacy wrapper for customer payment.", meta={"ui": {"resourceUri": "ui://khata-card"}})
def record_payment(customer_name: str, amount: float) -> Dict[str, Any]:
    res = ledger.record_payment(customer_name, amount)
    if res.get("success"):
        increment_state_version()
    return res

@mcp_server.tool(name="get_customer_balance", description="Legacy wrapper for checking customer balance.", meta={"ui": {"resourceUri": "ui://khata-card"}})
def get_customer_balance(customer_name: str) -> Dict[str, Any]:
    return ledger.get_customer_balance(customer_name)

@mcp_server.tool(name="undo_last_entry", description="Legacy wrapper for undo.", meta={"ui": {"resourceUri": "ui://khata-card"}})
def undo_last_entry(customer_name: Optional[str] = None) -> Dict[str, Any]:
    res = ledger.undo_last_entry(customer_name)
    if res.get("success"):
        increment_state_version()
    return res

@mcp_server.tool(name="get_overdue_accounts", description="Legacy wrapper for overdue accounts.", meta={"ui": {"resourceUri": "ui://khata-card"}})
def get_overdue_accounts() -> Dict[str, Any]:
    return ledger.get_overdue_accounts()

@mcp_server.tool(name="teach_item_alias", description="Legacy wrapper to teach alias.", meta={"ui": {"resourceUri": "ui://khata-card"}})
def teach_item_alias(alias: str, item_name_or_sku: str) -> Dict[str, Any]:
    res = data_ownership.teach_item_alias(alias, item_name_or_sku)
    if res.get("success"):
        increment_state_version()
    return res

@mcp_server.tool(name="set_item_price", description="Legacy wrapper to set price.", meta={"ui": {"resourceUri": "ui://khata-card"}})
def set_item_price(item_name_or_sku: str, new_price: float) -> Dict[str, Any]:
    res = data_ownership.set_item_price(item_name_or_sku, new_price)
    if res.get("success"):
        increment_state_version()
    return res

@mcp_server.tool(name="add_catalog_item", description="Legacy wrapper to add item.", meta={"ui": {"resourceUri": "ui://khata-card"}})
def add_catalog_item(sku: str, display_name: str, price: float, unit: str = "packet", is_loose: bool = False, aliases: Optional[List[str]] = None) -> Dict[str, Any]:
    res = data_ownership.add_catalog_item(sku, display_name, price, unit, is_loose, aliases)
    if res.get("success"):
        increment_state_version()
    return res

@mcp_server.tool(name="add_customer", description="Legacy wrapper to add customer.", meta={"ui": {"resourceUri": "ui://khata-card"}})
def add_customer(name: str, phone: Optional[str] = None, credit_limit: float = 2000.0) -> Dict[str, Any]:
    res = data_ownership.add_customer(name, phone, credit_limit)
    if res.get("success"):
        increment_state_version()
    return res

@mcp_server.tool(name="evaluate_wholesale_quote", description="Legacy wrapper to evaluate wholesale quote.")
def evaluate_wholesale_quote(item_name_or_sku: str, wholesale_price: float, quantity: float = 1.0) -> Dict[str, Any]:
    return data_ownership.evaluate_wholesale_quote(item_name_or_sku, wholesale_price, quantity)


# ============================================================================
# 3. MCP APPS RESOURCE (ui://khata-card)
# ============================================================================

WIDGET_FILE_PATH = os.path.join(os.path.dirname(__file__), "widget.html")

def load_widget_html() -> str:
    if os.path.exists(WIDGET_FILE_PATH):
        with open(WIDGET_FILE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "<!DOCTYPE html><html><body>Khata Card</body></html>"

@mcp_server.resource("ui://khata-card", mime_type="text/html")
def get_khata_card_widget() -> str:
    return load_widget_html()


# ============================================================================
# 4. HTTP API & COUNTER SCREEN HANDLERS
# ============================================================================

COUNTER_SCREEN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Namma-Kanakku (நம்ம கணக்கு) — Kirana Counter Screen</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-base: #090d16;
      --bg-panel: #111827;
      --bg-card: #1f2937;
      --bg-card-hover: #374151;
      --border-subtle: #374151;
      --text-main: #f9fafb;
      --text-muted: #9ca3af;
      --accent-primary: #0284c7;
      --accent-hover: #0369a1;
      --emerald: #10b981;
      --amber: #f59e0b;
      --rose: #f43f5e;
      --indigo: #6366f1;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Outfit', -apple-system, sans-serif;
      background: var(--bg-base);
      color: var(--text-main);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: rgba(17, 24, 39, 0.95);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border-subtle);
      padding: 12px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 50;
    }
    .brand-group { display: flex; align-items: center; gap: 12px; }
    .brand-icon { font-size: 1.8rem; }
    .brand-title { font-size: 1.25rem; font-weight: 800; color: #38bdf8; letter-spacing: -0.02em; }
    .brand-sub { font-size: 0.8rem; color: var(--text-muted); }
    .header-actions { display: flex; align-items: center; gap: 12px; }
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
      background: rgba(16, 185, 129, 0.15);
      color: var(--emerald);
      border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--emerald); animation: pulse 2s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(0.9); } }
    .btn-toggle {
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      color: var(--text-main);
      padding: 6px 14px;
      border-radius: 8px;
      font-size: 0.82rem;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s;
    }
    .btn-toggle:hover { background: var(--bg-card-hover); }
    .btn-toggle.active { background: #0369a1; border-color: #38bdf8; color: white; }

    /* Main Container */
    main {
      flex: 1;
      max-width: 1440px;
      width: 100%;
      margin: 0 auto;
      padding: 20px;
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 20px;
    }
    @media (max-width: 1024px) {
      main { grid-template-columns: 1fr; }
    }

    /* Left Column: Command & Dual-Channel */
    .left-col { display: flex; flex-direction: column; gap: 20px; }

    /* Command Bar */
    .command-box {
      background: var(--bg-panel);
      border: 1px solid var(--border-subtle);
      border-radius: 14px;
      padding: 16px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.25);
    }
    .input-row { display: flex; gap: 10px; margin-bottom: 12px; }
    .mic-btn {
      width: 52px;
      height: 52px;
      border-radius: 12px;
      border: 2px solid #0284c7;
      background: rgba(2, 132, 199, 0.15);
      color: #38bdf8;
      font-size: 1.5rem;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: all 0.2s;
      flex-shrink: 0;
    }
    .mic-btn:hover { background: #0284c7; color: white; }
    .mic-btn.listening {
      background: var(--rose);
      border-color: #fda4af;
      color: white;
      animation: mic-pulse 1.2s infinite;
    }
    @keyframes mic-pulse {
      0%, 100% { box-shadow: 0 0 0 0 rgba(244, 63, 94, 0.6); }
      50% { box-shadow: 0 0 0 12px rgba(244, 63, 94, 0); }
    }
    .cmd-input {
      flex: 1;
      background: var(--bg-base);
      border: 1px solid var(--border-subtle);
      border-radius: 12px;
      padding: 12px 16px;
      color: white;
      font-size: 1rem;
      font-family: inherit;
      outline: none;
      transition: border-color 0.15s;
    }
    .cmd-input:focus { border-color: #38bdf8; box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2); }
    .btn-send {
      padding: 0 20px;
      background: #0284c7;
      border: none;
      border-radius: 12px;
      color: white;
      font-weight: 700;
      font-size: 0.95rem;
      cursor: pointer;
      transition: background 0.15s;
    }
    .btn-send:hover { background: #0369a1; }
    .btn-undo-action {
      padding: 0 16px;
      background: rgba(244, 63, 94, 0.15);
      border: 1px solid rgba(244, 63, 94, 0.3);
      border-radius: 12px;
      color: #fda4af;
      font-weight: 600;
      font-size: 0.85rem;
      cursor: pointer;
    }
    .btn-undo-action:hover { background: var(--rose); color: white; }

    /* Action Chips */
    .chips-label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 8px; font-weight: 700; }
    .chips-grid { display: flex; flex-wrap: wrap; gap: 8px; }
    .chip {
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      color: #cbd5e1;
      padding: 6px 12px;
      border-radius: 20px;
      font-size: 0.8rem;
      cursor: pointer;
      transition: all 0.15s;
      user-select: none;
    }
    .chip:hover { background: var(--bg-card-hover); border-color: #64748b; color: white; transform: translateY(-1px); }

    /* Dual-Channel Box */
    .dual-channel-container {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .channel-card {
      border-radius: 14px;
      padding: 16px 20px;
      position: relative;
    }
    .channel-audio {
      background: linear-gradient(135deg, rgba(2, 132, 199, 0.15) 0%, rgba(30, 41, 59, 0.8) 100%);
      border: 1px solid rgba(56, 189, 248, 0.3);
    }
    .channel-screen {
      background: linear-gradient(135deg, rgba(245, 158, 11, 0.12) 0%, rgba(30, 41, 59, 0.8) 100%);
      border: 1px solid rgba(245, 158, 11, 0.3);
    }
    .channel-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }
    .channel-title {
      font-size: 0.85rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .channel-audio .channel-title { color: #38bdf8; }
    .channel-screen .channel-title { color: #fbbf24; }
    .channel-text {
      font-size: 1.15rem;
      font-weight: 600;
      line-height: 1.45;
      color: #f8fafc;
    }
    .channel-screen .channel-text {
      font-size: 0.95rem;
      color: #fef3c7;
      font-weight: 500;
    }

    /* Live Feed / Right Column */
    .right-col { display: flex; flex-direction: column; gap: 20px; }

    /* Stats Bar */
    .stats-bar {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
    }
    .stat-pill {
      background: var(--bg-panel);
      border: 1px solid var(--border-subtle);
      border-radius: 12px;
      padding: 12px;
      text-align: center;
    }
    .stat-val { font-size: 1.25rem; font-weight: 800; font-family: 'JetBrains Mono', monospace; }
    .stat-lbl { font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; margin-top: 2px; }

    /* Sections */
    .panel {
      background: var(--bg-panel);
      border: 1px solid var(--border-subtle);
      border-radius: 14px;
      overflow: hidden;
    }
    .panel-head {
      padding: 12px 16px;
      background: rgba(0,0,0,0.2);
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.9rem;
      font-weight: 700;
    }
    .table-wrap { overflow-x: auto; max-height: 280px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    th {
      background: rgba(0,0,0,0.3);
      padding: 8px 12px;
      text-align: left;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      position: sticky;
      top: 0;
    }
    td { padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,0.05); }
    tr:hover td { background: rgba(255,255,255,0.02); }

    .tag {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 6px;
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
    }
    .tag-credit { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
    .tag-cash { background: rgba(16, 185, 129, 0.2); color: #34d399; }
    .tag-payment { background: rgba(56, 189, 248, 0.2); color: #38bdf8; }
    .tag-return { background: rgba(168, 85, 247, 0.2); color: #c084fc; }
    .tag-stock { background: rgba(100, 116, 139, 0.25); color: #94a3b8; }
    .tag-overdue { background: rgba(244, 63, 94, 0.25); color: #fda4af; border: 1px solid rgba(244,63,94,0.4); }

    /* Widget Preview Box */
    .widget-box {
      width: 100%;
      height: 380px;
      border: none;
      border-radius: 0 0 14px 14px;
      background: white;
    }
  </style>
</head>
<body>
  <header>
    <div class="brand-group">
      <div class="brand-icon">🏪</div>
      <div>
        <div class="brand-title">Namma-Kanakku (நம்ம கணக்கு)</div>
        <div class="brand-sub">Voice Khata for Neighbourhood Shops • Alexa+ MCP Server</div>
      </div>
    </div>
    <div class="header-actions">
      <div class="status-badge">
        <div class="status-dot"></div>
        <span>Streamable HTTP (/mcp) Live</span>
      </div>
      <button id="ttsToggle" class="btn-toggle active" onclick="toggleTTS()">
        <span>🔊 Audio Readback: ON</span>
      </button>
      <button class="btn-toggle" onclick="resetDemo()">
        <span>🔄 Reset Demo</span>
      </button>
    </div>
  </header>

  <main>
    <!-- Left Column: Command Input & Dual-Channel Box -->
    <div class="left-col">
      <div class="command-box">
        <div class="input-row">
          <button id="micBtn" class="mic-btn" onclick="toggleMic()" title="Hold/Click to Speak in Tamil, Tanglish, or English">🎙️</button>
          <input type="text" id="cmdInput" class="cmd-input" placeholder="Speak or type: 'Karthik 3B ku rendu thayir and oru kadala ennai, udhaar'..." onkeydown="if(event.key==='Enter') executeCommand()">
          <button class="btn-send" onclick="executeCommand()">Run</button>
          <button class="btn-undo-action" onclick="runChip('Undo last entry')">↩️ Undo</button>
        </div>
        <div class="chips-label">Try Spoken Kirana Utterances (Tamil / Tanglish / English):</div>
        <div class="chips-grid">
          <div class="chip" onclick="runChip('Karthik 3B ku rendu thayir and oru kadala ennai, udhaar')">🛒 Karthik 3B: 2 Curd + 1 Kadala Ennai (Udhaar)</div>
          <div class="chip" onclick="runChip('Ramesh teacher ku rendu thayir udhaar')">🛒 Ramesh Teacher: 2 Curd (Udhaar)</div>
          <div class="chip" onclick="runChip('rendu thayir cash')">💵 2 Curd (Cash Sale)</div>
          <div class="chip" onclick="runChip('Priya Madam 200 kuduthaaru')">💰 Priya Madam: 200 Kuduthaaru (Payment)</div>
          <div class="chip" onclick="runChip('credit check for Ramesh Teacher')">🛡️ Quiet Credit Check (Ramesh)</div>
          <div class="chip" onclick="runChip('morning brief')">🌅 Morning Brief</div>
          <div class="chip" onclick="runChip('today summary')">📊 Today's Summary & Profit</div>
          <div class="chip" onclick="runChip('Toor dal return oru kilo')">📦 Toor Dal Return (1 kg)</div>
          <div class="chip" onclick="runChip('Remember pasu thayir means Curd 500ml')">🧠 Remember Pasu Thayir = Curd</div>
        </div>
      </div>

      <div class="dual-channel-container">
        <!-- Channel 1: Counter Audio (What Customer & Shop Hears) -->
        <div class="channel-card channel-audio">
          <div class="channel-header">
            <div class="channel-title">
              <span>🔊 What Counter Hears (Audible Readback)</span>
            </div>
            <button class="btn-toggle" style="padding: 2px 8px; font-size: 0.75rem;" onclick="speakCurrentAudio()">▶️ Replay</button>
          </div>
          <div id="spokenText" class="channel-text">"Namma Kanakku is ready. Speak in Tamil, Tanglish, or English."</div>
        </div>

        <!-- Channel 2: Confidential Screen Note (What Shopkeeper Sees) -->
        <div class="channel-card channel-screen">
          <div class="channel-header">
            <div class="channel-title">
              <span>👁️ What Shopkeeper Sees (Confidential Note)</span>
            </div>
            <span style="font-size: 0.72rem; color: #fbbf24; font-weight: 600;">VISUAL ONLY • NOT SPOKEN</span>
          </div>
          <div id="screenNoteText" class="channel-text">Ramesh Teacher has dues of Rs 450 (unpaid for 35 days). Customer debts are strictly kept private from spoken audio.</div>
        </div>
      </div>

      <!-- Live MCP Apps Khata Card Preview -->
      <div class="panel">
        <div class="panel-head">
          <span>📱 Alexa+ MCP Apps Interactive Khata Card (`ui://khata-card`)</span>
          <span style="font-size:0.75rem; color:var(--text-muted);">Real-time Echo Show View</span>
        </div>
        <iframe id="widgetIframe" class="widget-box" src="/widget"></iframe>
      </div>
    </div>

    <!-- Right Column: Stats, Ledger Feed, and Customer Directory -->
    <div class="right-col">
      <!-- Stats Bar -->
      <div class="stats-bar">
        <div class="stat-pill">
          <div id="statCash" class="stat-val" style="color:#34d399;">₹0</div>
          <div class="stat-lbl">Cash Sales</div>
        </div>
        <div class="stat-pill">
          <div id="statCredit" class="stat-val" style="color:#fbbf24;">₹0</div>
          <div class="stat-lbl">Udhaar Given</div>
        </div>
        <div class="stat-pill">
          <div id="statCollected" class="stat-val" style="color:#38bdf8;">₹0</div>
          <div class="stat-lbl">Payments Recv</div>
        </div>
        <div class="stat-pill">
          <div id="statProfit" class="stat-val" style="color:#c084fc;">₹0</div>
          <div class="stat-lbl">Gross Profit</div>
        </div>
      </div>

      <!-- Recent Ledger Transactions -->
      <div class="panel">
        <div class="panel-head">
          <span>Recent Counter Ledger Transactions</span>
          <span style="font-size:0.75rem; color:var(--text-muted);">Live Poll (2s)</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Seq</th><th>Customer</th><th>Event</th><th>Amount</th><th>Items</th><th>Time</th></tr>
            </thead>
            <tbody id="entriesTableBody">
              <tr><td colspan="6" style="text-align:center;color:var(--text-muted);">Loading ledger...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Customer Directory -->
      <div class="panel">
        <div class="panel-head">
          <span>Customer Accounts & Credit Limits</span>
          <span style="font-size:0.75rem; color:var(--text-muted);">Confidential Khata</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Customer</th><th>Balance</th><th>Credit Limit</th><th>Status</th></tr>
            </thead>
            <tbody id="customersTableBody">
              <tr><td colspan="4" style="text-align:center;color:var(--text-muted);">Loading customers...</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </main>

  <script>
    let ttsEnabled = true;
    let localVersion = -1;

    function toggleTTS() {
      ttsEnabled = !ttsEnabled;
      const btn = document.getElementById("ttsToggle");
      if (ttsEnabled) {
        btn.classList.add("active");
        btn.innerHTML = "<span>🔊 Audio Readback: ON</span>";
      } else {
        btn.classList.remove("active");
        btn.innerHTML = "<span>🔇 Audio Readback: OFF</span>";
      }
    }

    function speakText(text) {
      if (!ttsEnabled || !window.speechSynthesis) return;
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.0;
      utterance.lang = "en-IN";
      window.speechSynthesis.speak(utterance);
    }

    function speakCurrentAudio() {
      const text = document.getElementById("spokenText").innerText.replace(/^"|"$/g, '');
      speakText(text);
    }

    // Speech Recognition
    let recognition = null;
    let isListening = false;
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
      recognition = new SpeechRec();
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.lang = 'en-IN';

      recognition.onstart = function() {
        isListening = true;
        document.getElementById("micBtn").classList.add("listening");
      };
      recognition.onend = function() {
        isListening = false;
        document.getElementById("micBtn").classList.remove("listening");
      };
      recognition.onresult = function(event) {
        const transcript = event.results[0][0].transcript;
        document.getElementById("cmdInput").value = transcript;
        executeCommand();
      };
      recognition.onerror = function(err) {
        isListening = false;
        document.getElementById("micBtn").classList.remove("listening");
      };
    }

    function toggleMic() {
      if (!recognition) {
        alert("Web Speech API not supported in this browser. Please type commands in the box.");
        return;
      }
      if (isListening) {
        recognition.stop();
      } else {
        recognition.start();
      }
    }

    async function executeCommand() {
      const input = document.getElementById("cmdInput");
      const cmd = input.value.trim();
      if (!cmd) return;

      try {
        const res = await fetch("/api/command", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ command: cmd })
        });
        const data = await res.json();
        
        // Update Dual-Channel Display
        document.getElementById("spokenText").innerText = `"${data.spoken_summary}"`;
        document.getElementById("screenNoteText").innerText = data.screen_note || "Normal transaction. No overdue debts or margin issues.";

        // Speak aloud if TTS enabled
        speakText(data.spoken_summary);

        // Update widget iframe postMessage
        const iframe = document.getElementById("widgetIframe");
        if (iframe && iframe.contentWindow) {
          iframe.contentWindow.postMessage({
            jsonrpc: "2.0",
            method: "ui/notifications/tool-input",
            params: {
              toolName: data.tool_called || "write_entry",
              arguments: data.arguments || {},
              result: data.structured_data || {}
            }
          }, "*");
        }

        input.value = "";
        pollState();
      } catch (err) {
        console.error(err);
      }
    }

    function runChip(cmdText) {
      document.getElementById("cmdInput").value = cmdText;
      executeCommand();
    }

    async function resetDemo() {
      if (!confirm("Reset database to pristine demo state?")) return;
      await fetch("/reset", { method: "POST" });
      pollState();
    }

    async function pollState() {
      try {
        const res = await fetch("/api/state");
        const state = await res.json();

        // Update stats
        if (state.summary) {
          document.getElementById("statCash").innerText = `₹${state.summary.cash_sales}`;
          document.getElementById("statCredit").innerText = `₹${state.summary.credit_sales}`;
          document.getElementById("statCollected").innerText = `₹${state.summary.payments_received}`;
          document.getElementById("statProfit").innerText = `₹${state.summary.estimated_gross_profit}`;
        }

        // Update Recent Entries
        if (state.recent_entries) {
          let rows = "";
          for (const e of state.recent_entries) {
            let tagClass = "tag-stock";
            if (e.entry_type === "CASH_SALE") tagClass = "tag-cash";
            else if (e.entry_type === "CREDIT_SALE") tagClass = "tag-credit";
            else if (e.entry_type === "PAYMENT_RECEIVED") tagClass = "tag-payment";
            else if (e.entry_type === "RETURN") tagClass = "tag-return";

            rows += `<tr>
              <td style="font-family:'JetBrains Mono',monospace;color:var(--text-muted);">#${e.seq}</td>
              <td><strong>${e.customer_name || 'Anonymous'}</strong></td>
              <td><span class="tag ${tagClass}">${e.entry_type.replace('_', ' ')}</span></td>
              <td style="font-weight:700;">₹${e.amount}</td>
              <td style="color:var(--text-muted);font-size:0.8rem;">${e.items_summary || '—'}</td>
              <td style="color:var(--text-muted);font-size:0.75rem;">${e.created_at.split(' ')[1] || e.created_at}</td>
            </tr>`;
          }
          document.getElementById("entriesTableBody").innerHTML = rows || "<tr><td colspan='6'>No entries yet.</td></tr>";
        }

        // Update Customers
        if (state.customers) {
          let custRows = "";
          for (const c of state.customers) {
            let badge = `<span style="color:#10b981;font-weight:600;">Good</span>`;
            if (c.is_overdue) {
              badge = `<span class="tag tag-overdue">Unpaid ${c.days_unpaid}d</span>`;
            } else if (c.current_balance > c.credit_limit) {
              badge = `<span class="tag tag-overdue">Over Limit</span>`;
            }
            custRows += `<tr>
              <td><strong style="cursor:pointer;" onclick="runChip('what is ${c.name} balance')">${c.name}</strong></td>
              <td style="font-weight:700;color:${c.current_balance > 0 ? '#fbbf24' : '#9ca3af'};">₹${c.current_balance}</td>
              <td style="color:var(--text-muted);">₹${c.credit_limit}</td>
              <td>${badge}</td>
            </tr>`;
          }
          document.getElementById("customersTableBody").innerHTML = custRows;
        }

      } catch (err) {
        console.error("State poll failed:", err);
      }
    }

    // Poll every 2 seconds
    pollState();
    setInterval(pollState, 2000);
  </script>
</body>
</html>
"""

async def counter_screen_route(request: Request):
    """Serves the pure ASGI Counter Screen at / (zero Gradio)."""
    return HTMLResponse(COUNTER_SCREEN_HTML)

async def widget_preview_route(request: Request):
    """Direct visual preview of the MCP Apps Khata Card widget."""
    return HTMLResponse(load_widget_html())

async def healthz_route(request: Request):
    return JSONResponse({
        "status": "ok",
        "app": "Namma-Kanakku",
        "demo_mode": True,
        "mcp_transport": "Streamable HTTP (/mcp)",
        "front_door_tools": ["write_entry", "fix_entry", "ask_khata", "update_shop"]
    })

async def api_state_route(request: Request):
    """Returns current state version, customers, recent transactions, and today's stats."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        # Customers
        cur.execute("SELECT id, name, phone, credit_limit, current_balance, last_payment_date FROM customers ORDER BY current_balance DESC")
        customers = []
        for c in cur.fetchall():
            days = engine.days_between(c["last_payment_date"])
            customers.append({
                "id": c["id"],
                "name": c["name"],
                "phone": c["phone"],
                "credit_limit": c["credit_limit"],
                "current_balance": c["current_balance"],
                "last_payment_date": c["last_payment_date"],
                "days_unpaid": days,
                "is_overdue": days >= 30 and c["current_balance"] > 0
            })

        # Recent entries
        cur.execute("""
            SELECT l.seq, c.name as customer_name, l.entry_type, l.amount, l.items_json, l.created_at
            FROM ledger_entries l
            LEFT JOIN customers c ON l.customer_id = c.id
            ORDER BY l.seq DESC LIMIT 15
        """)
        recent_entries = []
        for e in cur.fetchall():
            items_summary = ""
            if e["items_json"]:
                try:
                    its = json.loads(e["items_json"])
                    items_summary = ", ".join(f"{it['quantity']}{it.get('unit','')} {it['display_name']}" for it in its)
                except Exception:
                    items_summary = str(e["items_json"])
            recent_entries.append({
                "seq": e["seq"],
                "customer_name": e["customer_name"],
                "entry_type": e["entry_type"],
                "amount": e["amount"],
                "items_summary": items_summary,
                "created_at": e["created_at"]
            })

        # Summary
        cur.execute("SELECT entry_type, amount, cost_amount FROM ledger_entries")
        all_entries = cur.fetchall()
        cash = sum(e["amount"] for e in all_entries if e["entry_type"] == "CASH_SALE")
        credit = sum(e["amount"] for e in all_entries if e["entry_type"] == "CREDIT_SALE")
        payments = sum(e["amount"] for e in all_entries if e["entry_type"] == "PAYMENT_RECEIVED")
        total_cost = sum(e["cost_amount"] for e in all_entries if e["entry_type"] in ("CASH_SALE", "CREDIT_SALE"))
        profit = round((cash + credit) - total_cost, 2)

        return JSONResponse({
            "version": _STATE_VERSION,
            "customers": customers,
            "recent_entries": recent_entries,
            "summary": {
                "cash_sales": int(cash) if cash.is_integer() else cash,
                "credit_sales": int(credit) if credit.is_integer() else credit,
                "payments_received": int(payments) if payments.is_integer() else payments,
                "estimated_gross_profit": int(profit) if profit.is_integer() else profit
            }
        })
    finally:
        conn.close()

async def api_command_route(request: Request):
    """Executes a natural voice or typed kirana command and returns dual-channel presentation."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    cmd = (body.get("command") or body.get("utterance") or "").strip()
    if not cmd:
        return JSONResponse({"error": "Empty command provided."}, status_code=400)

    cmd_lower = cmd.lower()

    # Route based on utterance
    if "undo" in cmd_lower:
        res = engine.fix_entry(action="undo")
        tool_called = "fix_entry"
    elif any(k in cmd_lower for k in ["credit check", "morning", "brief", "today", "balance", "dues", "evvalavu"]):
        res = engine.ask_khata(question=cmd)
        tool_called = "ask_khata"
    elif "means" in cmd_lower or "remember" in cmd_lower:
        # e.g. "Remember pasu thayir means Curd 500ml"
        res = engine.update_shop(action="teach_alias", alias="pasu thayir", item_name_or_sku="curd_500ml")
        tool_called = "update_shop"
    else:
        res = engine.write_entry(utterance=cmd)
        tool_called = "write_entry"

    if res.get("success"):
        increment_state_version()

    return JSONResponse({
        "success": res.get("success", False),
        "tool_called": tool_called,
        "spoken_summary": res.get("spoken_summary", ""),
        "screen_note": res.get("screen_note"),
        "structured_data": res.get("structured_data", {}),
        "state_version": _STATE_VERSION
    })

async def ledger_dashboard_route(request: Request):
    """Plain HTML fallback ledger dashboard."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT name, phone, current_balance, credit_limit, last_payment_date FROM customers ORDER BY current_balance DESC")
        cust_rows = ""
        for c in cur.fetchall():
            days = engine.days_between(c["last_payment_date"])
            overdue_tag = f'<span style="color:#ef4444;">Overdue ({days}d)</span>' if (days >= 30 and c["current_balance"] > 0) else '<span style="color:#10b981;">Good</span>'
            cust_rows += f"<tr><td>{c['name']}</td><td>Rs {c['current_balance']}</td><td>Rs {c['credit_limit']}</td><td>{overdue_tag}</td></tr>"

        cur.execute("""
            SELECT l.seq, COALESCE(c.name, 'Anonymous') as cname, l.entry_type, l.amount, l.created_at
            FROM ledger_entries l LEFT JOIN customers c ON l.customer_id = c.id
            ORDER BY l.seq DESC LIMIT 15
        """)
        entry_rows = ""
        for e in cur.fetchall():
            entry_rows += f"<tr><td>#{e['seq']}</td><td>{e['cname']}</td><td>{e['entry_type']}</td><td>Rs {e['amount']}</td><td>{e['created_at']}</td></tr>"

        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Namma-Kanakku Ledger</title>
        <style>body{{font-family:sans-serif;margin:24px;background:#f8fafc;color:#0f172a;}} table{{width:100%;border-collapse:collapse;margin-bottom:20px;background:white;}} th,td{{padding:8px 12px;border:1px solid #e2e8f0;text-align:left;}} th{{background:#f1f5f9;}}</style>
        </head><body><h2>Namma-Kanakku Fallback Ledger</h2><h3>Customer Accounts</h3><table><tr><th>Customer</th><th>Balance</th><th>Credit Limit</th><th>Status</th></tr>{cust_rows}</table><h3>Recent Transactions</h3><table><tr><th>Seq</th><th>Customer</th><th>Type</th><th>Amount</th><th>Time</th></tr>{entry_rows}</table></body></html>"""
        return HTMLResponse(html)
    finally:
        conn.close()

async def reset_route(request: Request):
    seed_demo_data(force=True)
    increment_state_version()
    return JSONResponse({"status": "reset_successful", "message": "Demo data restored to pristine state."})


# ============================================================================
# 5. ASSEMBLE STARLETTE ASGI APPLICATION
# ============================================================================

# Build the Streamable HTTP Starlette app mounted at /mcp
app = mcp_server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True)

# Register pure ASGI routes directly onto the app
app.add_route("/", counter_screen_route, methods=["GET"])
app.add_route("/widget", widget_preview_route, methods=["GET"])
app.add_route("/healthz", healthz_route, methods=["GET"])
app.add_route("/api/state", api_state_route, methods=["GET"])
app.add_route("/api/command", api_command_route, methods=["POST"])
app.add_route("/ledger", ledger_dashboard_route, methods=["GET"])
app.add_route("/reset", reset_route, methods=["GET", "POST"])

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    print(f"Starting Namma-Kanakku on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
