"""
server.py - Streamable HTTP MCP Server for KiranaFlow.

Features:
- Official MCP Python SDK 2025-11-25+ Streamable HTTP transport served at /mcp.
- Defensively handles base URL / and redirects to /mcp.
- Auxiliary plain routes:
  - /healthz: Service health check.
  - /ledger: Fallback HTML dashboard with 5-second auto-refresh.
  - /reset: Resets database to pristine demo state if RESET_KEY matches (disabled if unset).
- MCP Apps UI resource: ui://khata-card (with data-only rendering fallback).
- 9 MCP Tools (5 Core Ledger + 4 Data-Ownership + 1 Isolated Wholesale stretch tool).
- Idempotent startup seeder for labeled demo data.
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
from matching import normalize_text, match_item

# Ensure database is initialized with labelled demo data on startup
seed_demo_data(force=False)

# Initialize MCPServer
mcp_server = MCPServer(
    name="KiranaFlow",
    version="1.0.0",
    description="A voice khata that learns your shop's language, keeps debts private, and never guesses with money."
)

# Pydantic Schemas for Tools
class ItemInput(BaseModel):
    item_name: str = Field(description="Spoken name of the item in English, Tanglish, or Tamil script (e.g. 'toor dal', 'thayir', 'sunflower oil', 'தயிர்')")
    quantity: Union[float, int, str] = Field(default=1.0, description="Quantity. For loose items by weight, specify in kg or grams (e.g. 0.5, 'half kilo', '250g').")
    unit: Optional[str] = Field(default=None, description="Optional unit (e.g., 'kg', 'g', 'packet', 'piece', 'bunch').")
    english_guess: Optional[str] = Field(default=None, description="Optional English translation guess provided by Alexa+ if word is Tamil/Tanglish/Hindi.")
    original_spoken: Optional[str] = Field(default=None, description="Original ambiguous word when answering a clarification, used to record a learned alias.")

# ============================================================================
# 1. CORE LEDGER TOOLS
# ============================================================================

@mcp_server.tool(
    name="log_credit_entry",
    description=(
        "Log one or more items on credit for a customer. "
        "Strictly atomic: saves nothing unless the customer and all items resolve. "
        "Alexa reasoning: If the customer word is Tamil/Tanglish, provide your translation in english_guess. "
        "Discretion: Never announce customer's total balance or limit aloud; only speak the itemized total and read-back."
    ),
    meta={"ui": {"resourceUri": "ui://khata-card"}}
)
def log_credit_entry(
    customer_name: str,
    items: List[ItemInput]
) -> Dict[str, Any]:
    items_dicts = [it.model_dump() for it in items]
    return ledger.log_credit_entry(customer_name, items_dicts)

@mcp_server.tool(
    name="record_payment",
    description=(
        "Record a cash or UPI payment from a customer. "
        "The payment is automatically capped at the customer's outstanding balance. "
        "Discretion: Never announce the customer's remaining debt or balance aloud."
    ),
    meta={"ui": {"resourceUri": "ui://khata-card"}}
)
def record_payment(
    customer_name: str,
    amount: float
) -> Dict[str, Any]:
    return ledger.record_payment(customer_name, amount)

@mcp_server.tool(
    name="get_customer_balance",
    description=(
        "Check a customer's balance, credit limit, and payment history. "
        "Spoken balance is permitted here because the shopkeeper explicitly requested it."
    ),
    meta={"ui": {"resourceUri": "ui://khata-card"}}
)
def get_customer_balance(
    customer_name: str
) -> Dict[str, Any]:
    return ledger.get_customer_balance(customer_name)

@mcp_server.tool(
    name="undo_last_entry",
    description=(
        "Undo the most recent ledger entry (credit purchase or payment). "
        "Optionally specify customer_name to undo the last entry for that specific customer. "
        "Orders strictly by sequential ledger ID, never timestamps. "
        "Restores previous balance and last payment dates."
    ),
    meta={"ui": {"resourceUri": "ui://khata-card"}}
)
def undo_last_entry(
    customer_name: Optional[str] = None
) -> Dict[str, Any]:
    return ledger.undo_last_entry(customer_name)

@mcp_server.tool(
    name="get_overdue_accounts",
    description=(
        "Get a list of customer accounts with unpaid balances of 30 days or more. "
        "Discretion: Speaks only the count of overdue accounts; customer names and numbers go to screen only."
    ),
    meta={"ui": {"resourceUri": "ui://khata-card"}}
)
def get_overdue_accounts() -> Dict[str, Any]:
    return ledger.get_overdue_accounts()

# ============================================================================
# 2. DATA-OWNERSHIP TOOLS
# ============================================================================

@mcp_server.tool(
    name="teach_item_alias",
    description=(
        "Teach the shop's local language or custom vocabulary. "
        "Links a spoken alias, slang, brand name, or Tanglish word to an existing catalog SKU. "
        "Example: 'remember kothamalli means coriander leaves'."
    ),
    meta={"ui": {"resourceUri": "ui://khata-card"}}
)
def teach_item_alias(
    alias: str,
    item_name_or_sku: str
) -> Dict[str, Any]:
    return data_ownership.teach_item_alias(alias, item_name_or_sku)

@mcp_server.tool(
    name="set_item_price",
    description=(
        "Update the unit price of an item in the shopkeeper's catalog. "
        "Applies immediately to future transactions without altering historical ledger entries."
    ),
    meta={"ui": {"resourceUri": "ui://khata-card"}}
)
def set_item_price(
    item_name_or_sku: str,
    new_price: float
) -> Dict[str, Any]:
    return data_ownership.set_item_price(item_name_or_sku, new_price)

@mcp_server.tool(
    name="add_catalog_item",
    description=(
        "Add a new product to the shop's own catalog. "
        "Display names must be generic (e.g. 'Curd 500ml', not third-party brand names). "
        "Brand names may be added as aliases."
    ),
    meta={"ui": {"resourceUri": "ui://khata-card"}}
)
def add_catalog_item(
    sku: str,
    display_name: str,
    price: float,
    unit: str = "packet",
    is_loose: bool = False,
    aliases: Optional[List[str]] = None
) -> Dict[str, Any]:
    return data_ownership.add_catalog_item(sku, display_name, price, unit, is_loose, aliases)

@mcp_server.tool(
    name="add_customer",
    description=(
        "Register a new customer in the shop's khata with a name, optional phone, and credit limit. "
        "Rejects duplicate customer names."
    ),
    meta={"ui": {"resourceUri": "ui://khata-card"}}
)
def add_customer(
    name: str,
    phone: Optional[str] = None,
    credit_limit: float = 2000.0
) -> Dict[str, Any]:
    return data_ownership.add_customer(name, phone, credit_limit)

# ============================================================================
# 3. STRETCH TOOL: EVALUATE WHOLESALE QUOTE (Isolated)
# ============================================================================

@mcp_server.tool(
    name="evaluate_wholesale_quote",
    description=(
        "Compare a wholesale price quote against current retail catalog price. "
        "Calculates gross profit margin and expected savings."
    )
)
def evaluate_wholesale_quote(
    item_name_or_sku: str,
    wholesale_price: float,
    quantity: float = 1.0
) -> Dict[str, Any]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT sku, display_name, price, unit FROM catalog_items WHERE sku = ? AND is_active = 1", (item_name_or_sku,))
        row = cur.fetchone()
        if not row:
            res = match_item(conn, item_name_or_sku)
            if res["status"] == "SUCCESS":
                sku = res["sku"]
                name = res["display_name"]
                retail_price = res["unit_price"]
                unit = res["unit"]
            else:
                return {
                    "success": False,
                    "status": "ITEM_NOT_FOUND",
                    "spoken_summary": f"Could not find '{item_name_or_sku}' in catalog to evaluate quote."
                }
        else:
            sku = row["sku"]
            name = row["display_name"]
            retail_price = row["price"]
            unit = row["unit"]

        margin_per_unit = round(retail_price - wholesale_price, 2)
        margin_pct = round((margin_per_unit / retail_price) * 100, 1) if retail_price > 0 else 0.0
        total_savings = round(margin_per_unit * quantity, 2)

        spoken = f"For {name}, wholesale quote of {wholesale_price} rupees gives a margin of {margin_per_unit} rupees per {unit} ({margin_pct}%)."
        return {
            "success": True,
            "status": "SUCCESS",
            "spoken_summary": spoken,
            "structured_data": {
                "sku": sku,
                "display_name": name,
                "retail_price": retail_price,
                "wholesale_quote": wholesale_price,
                "margin_per_unit": margin_per_unit,
                "margin_percentage": margin_pct,
                "total_savings": total_savings
            }
        }
    finally:
        conn.close()

# ============================================================================
# 4. MCP APPS RESOURCE (ui://khata-card)
# ============================================================================

WIDGET_FILE_PATH = os.path.join(os.path.dirname(__file__), "widget.html")

def load_widget_html() -> str:
    if os.path.exists(WIDGET_FILE_PATH):
        with open(WIDGET_FILE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "<!DOCTYPE html><html><body>Khata Card</body></html>"

@mcp_server.resource("ui://khata-card", mime_type="text/html")
def get_khata_card_widget() -> str:
    """
    Self-contained MCP Apps Khata Card widget.
    Implements JSON-RPC 2.0 postMessage handshake (ui/initialize, ui/notifications/initialized, ui/notifications/tool-input).
    Supports light and dark mode, highlighting recent transactions and badges.
    """
    return load_widget_html()

@mcp_server.custom_route("/widget", methods=["GET"])
async def widget_preview_route(request: Request):
    """Direct visual preview of the MCP Apps Khata Card widget."""
    return HTMLResponse(load_widget_html())

# ============================================================================
# 5. AUXILIARY PLAIN ROUTES (/healthz, /ledger, /reset, /)
# ============================================================================

@mcp_server.custom_route("/healthz", methods=["GET"])
async def healthz_route(request: Request):
    return JSONResponse({
        "status": "ok",
        "app": "KiranaFlow",
        "demo_mode": True,
        "mcp_transport": "Streamable HTTP (/mcp)"
    })

@mcp_server.custom_route("/ledger", methods=["GET"])
async def ledger_dashboard_route(request: Request):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, phone, credit_limit, current_balance, last_payment_date FROM customers ORDER BY current_balance DESC")
        customers = cur.fetchall()

        cur.execute("""
            SELECT l.seq, c.name as customer_name, l.entry_type, l.amount, l.items_json, l.previous_balance, l.new_balance, l.created_at
            FROM ledger_entries l
            JOIN customers c ON l.customer_id = c.id
            ORDER BY l.seq DESC LIMIT 20
        """)
        entries = cur.fetchall()

        cust_rows = ""
        for c in customers:
            overdue_badge = ""
            days = ledger.days_between(c["last_payment_date"])
            if days >= 30 and c["current_balance"] > 0:
                overdue_badge = f'<span style="background:#fee2e2;color:#991b1b;padding:2px 6px;border-radius:4px;font-size:0.75rem;">Overdue ({days}d)</span>'
            cust_rows += f"""
            <tr>
                <td><strong>{c['name']}</strong></td>
                <td>{c['phone']}</td>
                <td>Rs {c['current_balance']} {overdue_badge}</td>
                <td>Rs {c['credit_limit']}</td>
                <td>{c['last_payment_date'] or 'Never'}</td>
            </tr>
            """

        entry_rows = ""
        for e in entries:
            items_desc = ""
            if e["items_json"]:
                try:
                    its = json.loads(e["items_json"])
                    items_desc = ", ".join([f"{i['quantity']}{i['unit']} {i['display_name']}" for i in its])
                except Exception:
                    items_desc = e["items_json"]
            type_color = "#16a34a" if e["entry_type"] == "PAYMENT" else "#ea580c"
            entry_rows += f"""
            <tr>
                <td>#{e['seq']}</td>
                <td><strong>{e['customer_name']}</strong></td>
                <td><span style="color:{type_color};font-weight:600;">{e['entry_type']}</span></td>
                <td>Rs {e['amount']}</td>
                <td style="font-size:0.85rem;color:#4b5563;">{items_desc}</td>
                <td>Rs {e['previous_balance']} &rarr; Rs {e['new_balance']}</td>
                <td style="font-size:0.8rem;color:#6b7280;">{e['created_at']}</td>
            </tr>
            """

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="5">
    <title>KiranaFlow - Live Fallback Ledger</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 24px; background: #f9fafb; color: #111827; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #e5e7eb; padding-bottom: 12px; margin-bottom: 20px; }}
        h1 {{ margin: 0; font-size: 1.5rem; color: #0284c7; }}
        .badge {{ background: #e0f2fe; color: #0369a1; padding: 4px 10px; border-radius: 9999px; font-size: 0.85rem; font-weight: 600; }}
        .demo-notice {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 10px; margin-bottom: 20px; font-size: 0.9rem; color: #92400e; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #f3f4f6; }}
        th {{ background: #f3f4f6; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: #4b5563; }}
        .section-title {{ font-size: 1.15rem; font-weight: 700; margin: 20px 0 10px 0; color: #374151; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>KiranaFlow - Modern Voice Khata</h1>
        <div class="badge">Auto-refresh (5s)</div>
    </div>
    <div class="demo-notice">
        <strong>[DEMO DATA - NOT REAL]</strong> All numbers and customer records shown are simulated demo data.
    </div>
    
    <div class="section-title">Customer Accounts</div>
    <table>
        <thead>
            <tr><th>Customer</th><th>Phone</th><th>Balance</th><th>Credit Limit</th><th>Last Payment</th></tr>
        </thead>
        <tbody>{cust_rows}</tbody>
    </table>

    <div class="section-title">Recent Ledger Entries</div>
    <table>
        <thead>
            <tr><th>Seq</th><th>Customer</th><th>Type</th><th>Amount</th><th>Items</th><th>Balance Transition</th><th>Time (UTC)</th></tr>
        </thead>
        <tbody>{entry_rows or "<tr><td colspan='7'>No recent transactions recorded.</td></tr>"}</tbody>
    </table>
</body>
</html>"""
        return HTMLResponse(html)
    finally:
        conn.close()

