"""
test_stage8.py - Comprehensive Unit Tests for Stage 8 & Stage 9:
- Data-driven classification using intent_lexicon (English, Tamil, Tanglish).
- Customer habit promotion (>=3 confirms, >=80% dominance) and disambiguation questions.
- Multi-event atomic execution (CREDIT_SALE, CASH_SALE, PAYMENT_RECEIVED, RETURN, STOCK_PURCHASE).
- Inventory stock delta tracking, profit calculation, and low stock notices.
- Reversible undo and amend via fix_entry.
- Discretion rules:
  - Spoken summary strictly NEVER reveals customer debt/balance in receipts.
  - Credit check speaks ONLY "Okay" or "Please check the screen".
  - Morning brief speaks counts only.
"""

import os
import json
import pytest
import sqlite3
from database import init_db, seed_demo_data, get_connection
import engine

TEST_DB_PATH = os.path.join(os.path.dirname(__file__), "test_kirana_stage8.db")

@pytest.fixture(autouse=True)
def setup_test_db():
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass
    seed_demo_data(db_path=TEST_DB_PATH, force=True)
    yield
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass


# ============================================================================
# 1. INTENT LEXICON & SCORING TESTS
# ============================================================================

def test_lexicon_scoring_english_credit():
    conn = get_connection(TEST_DB_PATH)
    scores = engine.score_utterance_intent(conn, "put on account please")
    conn.close()
    assert scores.get("CREDIT_SALE", 0) >= 1.0

def test_lexicon_scoring_tanglish_credit():
    conn = get_connection(TEST_DB_PATH)
    scores = engine.score_utterance_intent(conn, "Ramesh teacher ku rendu thayir udhaar")
    conn.close()
    assert scores.get("CREDIT_SALE", 0) >= 1.0

def test_lexicon_scoring_tamil_script_credit():
    conn = get_connection(TEST_DB_PATH)
    # கடன் or கணக்கு
    scores = engine.score_utterance_intent(conn, "ரமேஷ் கணக்கு தயிர் கடன்")
    conn.close()
    assert scores.get("CREDIT_SALE", 0) >= 1.0

def test_lexicon_scoring_tanglish_payment():
    conn = get_connection(TEST_DB_PATH)
    scores = engine.score_utterance_intent(conn, "Priya Madam 200 kuduthaaru")
    conn.close()
    assert scores.get("PAYMENT_RECEIVED", 0) >= 1.0

def test_lexicon_scoring_tamil_script_payment():
    conn = get_connection(TEST_DB_PATH)
    scores = engine.score_utterance_intent(conn, "பிரியா 200 கொடுத்தார்")
    conn.close()
    assert scores.get("PAYMENT_RECEIVED", 0) >= 1.0

def test_lexicon_scoring_cash_sale():
    conn = get_connection(TEST_DB_PATH)
    scores = engine.score_utterance_intent(conn, "one curd cash kaasu")
    conn.close()
    assert scores.get("CASH_SALE", 0) >= 1.0

def test_lexicon_scoring_return():
    conn = get_connection(TEST_DB_PATH)
    scores = engine.score_utterance_intent(conn, "toor dal thiruppi return")
    conn.close()
    assert scores.get("RETURN", 0) >= 1.0

def test_lexicon_scoring_stock_purchase():
    conn = get_connection(TEST_DB_PATH)
    scores = engine.score_utterance_intent(conn, "wholesale sarakku mandi purchase")
    conn.close()
    assert scores.get("STOCK_PURCHASE", 0) >= 1.0


# ============================================================================
# 2. CONFLICT & HABIT DISAMBIGUATION (0 ROWS WRITTEN)
# ============================================================================

