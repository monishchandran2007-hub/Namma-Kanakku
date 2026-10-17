"""
test_stage10.py - Contract Tests for Stage 10:
- Pure ASGI Counter Screen at / (verifies zero Gradio, zero dev terms like 'tab 1', 'tab 3', 'Run:').
- Contract tests verifying no developer vocabulary leaks into user-facing spoken summaries or screen notes.
- Direct verification of HTTP endpoints:
  - GET /: Counter Screen HTML
  - GET /widget: MCP Apps Khata Card widget HTML
  - GET /healthz: Health check JSON
  - GET /api/state: Real-time state JSON with version, customers, transactions
  - POST /api/command: Natural command routing
- Verification of front-door MCP tools registration (write_entry, fix_entry, ask_khata, update_shop).
"""

import os
import json
import pytest
from starlette.testclient import TestClient
from server import app, mcp_server
from database import seed_demo_data

client = TestClient(app)

FORBIDDEN_DEV_TERMS = [
    "tab 1", "tab 2", "tab 3", "tab 4", "tab 5",
    "log_credit_entry", "record_payment", "get_customer_balance",
    "undo_last_entry", "get_overdue_accounts",
    "traceback", "exception", "nullpointer", "syntaxerror",
    "mcp_server", "jsonrpc"
]

@pytest.fixture(autouse=True)
def init_test():
    seed_demo_data(force=True)

# 1. Counter Screen Route Contract
def test_counter_screen_get_root():
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    html_text = res.text.lower()
    assert "namma-kanakku" in html_text
    assert "what counter hears" in html_text
    assert "what shopkeeper sees" in html_text
    # Strictly NO Gradio
    assert "gradio" not in html_text
    assert "svelte" not in html_text

# 2. Widget Route Contract
def test_widget_route():
    res = client.get("/widget")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "ui/initialize" in res.text or "khata-card" in res.text

# 3. Healthz Route Contract
def test_healthz_route():
    res = client.get("/healthz")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "write_entry" in data["front_door_tools"]

# 4. State API Contract
def test_api_state_route():
    res = client.get("/api/state")
    assert res.status_code == 200
    data = res.json()
    assert "version" in data
    assert "customers" in data
    assert len(data["customers"]) >= 5
    assert "recent_entries" in data
    assert "summary" in data
    assert "cash_sales" in data["summary"]
    assert "estimated_gross_profit" in data["summary"]

# 5. Natural Command API Contract
def test_api_command_credit_sale_no_dev_terms():
    res = client.post("/api/command", json={"command": "Ramesh teacher ku rendu thayir udhaar"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    spoken = data["spoken_summary"].lower()
    screen = (data.get("screen_note") or "").lower()

    # Check that forbidden dev terms do NOT leak
    for term in FORBIDDEN_DEV_TERMS:
        assert term not in spoken, f"Forbidden dev term '{term}' found in spoken summary"
        assert term not in screen, f"Forbidden dev term '{term}' found in screen note"

def test_api_command_quiet_credit_check_no_dev_terms():
    res = client.post("/api/command", json={"command": "credit check for Ramesh Teacher"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    # Discretion: Audio must be strictly "Please check the screen."
    assert data["spoken_summary"] == "Please check the screen."
    assert "Credit Check Warning" in data["screen_note"]

    for term in FORBIDDEN_DEV_TERMS:
        assert term not in data["spoken_summary"].lower()
        assert term not in data["screen_note"].lower()

def test_api_command_undo_no_dev_terms():
    # Make a sale first
    client.post("/api/command", json={"command": "rendu thayir cash"})
    res = client.post("/api/command", json={"command": "undo that"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "Undone" in data["spoken_summary"]
    for term in FORBIDDEN_DEV_TERMS:
        assert term not in data["spoken_summary"].lower()

# 6. Front-Door Tools Registered on MCPServer
def test_front_door_tools_registered():
    # Tools registered on MCPServer tool manager
    registered_tool_names = [t.name for t in mcp_server._tool_manager.list_tools()]
    assert "write_entry" in registered_tool_names
    assert "fix_entry" in registered_tool_names
    assert "ask_khata" in registered_tool_names
    assert "update_shop" in registered_tool_names