@mcp_server.custom_route("/reset", methods=["POST", "GET"])
async def reset_route(request: Request):
    """
    Resets the SQLite database to initial demo state.
    Requires RESET_KEY environment variable. Disabled if unset.
    """
    reset_key = os.environ.get("RESET_KEY")
    if not reset_key:
        return JSONResponse({
            "error": "Reset endpoint is disabled. Set RESET_KEY environment variable to enable."
        }, status_code=403)

    provided_key = request.query_params.get("key") or request.headers.get("X-Reset-Key")
    if provided_key != reset_key:
        return JSONResponse({"error": "Unauthorized: invalid reset key"}, status_code=401)

    seed_demo_data(force=True)
    return JSONResponse({"status": "reset_successful", "message": "Demo data restored to pristine state."})

@mcp_server.custom_route("/", methods=["GET", "POST"])
async def root_defensive_route(request: Request):
    """
    Defensive routing: If an MCP client hits the root URL /, forward or redirect to /mcp.
    For browser GET requests, redirect to /ledger dashboard.
    """
    if request.method == "POST":
        return RedirectResponse(url="/mcp", status_code=307)
    return RedirectResponse(url="/ledger", status_code=302)

# Build the Streamable HTTP Starlette app mounted at /mcp
app = mcp_server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting KiranaFlow Streamable HTTP MCP Server on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
