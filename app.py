"""
app.py - Hugging Face Spaces entrypoint for Namma-Kanakku.
Mounts:
1. Interactive Gradio UI at root / for hackathon judges to test voice/text inputs live.
2. Streamable HTTP MCP endpoint at /mcp for Alexa+ and MCP clients.
3. Interactive MCP Apps widget at /widget.
4. Live auto-refreshing ledger dashboard at /ledger.
5. Health check endpoint at /healthz.
"""

import os
import sys

# Ensure local imports resolve
sys.path.insert(0, os.path.dirname(__file__))

import gradio as gr
import uvicorn
from server import app as starlette_app
from database import get_db, seed_demo_data
from ledger import get_customer_balance, log_credit_entry, undo_last_entry, get_overdue_accounts
from data_ownership import evaluate_wholesale_quote

# Ensure demo data is seeded
seed_demo_data()

# 1. Action handlers for judges' interactive testing
def test_balance(customer_name: str):
    conn = get_db()
    try:
        res = get_customer_balance(conn, customer_name)
        return res
    finally:
        conn.close()

def test_credit(customer_name: str, item_text: str, quantity: float):
    conn = get_db()
    try:
        res = log_credit_entry(conn, customer_name, [{"item_name": item_text, "quantity": quantity}])
        return res
    finally:
        conn.close()

def test_undo(customer_name: str):
    conn = get_db()
    try:
        res = undo_last_entry(conn, customer_name)
        return res
    finally:
        conn.close()

def test_overdue():
    conn = get_db()
    try:
        res = get_overdue_accounts(conn)
        return res
    finally:
        conn.close()

def test_wholesale(item: str, wholesale_price: float, qty: float):
    conn = get_db()
    try:
        res = evaluate_wholesale_quote(conn, item, wholesale_price, qty)
        return res
    finally:
        conn.close()

# 2. Build Gradio Blocks Dashboard for Judges
custom_css = """
.gradio-container { max-width: 1200px !important; margin: 0 auto !important; }
.hero-box { background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%); color: white; padding: 24px; border-radius: 12px; margin-bottom: 20px; }
.hero-box h1 { color: white !important; margin: 0 0 8px 0; font-size: 2rem; }
.hero-box p { color: #e0f2fe; margin: 0; font-size: 1.05rem; }
.badge { display: inline-block; background: #e0f2fe; color: #0369a1; padding: 4px 10px; border-radius: 20px; font-weight: bold; font-size: 0.8rem; margin-right: 8px; }
"""

