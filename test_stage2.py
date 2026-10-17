"""
test_stage2.py - Automated Test Suite for KiranaFlow Stage 2 Data-Ownership Tools.

Verifies:
1. teach then use: Teach a custom alias, then immediately log an entry using it.
2. price change affects next total: Voice price update applies to next calculation while preserving historical ledger entries.
3. new customer chargeable: Adding a new customer allows charging immediately.
4. duplicate customer rejected: Attempting to add an existing customer (even case-insensitive) is rejected.
5. add catalog item then charge: Registering a new SKU with custom aliases allows immediate use.
6. invalid inputs rejected: Negative prices or empty customer names return structured validation errors.
"""

import os
import tempfile
import pytest
from database import seed_demo_data, get_connection
from ledger import log_credit_entry, get_customer_balance
from data_ownership import (
    teach_item_alias,
    set_item_price,
    add_catalog_item,
    add_customer
)

@pytest.fixture
def test_db():
    fd, path = tempfile.mkstemp(suffix="_kirana_stage2.db")
    os.close(fd)
    seed_demo_data(db_path=path, force=True)
    yield path
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

# Test 1: Teach then use
def test_teach_then_use(test_db):
    # 'kothamalli' is unlisted or custom. Teach it to map to 'coriander_leaves'
    teach_res = teach_item_alias("kothamalli thazhai", "Coriander Leaves", db_path=test_db)
    assert teach_res["success"] is True
    assert teach_res["structured_data"]["sku"] == "coriander_leaves"
    assert "linked" in teach_res["spoken_summary"].lower()

    # Immediately use the taught alias in a credit transaction
    log_res = log_credit_entry(
        "Ramesh Teacher",
        [{"item_name": "kothamalli thazhai", "quantity": 2}],
        db_path=test_db
    )
    assert log_res["success"] is True
    # Coriander is 15.0 per bunch, 2 bunches = Rs 30
    assert log_res["structured_data"]["total_amount"] == 30.0
    assert log_res["structured_data"]["items"][0]["display_name"] == "Coriander Leaves"

# Test 2: Price change affects next total, preserves historical ledger
def test_price_change_affects_next_total_preserves_history(test_db):
    # 1. Log entry with initial price (Toor Dal = Rs 160/kg)
    r1 = log_credit_entry("Ramesh Teacher", [{"item_name": "toor dal", "quantity": 1}], db_path=test_db)
    assert r1["structured_data"]["total_amount"] == 160.0

    # 2. Update price to Rs 185/kg
    price_res = set_item_price("Toor Dal", 185.0, db_path=test_db)
    assert price_res["success"] is True
    assert price_res["structured_data"]["new_price"] == 185.0
    assert "185" in price_res["spoken_summary"]

    # 3. Log entry with new price
    r2 = log_credit_entry("Ramesh Teacher", [{"item_name": "toor dal", "quantity": 1}], db_path=test_db)
    assert r2["structured_data"]["total_amount"] == 185.0

    # 4. Verify historical ledger entry 1 still recorded original Rs 160
    conn = get_connection(test_db)
    cur = conn.cursor()
    cur.execute("SELECT amount FROM ledger_entries WHERE is_seed = 0 ORDER BY seq ASC")
    amounts = [row[0] for row in cur.fetchall()]
    assert amounts == [160.0, 185.0]
    conn.close()

# Test 3: New customer chargeable
def test_new_customer_chargeable(test_db):
    # Add new customer
    cust_res = add_customer("Murugan Carpenter", phone="9800000099", credit_limit=2500.0, db_path=test_db)
    assert cust_res["success"] is True
    assert cust_res["structured_data"]["name"] == "Murugan Carpenter"
    assert cust_res["structured_data"]["current_balance"] == 0.0

    # Immediately charge the new customer
    log_res = log_credit_entry(
        "Murugan Carpenter",
        [{"item_name": "curd 500ml", "quantity": 2}],
        db_path=test_db
    )
    assert log_res["success"] is True
    # 2 * 35 = Rs 70
    assert log_res["structured_data"]["total_amount"] == 70.0
    assert log_res["structured_data"]["current_balance"] == 70.0

    # Check balance
    bal_res = get_customer_balance("Murugan Carpenter", db_path=test_db)
    assert bal_res["structured_data"]["current_balance"] == 70.0

# Test 4: Duplicate customer rejected
def test_duplicate_customer_rejected(test_db):
    # 'Ramesh Teacher' already exists in seeded demo data
    res1 = add_customer("Ramesh Teacher", phone="9800000001", db_path=test_db)
    assert res1["success"] is False
    assert res1["status"] == "DUPLICATE_CUSTOMER"
    assert "already exists" in res1["spoken_summary"]

    # Test case-insensitive duplicate
    res2 = add_customer("ramesh teacher", db_path=test_db)
    assert res2["success"] is False
    assert res2["status"] == "DUPLICATE_CUSTOMER"

# Test 5: Add catalog item with aliases and charge
def test_add_catalog_item_then_charge(test_db):
    item_res = add_catalog_item(
        sku="organic_jaggery_1kg",
        display_name="Organic Jaggery 1kg",
        price=95.0,
        unit="packet",
        is_loose=False,
        aliases=["vellam", "bellam", "gur"],
        db_path=test_db
    )
    assert item_res["success"] is True
    assert item_res["structured_data"]["sku"] == "organic_jaggery_1kg"

    # Charge using alias "vellam"
    log_res = log_credit_entry(
        "Ramesh Teacher",
        [{"item_name": "vellam", "quantity": 1}],
        db_path=test_db
    )
    assert log_res["success"] is True
    assert log_res["structured_data"]["total_amount"] == 95.0
    assert log_res["structured_data"]["items"][0]["display_name"] == "Organic Jaggery 1kg"

# Test 6: Validation errors on invalid inputs
def test_validation_errors(test_db):
    # Invalid price <= 0
    p_err = set_item_price("Toor Dal", -20.0, db_path=test_db)
    assert p_err["success"] is False
    assert p_err["status"] == "INVALID_PRICE"

    # Empty customer name
    c_err = add_customer("   ", db_path=test_db)
    assert c_err["success"] is False
    assert c_err["status"] == "INVALID_NAME"