def test_conflicting_cues_trigger_question_and_writes_zero_rows():
    conn = get_connection(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM ledger_entries")
    count_before = cur.fetchone()[0]

    res = engine.write_entry(
        utterance="Ramesh Teacher one curd cash udhaar",
        db_path=TEST_DB_PATH
    )
    cur.execute("SELECT COUNT(*) FROM ledger_entries")
    count_after = cur.fetchone()[0]
    conn.close()

    assert res["success"] is False
    assert res["status"] == "NEEDS_CLARIFICATION"
    assert "Did you mean cash sale or credit" in res["spoken_summary"]
    # Strictly zero rows written
    assert count_before == count_after

def test_habit_promoted_credit_customer():
    # Ramesh Teacher is seeded with 3 CREDIT_SALE confirms
    res = engine.write_entry(
        customer_name="Ramesh Teacher",
        items=[{"item_name": "toor dal", "quantity": 1}],
        db_path=TEST_DB_PATH
    )
    assert res["success"] is True
    assert res["status"] == "SUCCESS"
    assert "Logged 1 kg Toor Dal for Ramesh Teacher" in res["spoken_summary"]

    conn = get_connection(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT entry_type FROM ledger_entries ORDER BY seq DESC LIMIT 1")
    assert cur.fetchone()[0] == "CREDIT_SALE"
    conn.close()

def test_habit_promoted_cash_customer():
    # Suresh Electrician is seeded with 3 CASH_SALE confirms
    res = engine.write_entry(
        customer_name="Suresh Electrician",
        items=[{"item_name": "bath soap", "quantity": 1}],
        db_path=TEST_DB_PATH
    )
    assert res["success"] is True
    assert res["status"] == "SUCCESS"
    assert "Cash sale" in res["spoken_summary"]

    conn = get_connection(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT entry_type, customer_id FROM ledger_entries ORDER BY seq DESC LIMIT 1")
    row = cur.fetchone()
    assert row[0] == "CASH_SALE"
    assert row[1] is not None
    conn.close()

def test_unestablished_habit_asks_question_and_writes_zero_rows():
    # Karthik 3B has 0 habit records seeded
    conn = get_connection(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM ledger_entries")
    count_before = cur.fetchone()[0]

    res = engine.write_entry(
        customer_name="Karthik 3B",
        items=[{"item_name": "curd", "quantity": 1}],
        db_path=TEST_DB_PATH
    )
    cur.execute("SELECT COUNT(*) FROM ledger_entries")
    count_after = cur.fetchone()[0]
    conn.close()

    assert res["success"] is False
    assert res["status"] == "NEEDS_CLARIFICATION"
    assert "Should I put this on Karthik 3B's account or was it paid in cash?" in res["spoken_summary"]
    assert count_before == count_after


# ============================================================================
# 3. ATOMIC MULTI-ITEM & BATCH ROLLBACK
# ============================================================================

def test_anonymous_purchase_defaults_to_cash_sale():
    res = engine.write_entry(
        items=[{"item_name": "curd", "quantity": 2}],
        db_path=TEST_DB_PATH
    )
    assert res["success"] is True
    assert "Cash sale of 70 rupees logged" in res["spoken_summary"]

    conn = get_connection(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT entry_type, customer_id, amount FROM ledger_entries ORDER BY seq DESC LIMIT 1")
    row = cur.fetchone()
    assert row["entry_type"] == "CASH_SALE"
    assert row["customer_id"] is None
    assert row["amount"] == 70.0
    conn.close()

def test_atomic_rollback_on_unrecognized_item():
    conn = get_connection(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT stock FROM catalog_items WHERE sku = 'curd_500ml'")
    curd_stock_before = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ledger_entries")
    entry_count_before = cur.fetchone()[0]

    # One valid item, one invalid item
    res = engine.write_entry(
        customer_name="Ramesh Teacher",
        items=[
            {"item_name": "curd", "quantity": 2},
            {"item_name": "non_existent_item_xyz", "quantity": 1}
        ],
        event_type="CREDIT_SALE",
        db_path=TEST_DB_PATH
    )

    cur.execute("SELECT stock FROM catalog_items WHERE sku = 'curd_500ml'")
    curd_stock_after = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ledger_entries")
    entry_count_after = cur.fetchone()[0]
    conn.close()

    assert res["success"] is False
    assert res["status"] == "ITEM_NOT_RECOGNIZED"
    # Strict atomicity: curd stock unchanged, zero entries saved
    assert curd_stock_after == curd_stock_before
    assert entry_count_after == entry_count_before


# ============================================================================
# 4. INVENTORY STOCK DELTAS & PROFIT TRACKING
# ============================================================================

def test_stock_decrement_on_credit_sale():
    conn = get_connection(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT stock FROM catalog_items WHERE sku = 'sunflower_oil_1l'")
    stock_before = cur.fetchone()[0]

    res = engine.write_entry(
        customer_name="Ramesh Teacher",
        items=[{"item_name": "sunflower oil", "quantity": 2}],
        event_type="CREDIT_SALE",
        db_path=TEST_DB_PATH
    )
    assert res["success"] is True

    cur.execute("SELECT stock FROM catalog_items WHERE sku = 'sunflower_oil_1l'")
    stock_after = cur.fetchone()[0]
    assert stock_after == stock_before - 2.0

    cur.execute("SELECT cost_amount, stock_delta_json FROM ledger_entries ORDER BY seq DESC LIMIT 1")
    row = cur.fetchone()
    # Sunflower oil cost is 120.0, 2 units -> 240.0
    assert row["cost_amount"] == 240.0
    deltas = json.loads(row["stock_delta_json"])
    assert deltas["sunflower_oil_1l"] == -2.0
    conn.close()

def test_stock_increment_on_return():
    conn = get_connection(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT stock FROM catalog_items WHERE sku = 'toor_dal'")
    stock_before = cur.fetchone()[0]

    res = engine.write_entry(
        customer_name="Ramesh Teacher",
        items=[{"item_name": "toor dal", "quantity": 1}],
        event_type="RETURN",
        db_path=TEST_DB_PATH
    )
    assert res["success"] is True

    cur.execute("SELECT stock FROM catalog_items WHERE sku = 'toor_dal'")
    stock_after = cur.fetchone()[0]
    assert stock_after == stock_before + 1.0
    conn.close()

def test_stock_purchase_increments_stock():
    conn = get_connection(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT stock FROM catalog_items WHERE sku = 'curd_500ml'")
    stock_before = cur.fetchone()[0]

    res = engine.write_entry(
        items=[{"item_name": "curd", "quantity": 20}],
        event_type="STOCK_PURCHASE",
        db_path=TEST_DB_PATH
    )
    assert res["success"] is True

    cur.execute("SELECT stock FROM catalog_items WHERE sku = 'curd_500ml'")
    stock_after = cur.fetchone()[0]
    assert stock_after == stock_before + 20.0
    conn.close()


# ============================================================================
# 5. REVERSIBLE UNDO & AMEND (fix_entry)
# ============================================================================

def test_fix_entry_undo_restores_balance_and_stock():
    conn = get_connection(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT current_balance FROM customers WHERE name = 'Ramesh Teacher'")
    bal_initial = cur.fetchone()[0]
    cur.execute("SELECT stock FROM catalog_items WHERE sku = 'toor_dal'")
    stock_initial = cur.fetchone()[0]

    # Make credit sale
    res_entry = engine.write_entry(
        customer_name="Ramesh Teacher",
        items=[{"item_name": "toor dal", "quantity": 1}],
        event_type="CREDIT_SALE",
        db_path=TEST_DB_PATH
    )
    assert res_entry["success"] is True

    # Call undo via fix_entry
    res_undo = engine.fix_entry(action="undo", db_path=TEST_DB_PATH)
    assert res_undo["success"] is True
    assert "Undone last entry" in res_undo["spoken_summary"]

    cur.execute("SELECT current_balance FROM customers WHERE name = 'Ramesh Teacher'")
    bal_restored = cur.fetchone()[0]
    cur.execute("SELECT stock FROM catalog_items WHERE sku = 'toor_dal'")
    stock_restored = cur.fetchone()[0]
    conn.close()

    assert bal_restored == bal_initial
    assert stock_restored == stock_initial

def test_fix_entry_undo_payment_restores_last_payment_date():
    conn = get_connection(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT current_balance, last_payment_date FROM customers WHERE name = 'Ramesh Teacher'")
    row_init = cur.fetchone()
    bal_initial = row_init["current_balance"]
    date_initial = row_init["last_payment_date"]

    # Record payment
    res_pay = engine.write_entry(
        customer_name="Ramesh Teacher",
        amount=100.0,
        event_type="PAYMENT_RECEIVED",
        db_path=TEST_DB_PATH
    )
    assert res_pay["success"] is True

    # Undo payment
    res_undo = engine.fix_entry(action="undo", customer_name="Ramesh Teacher", db_path=TEST_DB_PATH)
    assert res_undo["success"] is True

    cur.execute("SELECT current_balance, last_payment_date FROM customers WHERE name = 'Ramesh Teacher'")
    row_after = cur.fetchone()
    conn.close()

    assert row_after["current_balance"] == bal_initial
    assert row_after["last_payment_date"] == date_initial

def test_fix_entry_amend_replaces_entry_atomically():
    conn = get_connection(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT stock FROM catalog_items WHERE sku = 'curd_500ml'")
    stock_initial = cur.fetchone()[0]

    # Log 1 curd
    engine.write_entry(
        customer_name="Ramesh Teacher",
        items=[{"item_name": "curd", "quantity": 1}],
        event_type="CREDIT_SALE",
        db_path=TEST_DB_PATH
    )

    # Amend to 2 curds
    res_amend = engine.fix_entry(
        action="amend",
        amend_fields={
            "customer_name": "Ramesh Teacher",
            "items": [{"item_name": "curd", "quantity": 2}],
            "event_type": "CREDIT_SALE"
        },
        db_path=TEST_DB_PATH
    )
    assert res_amend["success"] is True
    assert "Logged 2 packet Curd 500ml" in res_amend["spoken_summary"]

    cur.execute("SELECT stock FROM catalog_items WHERE sku = 'curd_500ml'")
    stock_after = cur.fetchone()[0]
    conn.close()

    # Stock should reflect only 2 units subtracted from initial
    assert stock_after == stock_initial - 2.0


# ============================================================================
# 6. DISCRETION RULES (Strict Voice Privacy)
# ============================================================================

def test_credit_sale_spoken_summary_never_speaks_balance_or_debt_warning():
    # Ramesh Teacher has 450 initial balance, 35 days unpaid (overdue)
    res = engine.write_entry(
        customer_name="Ramesh Teacher",
        items=[{"item_name": "curd", "quantity": 1}],
        event_type="CREDIT_SALE",
        db_path=TEST_DB_PATH
    )
    spoken = res["spoken_summary"].lower()
    # Must NOT speak the new balance (485) or previous balance (450)
    assert "485" not in spoken
    assert "450" not in spoken
    assert "balance" not in spoken
    assert "overdue" not in spoken
    assert "unpaid" not in spoken
    # But screen note DOES include overdue warning
    assert "Unpaid for" in res["screen_note"]

def test_payment_spoken_summary_never_speaks_remaining_balance():
    # Ramesh has 450 dues. Pays 100.
    res = engine.write_entry(
        customer_name="Ramesh Teacher",
        amount=100.0,
        event_type="PAYMENT_RECEIVED",
        db_path=TEST_DB_PATH
    )
    spoken = res["spoken_summary"].lower()
    # Spoken must confirm 100 received, but NOT speak remaining balance (350)
    assert "100" in spoken
    assert "350" not in spoken
    assert "remaining" not in spoken
    assert "balance" not in spoken


# ============================================================================
# 7. STAGE 9: QUIET CREDIT CHECK, MORNING BRIEF & TODAY SUMMARY
# ============================================================================

def test_credit_check_overdue_customer_speaks_strictly_check_the_screen():
    # Ramesh Teacher is 35 days overdue (> 30 days)
    res = engine.ask_khata(
        question="credit check for Ramesh Teacher",
        kind="credit_check",
        customer_name="Ramesh Teacher",
        amount=200.0,
        db_path=TEST_DB_PATH
    )
    assert res["success"] is True
    # STRICT DISCRETION: Spoken MUST be exactly "Please check the screen."
    assert res["spoken_summary"] == "Please check the screen."
    # Detailed warning on screen note
    assert "Credit Check Warning" in res["screen_note"]
    assert "Unpaid for" in res["screen_note"]
    assert res["structured_data"]["approved"] is False

def test_credit_check_good_customer_speaks_okay():
    # Suresh Electrician has 0 balance and recent payment
    res = engine.ask_khata(
        question="credit check for Suresh Electrician",
        kind="credit_check",
        customer_name="Suresh Electrician",
        amount=100.0,
        db_path=TEST_DB_PATH
    )
    assert res["success"] is True
    assert res["spoken_summary"] == "Okay."
    assert res["structured_data"]["approved"] is True

def test_morning_brief_speaks_counts_only():
    res = engine.ask_khata(
        question="give me the morning brief",
        kind="morning_brief",
        db_path=TEST_DB_PATH
    )
    assert res["success"] is True
    spoken = res["spoken_summary"]
    # Speaks counts only, never individual customer names aloud
    assert "overdue accounts" in spoken
    assert "items low on stock" in spoken
    assert "Ramesh Teacher" not in spoken
    assert "Priya Madam" not in spoken
    # But screen note contains the account names
    assert "Overdue:" in res["screen_note"]

def test_today_summary_calculates_sales_and_profit():
    # Make a cash sale (retail 160, cost 135 -> profit 25)
    engine.write_entry(
        items=[{"item_name": "toor dal", "quantity": 1}],
        event_type="CASH_SALE",
        db_path=TEST_DB_PATH
    )
    # Make a credit sale (retail 70, cost 56 -> profit 14)
    engine.write_entry(
        customer_name="Ramesh Teacher",
        items=[{"item_name": "curd", "quantity": 2}],
        event_type="CREDIT_SALE",
        db_path=TEST_DB_PATH
    )
    # Total sales = 230, total cost = 191, gross profit = 39

    res = engine.ask_khata(
        question="what is today's summary",
        kind="today_summary",
        db_path=TEST_DB_PATH
    )
    assert res["success"] is True
    spoken = res["spoken_summary"]
    assert "Cash sales 160" in spoken
    assert "credit 70" in spoken
    assert "profit 39" in spoken
    assert res["structured_data"]["estimated_gross_profit"] == 39.0

def test_explicit_balance_query_speaks_balance():
    res = engine.ask_khata(
        question="what is Ramesh Teacher's balance?",
        kind="balance",
        customer_name="Ramesh Teacher",
        db_path=TEST_DB_PATH
    )
    assert res["success"] is True
    # Spoken balance is permitted when explicitly requested by shopkeeper
    assert "current balance is 450 rupees" in res["spoken_summary"]


# ============================================================================
# 8. UPDATE SHOP DATA-OWNERSHIP TOOL
# ============================================================================

def test_update_shop_teach_alias():
    res = engine.update_shop(
        action="teach_alias",
        alias="paruppu thool",
        item_name_or_sku="toor_dal",
        db_path=TEST_DB_PATH
    )
    assert res["success"] is True

    # Test the learned alias in matching
    conn = get_connection(TEST_DB_PATH)
    m_res = engine.match_item(conn, "paruppu thool")
    conn.close()
    assert m_res["status"] == "SUCCESS"
    assert m_res["sku"] == "toor_dal"

def test_update_shop_set_price():
    res = engine.update_shop(
        action="set_price",
        item_name_or_sku="toor_dal",
        new_price=175.0,
        db_path=TEST_DB_PATH
    )
    assert res["success"] is True

    conn = get_connection(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT price FROM catalog_items WHERE sku = 'toor_dal'")
    assert cur.fetchone()[0] == 175.0
    conn.close()

def test_update_shop_add_customer():
    res = engine.update_shop(
        action="add_customer",
        customer_name="Anand Tailor",
        phone="9800000099",
        credit_limit=2500.0,
        db_path=TEST_DB_PATH
    )
    assert res["success"] is True

    conn = get_connection(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name, credit_limit FROM customers WHERE name = 'Anand Tailor'")
    row = cur.fetchone()
    assert row["name"] == "Anand Tailor"
    assert row["credit_limit"] == 2500.0
    conn.close()