with gr.Blocks(title="Namma-Kanakku (நம்ம கணக்கு) - Voice Khata", css=custom_css, theme=gr.themes.Soft()) as demo:
    gr.HTML("""
    <div class="hero-box">
        <h1>🏪 Namma-Kanakku (நம்ம கணக்கு)</h1>
        <p><strong>"A voice khata that learns your shop's language, keeps your customers' debts private, and never guesses with money."</strong></p>
        <p style="margin-top: 6px; font-size: 0.95rem; opacity: 0.9;">
            <em>"உங்கள் கடையின் மொழியைப் பேசும், வாடிக்கையாளரின் மரியாதையைக் காக்கும் நவீன குரல் கணக்கு."</em>
        </p>
        <div style="margin-top: 14px;">
            <span class="badge">Alexa+ Track Hackathon 2026</span>
            <span class="badge">Streamable HTTP (/mcp)</span>
            <span class="badge">12.92 ms Latency</span>
            <span class="badge">Zero Spoken Debts</span>
        </div>
    </div>
    """)

    with gr.Row():
        with gr.Column(scale=3):
            gr.Markdown("### 🎙️ Live Interactive Tool Testing for Judges")
            gr.Markdown("Test how Namma-Kanakku handles Tanglish, phonetic spelling, and strict discretion:")

            with gr.Tabs():
                with gr.TabItem("1. Log Credit Entry (Tanglish & Discretion)"):
                    gr.Markdown("*Notice: Confirms items and price, but **NEVER** speaks total balance aloud into a crowded shop.*")
                    c_name_1 = gr.Dropdown(choices=["Ramesh Teacher", "Priya Madam", "Suresh Auto", "Kavitha Akka", "Murugan Painter"], value="Ramesh Teacher", label="Customer Name")
                    item_text_1 = gr.Textbox(value="thayir", label="Item Spoken (e.g. 'thayir', 'half kilo toor dal', 'curd 500ml', 'kadala ennai')")
                    qty_1 = gr.Number(value=1.0, label="Quantity")
                    btn_log = gr.Button("▶️ Run: log_credit_entry", variant="primary")
                    out_log = gr.JSON(label="Result (Inspect spoken_summary and screen_note)")

                with gr.TabItem("2. Check Balance (Private Query)"):
                    gr.Markdown("*Balances are spoken ONLY when the shopkeeper explicitly queries via get_customer_balance.*")
                    c_name_2 = gr.Dropdown(choices=["Ramesh Teacher", "Priya Madam", "Suresh Auto", "Kavitha Akka", "Murugan Painter"], value="Ramesh Teacher", label="Customer Name")
                    btn_bal = gr.Button("▶️ Run: get_customer_balance", variant="secondary")
                    out_bal = gr.JSON(label="Result")

                with gr.TabItem("3. Reversible Undo (seq DESC)"):
                    gr.Markdown("*Instantly rolls back the last action by autoincrement sequence ID, restoring balance and timestamp.*")
                    c_name_3 = gr.Dropdown(choices=["Ramesh Teacher", "Priya Madam", "Suresh Auto", "Kavitha Akka", "Murugan Painter"], value="Ramesh Teacher", label="Customer Name")
                    btn_undo = gr.Button("↩️ Run: undo_last_entry", variant="stop")
                    out_undo = gr.JSON(label="Result")

                with gr.TabItem("4. 30-Day Overdue Accounts"):
                    gr.Markdown("*Returns accounts with unpaid credit older than 30 days without broadcasting balances.*")
                    btn_overdue = gr.Button("📋 Run: get_overdue_accounts")
                    out_overdue = gr.JSON(label="Result")

                with gr.TabItem("5. Wholesale Margin Calculator"):
                    gr.Markdown("*Calculates profit margin and retail profit on wholesale quotes.*")
                    ws_item = gr.Textbox(value="toor_dal", label="Catalog Item")
                    ws_price = gr.Number(value=135.0, label="Wholesale Price Quoted (Rs)")
                    ws_qty = gr.Number(value=10.0, label="Quantity")
                    btn_ws = gr.Button("📊 Run: evaluate_wholesale_quote")
                    out_ws = gr.JSON(label="Result")

        with gr.Column(scale=2):
            gr.Markdown("### 📱 MCP Apps Khata Widget (`ui://khata-card`)")
            gr.Markdown("Interactive card rendered inside assistant displays (with dark/light mode):")
            gr.HTML("""
            <iframe src="/widget" style="width: 100%; height: 480px; border: 1px solid #e2e8f0; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);"></iframe>
            """)
            gr.Markdown("""
            ---
            #### 🔗 Judge Endpoints
            - **Streamable HTTP MCP**: [`/mcp`](/mcp)
            - **Interactive Widget**: [`/widget`](/widget)
            - **Live Auto-Refreshing Ledger**: [`/ledger`](/ledger)
            - **Health Check**: [`/healthz`](/healthz)
            - **GitHub Source**: [monishchandran2007-hub/Namma-Kanakku](https://github.com/monishchandran2007-hub/Namma-Kanakku)
            """)

    # Connect interactions
    btn_log.click(test_credit, inputs=[c_name_1, item_text_1, qty_1], outputs=[out_log])
    btn_bal.click(test_balance, inputs=[c_name_2], outputs=[out_bal])
    btn_undo.click(test_undo, inputs=[c_name_3], outputs=[out_undo])
    btn_overdue.click(test_overdue, inputs=[], outputs=[out_overdue])
    btn_ws.click(test_wholesale, inputs=[ws_item, ws_price, ws_qty], outputs=[out_ws])

# Mount Gradio onto the Starlette MCP application at /
app = gr.mount_gradio_app(starlette_app, demo, path="/")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    print(f"Starting Namma-Kanakku on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
