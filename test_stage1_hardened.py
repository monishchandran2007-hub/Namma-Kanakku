"""
test_stage1_hardened.py - Comprehensive Unit Tests for Stage 1 Data Model & Exact Accounting.

Covers:
1. Paise exactness & integer thousandths quantities (zero float math).
2. verify_books() auditing: customer balances match sum of ledger entries.
3. verify_books() discrepancy detection: catches even a 1-paisa corruption.
4. Duplicate customer detection ignoring honorifics (anna/akka/ayya/amma/sir/madam).
5. Customer archive & restore: NEVER deletes rows (is_archived flag).
6. Shop modes: "My shop" (starts empty) vs "Demo shop" (deterministic 60-day fake history).
7. Books balanced confirmation returned after every write operation.
"""

import os
import tempfile
import pytest
import sqlite3
from database import (
    init_db,
    seed_demo_data,
    init_my_shop,
    get_connection,
    get_setting,
    set_setting,
    rupees_to_paise,
    paise_to_rupees,
    paise_to_display,
    qty_to_thousandths,
    thousandths_to_qty,
    thousandths_to_display,
    verify_books
)
from matching import match_customer, strip_honorifics
from data_ownership import (
    add_customer,
    archive_customer,
    restore_customer,
    set_item_price,
    add_catalog_item
)
from ledger import (
    log_credit_entry,
    record_payment,
    undo_last_entry,
    get_customer_balance,
    get_overdue_accounts
)
import engine

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix="_kirana_stage1_test.db")
    os.close(fd)
    seed_demo_data(db_path=path, force=True)
    yield path
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


# ============================================================================
# 1. PAISE & THOUSANDTHS EXACTNESS
# ============================================================================

def test_paise_and_thousandths_exactness():
    # 0.1 + 0.2 in floating point is 0.30000000000000004
    # In exact paise, 10 + 20 = 30 paise
    p1 = rupees_to_paise(0.10)
    p2 = rupees_to_paise(0.20)
    p_sum = p1 + p2
    assert p_sum == 30
    assert paise_to_rupees(p_sum) == 0.30

    # Large values
    assert rupees_to_paise(1250.75) == 125075
    assert paise_to_rupees(125075) == 1250.75
    assert paise_to_display(125075) == "Rs 1250.75"
    assert paise_to_display(10000) == "Rs 100"

    # Quantities in thousandths
    assert qty_to_thousandths(0.5) == 500
    assert qty_to_thousandths("half kilo") == 500
    assert qty_to_thousandths("250g") == 250
    assert qty_to_thousandths(2) == 2000
    assert thousandths_to_qty(250) == 0.25
    assert thousandths_to_display(500, "kg") == "0.5 kg"
    assert thousandths_to_display(2000, "packet") == "2 packet"


# ============================================================================
# 2. VERIFY_BOOKS() HEALTHY BOOKS & DEMO DATA AUDIT
# ============================================================================

def test_verify_books_healthy_books(temp_db):
    conn = get_connection(temp_db)
    try:
        vb = verify_books(conn)
        assert vb["balanced"] is True
        assert len(vb["discrepancies"]) == 0
        # Ramesh (450) + Priya (850) + Karthik 3B (100) = 1400.0 Rs = 140000 paise
        assert vb["total_receivables_paise"] == 140000
        assert vb["total_receivables_rupees"] == 1400.0
    finally:
        conn.close()


def test_verify_books_detects_imbalance(temp_db):
    conn = get_connection(temp_db)
    try:
        cur = conn.cursor()
        # Deliberately corrupt Ramesh Teacher's balance by 1 paisa
        cur.execute("UPDATE customers SET current_balance_paise = current_balance_paise + 1 WHERE name = 'Ramesh Teacher'")
        conn.commit()

        vb = verify_books(conn)
        assert vb["balanced"] is False
        assert len(vb["discrepancies"]) == 1
        disc = vb["discrepancies"][0]
        assert disc["customer_name"] == "Ramesh Teacher"
        assert disc["diff_paise"] == 1
        assert disc["stored_balance_paise"] == 45001
        assert disc["calculated_balance_paise"] == 45000
    finally:
        conn.close()


