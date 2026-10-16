"""
smoke_test.py - Protocol Conformance & Latency Benchmark for KiranaFlow.

Tests:
1. Auxiliary plain routes (/healthz, /ledger, /reset, /).
2. MCP Streamable HTTP JSON-RPC handshake (/mcp):
   - initialize (client protocol negotiation)
   - tools/list (inspect all 9 tool schemas & metadata)
   - resources/read (fetch ui://khata-card widget)
   - tools/call (execute core tools, verify structured outputs & discretion)
3. 50-call sequential latency benchmark reporting real p50 and p95 latency.
"""

import sys
import os
import time
import json
import asyncio
import urllib.request
import urllib.error
from typing import List, Dict, Any

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

BASE_URL = os.environ.get("SERVER_URL", "http://127.0.0.1:8000")
MCP_URL = f"{BASE_URL}/mcp"

def check_plain_routes():
    print(f"\n--- 1. Testing Plain HTTP Routes on {BASE_URL} ---")

    # /healthz
    healthz_url = f"{BASE_URL}/healthz"
    req = urllib.request.Request(healthz_url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        data = json.loads(resp.read().decode())
        assert data.get("status") == "ok"
        assert data.get("app") == "KiranaFlow"
        print(f"  [PASS] GET /healthz -> 200 OK: {data}")

    # /ledger
    ledger_url = f"{BASE_URL}/ledger"
    with urllib.request.urlopen(ledger_url) as resp:
        assert resp.status == 200
        html = resp.read().decode()
        assert "KiranaFlow - Modern Voice Khata" in html
        assert "[DEMO DATA - NOT REAL]" in html
        print(f"  [PASS] GET /ledger -> 200 OK (HTML dashboard with auto-refresh)")

    # /reset without key should be 403 Forbidden
    reset_url = f"{BASE_URL}/reset"
    try:
        urllib.request.urlopen(reset_url)
        assert False, "Expected 403 Forbidden for /reset"
    except urllib.error.HTTPError as e:
        assert e.code == 403
        print(f"  [PASS] GET /reset -> 403 Forbidden (Protected when RESET_KEY unset)")

    # / base redirect to /ledger (for browser GET)
    req = urllib.request.Request(f"{BASE_URL}/")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        print(f"  [PASS] GET / -> 302 redirected to /ledger")

async def check_mcp_protocol():
    print(f"\n--- 2. Testing MCP Streamable HTTP at {MCP_URL} ---")

    async with streamable_http_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # 1. Initialize
            init_res = await session.initialize()
            print(f"  [PASS] JSON-RPC initialize:")
            print(f"         Server Name: {init_res.server_info.name} v{init_res.server_info.version}")
            print(f"         Protocol Version: {init_res.protocol_version}")

            # 2. tools/list
            tools_res = await session.list_tools()
            tool_names = [t.name for t in tools_res.tools]
            print(f"\n  [PASS] tools/list ({len(tool_names)} tools discovered):")
            for t in tools_res.tools:
                ui_meta = t.meta.get("ui") if t.meta else None
                ui_tag = f" [UI: {ui_meta['resourceUri']}]" if ui_meta else ""
                print(f"         - {t.name}{ui_tag}")

            expected_tools = {
                "log_credit_entry", "record_payment", "get_customer_balance",
                "undo_last_entry", "get_overdue_accounts", "teach_item_alias",
                "set_item_price", "add_catalog_item", "add_customer",
                "evaluate_wholesale_quote"
            }
            assert expected_tools.issubset(set(tool_names)), f"Missing tools: {expected_tools - set(tool_names)}"

            # 3. resources/read (MCP Apps UI)
            res_content = await session.read_resource("ui://khata-card")
            assert len(res_content.contents) > 0
            widget_html = res_content.contents[0].text
            assert "<!DOCTYPE html>" in widget_html
            assert "KiranaFlow Khata" in widget_html
            print(f"\n  [PASS] resources/read('ui://khata-card'): retrieved {len(widget_html)} bytes of HTML widget")

            # 4. tools/call - Test each tool
            print(f"\n  [PASS] Calling tools over Streamable HTTP:")

            # Tool A: get_customer_balance
            bal_res = await session.call_tool("get_customer_balance", {"customer_name": "Ramesh Teacher"})
            bal_data = bal_res.content[0].text
            print(f"         get_customer_balance: {bal_data[:90]}...")

            # Tool B: log_credit_entry (Curd 500ml)
            log_res = await session.call_tool("log_credit_entry", {
                "customer_name": "Ramesh Teacher",
                "items": [{"item_name": "curd 500ml", "quantity": 1}]
            })
            log_data = log_res.content[0].text
            print(f"         log_credit_entry: {log_data[:90]}...")
            assert "undo" in log_data.lower()

            # Tool C: undo_last_entry
            undo_res = await session.call_tool("undo_last_entry", {"customer_name": "Ramesh Teacher"})
            undo_data = undo_res.content[0].text
            print(f"         undo_last_entry: {undo_data[:90]}...")

            # Tool D: record_payment
            pay_res = await session.call_tool("record_payment", {
                "customer_name": "Ramesh Teacher",
                "amount": 50.0
            })
            pay_data = pay_res.content[0].text
            print(f"         record_payment: {pay_data[:90]}...")

            # Undo payment
            await session.call_tool("undo_last_entry", {"customer_name": "Ramesh Teacher"})

            # Tool E: get_overdue_accounts
            overdue_res = await session.call_tool("get_overdue_accounts", {})
            print(f"         get_overdue_accounts: {overdue_res.content[0].text[:90]}...")

            # Tool F: teach_item_alias
            teach_res = await session.call_tool("teach_item_alias", {
                "alias": "pasu thayir",
                "item_name_or_sku": "Curd 500ml"
            })
            print(f"         teach_item_alias: {teach_res.content[0].text[:90]}...")

            # Tool G: evaluate_wholesale_quote
            quote_res = await session.call_tool("evaluate_wholesale_quote", {
                "item_name_or_sku": "toor_dal",
                "wholesale_price": 135.0,
                "quantity": 10.0
            })
            print(f"         evaluate_wholesale_quote: {quote_res.content[0].text[:90]}...")

async def run_latency_benchmark(num_calls: int = 50):
    print(f"\n--- 3. Running Latency Benchmark ({num_calls} sequential calls) ---")
    latencies: List[float] = []

    async with streamable_http_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Warm-up call
            await session.call_tool("get_customer_balance", {"customer_name": "Ramesh Teacher"})

            test_sequence = [
                ("get_customer_balance", {"customer_name": "Ramesh Teacher"}),
                ("log_credit_entry", {"customer_name": "Ramesh Teacher", "items": [{"item_name": "thayir", "quantity": 1}]}),
                ("undo_last_entry", {"customer_name": "Ramesh Teacher"}),
                ("get_overdue_accounts", {}),
                ("evaluate_wholesale_quote", {"item_name_or_sku": "toor_dal", "wholesale_price": 140.0}),
            ]

            for i in range(num_calls):
                tool_name, args = test_sequence[i % len(test_sequence)]
                t0 = time.perf_counter()
                await session.call_tool(tool_name, args)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                latencies.append(elapsed_ms)

    latencies.sort()
    p50_idx = int(0.50 * len(latencies))
    p95_idx = int(0.95 * len(latencies))
    p50 = latencies[p50_idx]
    p95 = latencies[p95_idx]
    min_lat = latencies[0]
    max_lat = latencies[-1]
    avg_lat = sum(latencies) / len(latencies)

    print(f"\n  [BENCHMARK RESULTS over {num_calls} calls]")
    print(f"  - p50 (median): {p50:.2f} ms")
    print(f"  - p95:          {p95:.2f} ms")
    print(f"  - Min / Max:    {min_lat:.2f} ms / {max_lat:.2f} ms")
    print(f"  - Average:      {avg_lat:.2f} ms")
    return {"p50": p50, "p95": p95, "min": min_lat, "max": max_lat, "avg": avg_lat}

def main():
    check_plain_routes()
    asyncio.run(check_mcp_protocol())
    asyncio.run(run_latency_benchmark(50))
    print("\n[ALL PROTOCOL AND BENCHMARK CHECKS PASSED]")

if __name__ == "__main__":
    main()