# ============================================================================
# 3. CUSTOMER DUPLICATE CHECK WITH HONORIFIC STRIPPING
# ============================================================================

def test_honorific_stripping():
    assert strip_honorifics("Ramesh Anna") == "ramesh"
    assert strip_honorifics("Priya Akka") == "priya"
    assert strip_honorifics("Murugan Ayya") == "murugan"
    assert strip_honorifics("Selvi Amma") == "selvi"
    assert strip_honorifics("Sundar Sir") == "sundar"
    assert strip_honorifics("Geetha Madam") == "geetha"
    assert strip_honorifics("Karthik") == "karthik"


def test_customer_duplicate_check_with_honorifics(temp_db):
    # 'Ramesh Teacher' exists in demo data.
    # Attempting to add 'Ramesh Anna' should be flagged as suspect duplicate
    res = add_customer("Ramesh Anna", phone="9988776655", db_path=temp_db)
    assert res["success"] is False
    assert res["status"] == "DUPLICATE_SUSPECT"
    assert "Is this the same person as Ramesh Teacher?" in res["spoken_summary"]
    assert res["suspected_match"] == "Ramesh Teacher"

    # Verify nothing was saved in the database
    conn = get_connection(temp_db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM customers WHERE name = 'Ramesh Anna'")
        assert cur.fetchone()[0] == 0
    finally:
        conn.close()

    # Confirmed same person saves nothing new and returns existing customer
    res_confirmed = add_customer("Ramesh Anna", confirm_existing=True, db_path=temp_db)
    assert res_confirmed["success"] is True
    assert res_confirmed["status"] == "EXISTING_CUSTOMER_CONFIRMED"
    assert res_confirmed["customer"]["name"] == "Ramesh Teacher"

    # Distinct person with explicit confirmation adds the new customer
    res_distinct = add_customer("Ramesh Anna", allow_duplicate_name=True, db_path=temp_db)
    assert res_distinct["success"] is True
    assert res_distinct["status"] == "SUCCESS"
    assert res_distinct["customer"]["name"] == "Ramesh Anna"


# ============================================================================
# 4. CUSTOMER ARCHIVE & RESTORE (NEVER DELETES ROWS)
# ============================================================================

def test_customer_archive_and_restore(temp_db):
    # Archive Ramesh Teacher
    arch_res = archive_customer("Ramesh Teacher", db_path=temp_db)
    assert arch_res["success"] is True
    assert arch_res["status"] == "CUSTOMER_ARCHIVED"

    conn = get_connection(temp_db)
    try:
        cur = conn.cursor()
        # Row must still exist in DB (never deleted!)
        cur.execute("SELECT id, name, is_archived, archived_at FROM customers WHERE name = 'Ramesh Teacher'")
        row = cur.fetchone()
        assert row is not None
        assert row["is_archived"] == 1
        assert row["archived_at"] is not None

        # verify_books() must still balance with archived customer's balance & entries preserved
        vb = verify_books(conn)
        assert vb["balanced"] is True

        # Archived customer cannot be matched for new transactions
        match_res = match_customer(conn, "Ramesh Teacher")
        assert match_res["status"] == "NOT_FOUND"
    finally:
        conn.close()

    # Attempting to log credit to archived customer fails
    credit_res = log_credit_entry("Ramesh Teacher", [{"item_name": "toor dal", "quantity": 1}], db_path=temp_db)
    assert credit_res["success"] is False

    # Restore customer
    restore_res = restore_customer("Ramesh Teacher", db_path=temp_db)
    assert restore_res["success"] is True
    assert restore_res["status"] == "CUSTOMER_RESTORED"

    conn = get_connection(temp_db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT is_archived, archived_at FROM customers WHERE name = 'Ramesh Teacher'")
        row = cur.fetchone()
        assert row["is_archived"] == 0
        assert row["archived_at"] is None

        # Customer is searchable and chargeable again
        match_res = match_customer(conn, "Ramesh Teacher")
        assert match_res["status"] == "SUCCESS"
    finally:
        conn.close()


# ============================================================================
# 5. MODES: "MY SHOP" (EMPTY) VS "DEMO SHOP" (60-DAY FAKE HISTORY)
# ============================================================================

def test_my_shop_mode_starts_empty():
    fd, path = tempfile.mkstemp(suffix="_kirana_myshop.db")
    os.close(fd)
    try:
        init_my_shop(db_path=path, shop_name="Sri Murugan Store")
        conn = get_connection(path)
        try:
            cur = conn.cursor()
            # Must start completely EMPTY
            cur.execute("SELECT COUNT(*) FROM customers")
            assert cur.fetchone()[0] == 0

            cur.execute("SELECT COUNT(*) FROM catalog_items")
            assert cur.fetchone()[0] == 0

            cur.execute("SELECT COUNT(*) FROM ledger_entries")
            assert cur.fetchone()[0] == 0

            # Settings
            assert get_setting(conn, "shop_mode") == "my_shop"
            assert get_setting(conn, "shop_name") == "Sri Murugan Store"
            assert get_setting(conn, "wizard_completed") == "0"

            # Books must balance (0 == 0)
            vb = verify_books(conn)
            assert vb["balanced"] is True
            assert vb["total_receivables_paise"] == 0
        finally:
            conn.close()

        # Add item and customer with opening balance in My Shop
        item_res = add_catalog_item(
            sku="sugar_1kg",
            display_name="Sugar 1kg",
            price=45.0,
            cost=38.0,
            unit="kg",
            db_path=path
        )
        assert item_res["success"] is True

        cust_res = add_customer(
            name="Venkatesh",
            phone="9876543210",
            credit_limit=3000.0,
            opening_balance=250.0,
            db_path=path
        )
        assert cust_res["success"] is True
        assert cust_res["customer"]["current_balance"] == 250.0

        # Books must balance after adding opening balance
        conn = get_connection(path)
        try:
            vb = verify_books(conn)
            assert vb["balanced"] is True
            assert vb["total_receivables_paise"] == 25000
        finally:
            conn.close()
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_demo_shop_mode_has_deterministic_60day_history(temp_db):
    conn = get_connection(temp_db)
    try:
        cur = conn.cursor()
        assert get_setting(conn, "shop_mode") == "demo"
        assert "[DEMO DATA]" in get_setting(conn, "shop_name")

        cur.execute("SELECT COUNT(*) FROM customers")
        assert cur.fetchone()[0] == 5

        cur.execute("SELECT COUNT(*) FROM catalog_items")
        assert cur.fetchone()[0] == 8

        cur.execute("SELECT COUNT(*) FROM ledger_entries")
        entry_count = cur.fetchone()[0]
        assert entry_count >= 20  # Spans 60 days of fake history

        # Check all customer balances match entries
        vb = verify_books(conn)
        assert vb["balanced"] is True
        assert vb["total_receivables_rupees"] == 1400.0
    finally:
        conn.close()


# ============================================================================
# 6. BOOKS BALANCED CONFIRMATION IN WRITES
# ============================================================================

def test_books_balanced_reported_on_every_write(temp_db):
    # 1. Credit sale
    res_credit = log_credit_entry("Ramesh Teacher", [{"item_name": "toor dal", "quantity": 1}], db_path=temp_db)
    assert res_credit["success"] is True
    assert res_credit["books_balanced"] is True
    assert res_credit["books_status"] == "Books balanced"
    assert "Books balanced" in res_credit["screen_note"]

    # 2. Payment
    res_payment = record_payment("Ramesh Teacher", 200.0, db_path=temp_db)
    assert res_payment["success"] is True
    assert res_payment["books_balanced"] is True
    assert res_payment["books_status"] == "Books balanced"
    assert "Books balanced" in res_payment["screen_note"]

    # 3. Undo
    res_undo = undo_last_entry("Ramesh Teacher", db_path=temp_db)
    assert res_undo["success"] is True
    assert res_undo["books_balanced"] is True
    assert res_undo["books_status"] == "Books balanced"
    assert "Books balanced" in res_undo["screen_note"]

    # 4. Engine write_entry (CASH_SALE)
    res_engine = engine.write_entry(items=[{"item_name": "curd 500ml", "quantity": 1}], event_type="CASH_SALE", db_path=temp_db)
    assert res_engine["success"] is True
    assert res_engine["books_balanced"] is True
    assert res_engine["books_status"] == "Books balanced"
    assert "Books balanced" in res_engine["screen_note"]
