"""
test_stage1.py - Automated Test Suite for KiranaFlow Stage 1 Core Hardening.

Covers:
1. Ambiguous customer ("Karthik" -> ambiguous between Karthik 3B and Karthik 5A)
2. "Ramesh tab" -> Ramesh Teacher (filler-word stripping)
3. Ambiguous item "oil" -> needs clarification
4. Unknown item saves nothing -> atomicity check
5. Half kilo toor dal -> 0.5 * 160 = Rs 80
6. Tanglish aliases (thayir, thuvaram paruppu, kadala ennai, arisi)
7. Spelling variants (tuvaram, thoovaram paruppu)
8. Tamil script "தயிர்" -> Curd 500ml
9. english_guess resolves an unlisted word
10. Fuzzy typo accepted (rapidfuzz WRatio >= 90, gap >= 8)
11. Fuzzy ambiguity rejected (close candidates require clarification)
12. Learned alias promoted after two confirmations ("I understood X as Y")
13. Atomicity (1 valid item + 1 invalid item -> 0 rows written in ledger)
14. Payment capped at balance (paying 600 against 450 balance caps at 450)
15. Undo credit entry restores previous balance
16. Undo payment restores last_payment_date
17. Nothing to undo handled gracefully
18. Overdue accounts ordered by days overdue descending
19. Discretion in log_credit_entry (no balance/limit in spoken_summary)
20. Discretion in record_payment (no balance in spoken_summary)
21. Discretion in undo_last_entry (no balance in spoken_summary)
22. Overdue nudge in screen_note for 30+ days unpaid
23. Spoken balance allowed in get_customer_balance
24. Grams conversion (250g toor dal = Rs 40)
"""

import os
import tempfile
import pytest
from database import init_db, seed_demo_data, get_connection
from matching import (
    transliterate_tamil,
    make_phonetic_key,
    normalize_text,
    match_customer,
    match_item,
    record_learned_confirmation
)
from ledger import (
    log_credit_entry,
    record_payment,
    get_customer_balance,
    undo_last_entry,
    get_overdue_accounts
)

@pytest.fixture
def test_db():
    """Provides a fresh temporary SQLite database seeded with labelled demo data."""
    fd, path = tempfile.mkstemp(suffix="_kirana_test.db")
    os.close(fd)
    seed_demo_data(db_path=path, force=True)
    yield path
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

# Test 1: Ambiguous customer
def test_ambiguous_customer(test_db):
    conn = get_connection(test_db)
    res = match_customer(conn, "Karthik")
    conn.close()
    assert res["status"] == "CUSTOMER_AMBIGUOUS"
    assert "Karthik 3B" in res["options"]
    assert "Karthik 5A" in res["options"]

# Test 2: "Ramesh tab" filler stripping
def test_ramesh_tab_filler_stripped(test_db):
    conn = get_connection(test_db)
    res = match_customer(conn, "Ramesh tab")
    conn.close()
    assert res["status"] == "SUCCESS"
    assert res["customer"]["name"] == "Ramesh Teacher"

# Test 3: Ambiguous item "oil"
def test_ambiguous_item_oil(test_db):
    conn = get_connection(test_db)
    res = match_item(conn, "oil")
    conn.close()
    assert res["status"] == "NEEDS_CLARIFICATION"
    assert len(res["options"]) >= 2
    assert "Sunflower Oil 1L" in res["options"]
    assert "Groundnut Oil 1L" in res["options"]

# Test 4: Unknown item saves nothing
def test_unknown_item_saves_nothing(test_db):
    conn = get_connection(test_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM ledger_entries")
    count_before = cur.fetchone()[0]
    conn.close()

    res = log_credit_entry("Ramesh Teacher", [{"item_name": "unknown_spaceship_part", "quantity": 1}], db_path=test_db)
    assert res["success"] is False
    assert res["status"] == "ITEM_NOT_RECOGNIZED"

    conn = get_connection(test_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM ledger_entries")
    assert cur.fetchone()[0] == count_before
    conn.close()

# Test 5: Half kilo toor dal
def test_half_kilo_toor_dal(test_db):
    res = log_credit_entry("Ramesh Teacher", [{"item_name": "toor dal", "quantity": "half kilo"}], db_path=test_db)
    assert res["success"] is True
    assert res["status"] == "SUCCESS"
    # Toor dal price is 160/kg, half kilo = 80
    assert res["structured_data"]["total_amount"] == 80.0
    assert "80 rupees" in res["spoken_summary"] or "80.0" in res["spoken_summary"] or "80" in res["spoken_summary"]

# Test 6: Tanglish aliases
def test_tanglish_aliases(test_db):
    conn = get_connection(test_db)
    # thayir -> Curd 500ml
    r1 = match_item(conn, "thayir")
    assert r1["status"] == "SUCCESS"
    assert r1["display_name"] == "Curd 500ml"

    # thuvaram paruppu -> Toor Dal
    r2 = match_item(conn, "thuvaram paruppu")
    assert r2["status"] == "SUCCESS"
    assert r2["display_name"] == "Toor Dal"

    # kadala ennai -> Groundnut Oil 1L
    r3 = match_item(conn, "kadala ennai")
    assert r3["status"] == "SUCCESS"
    assert r3["display_name"] == "Groundnut Oil 1L"

    # arisi -> Ponni Rice
    r4 = match_item(conn, "arisi")
    assert r4["status"] == "SUCCESS"
    assert r4["display_name"] == "Ponni Rice"
    conn.close()

# Test 7: Spelling variants via phonetic key
def test_spelling_variants_phonetic(test_db):
    conn = get_connection(test_db)
    # tuvaram
    r1 = match_item(conn, "tuvaram")
    assert r1["status"] == "SUCCESS"
    assert r1["display_name"] == "Toor Dal"

    # thoovaram paruppu (with 'oo' and 'th')
    r2 = match_item(conn, "thoovaram paruppu")
    assert r2["status"] == "SUCCESS"
    assert r2["display_name"] == "Toor Dal"
    conn.close()

# Test 8: Tamil script "தயிர்"
def test_tamil_script_transliteration(test_db):
    conn = get_connection(test_db)
    r = match_item(conn, "தயிர்")
    conn.close()
    assert r["status"] == "SUCCESS"
    assert r["display_name"] == "Curd 500ml"

# Test 9: english_guess resolves unlisted word
def test_english_guess_resolves_unlisted_word(test_db):
    conn = get_connection(test_db)
    # Spoken word is arbitrary/unlisted, english_guess provides "curd"
    r = match_item(conn, "vellai_katti", english_guess="curd")
    conn.close()
    assert r["status"] == "SUCCESS"
    assert r["display_name"] == "Curd 500ml"
    assert r["used_english_guess"] is True

# Test 10: Fuzzy typo accepted (WRatio >= 90, gap >= 8)
def test_fuzzy_typo_accepted(test_db):
    conn = get_connection(test_db)
    # Minor typo "sunflowr oil"
    r = match_item(conn, "sunflowr oil")
    conn.close()
    assert r["status"] == "SUCCESS"
    assert r["display_name"] == "Sunflower Oil 1L"
    assert r["match_type"] == "FUZZY"

# Test 11: Fuzzy ambiguity rejected
def test_fuzzy_ambiguity_rejected(test_db):
    conn = get_connection(test_db)
    # "oil packet" matches both sunflower and groundnut oil closely
    r = match_item(conn, "oil packet")
    conn.close()
    assert r["status"] == "NEEDS_CLARIFICATION"
    assert len(r["options"]) >= 2

# Test 12: Learned alias promoted after two confirmations
def test_learned_alias_promotion(test_db):
    conn = get_connection(test_db)
    # Ambiguous term "soap" initially needs clarification
    r_init = match_item(conn, "soap")
    assert r_init["status"] == "NEEDS_CLARIFICATION"

    # Confirm twice for bath_soap
    record_learned_confirmation(conn, "soap", "bath_soap")
    record_learned_confirmation(conn, "soap", "bath_soap")

    # Now it must auto-resolve with note "I understood soap as Bathing Soap 100g"
    r_learned = match_item(conn, "soap")
    conn.close()
    assert r_learned["status"] == "SUCCESS"
    assert r_learned["display_name"] == "Bathing Soap 100g"
    assert "I understood soap as Bathing Soap 100g" in r_learned["learned_note"]

# Test 13: Atomicity (multi-item partial failure writes 0 rows)
def test_atomicity_multi_item_failure(test_db):
    conn = get_connection(test_db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ledger_entries")
        count_before = cur.fetchone()[0]
    finally:
        conn.close()

    items = [
        {"item_name": "toor dal", "quantity": 1},
        {"item_name": "non_existent_unobtanium", "quantity": 1}
    ]
    res = log_credit_entry("Ramesh Teacher", items, db_path=test_db)
    assert res["success"] is False

    conn = get_connection(test_db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ledger_entries")
        assert cur.fetchone()[0] == count_before

        # Customer balance must remain unchanged
        cur.execute("SELECT current_balance FROM customers WHERE name = 'Ramesh Teacher'")
        assert cur.fetchone()[0] == 450.0
    finally:
        conn.close()

# Test 14: Payment capped at balance
def test_payment_capped_at_balance(test_db):
    # Ramesh has balance 450.0. Pay 600.0.
    res = record_payment("Ramesh Teacher", 600.0, db_path=test_db)
    assert res["success"] is True
    assert res["structured_data"]["payment_amount"] == 450.0
    assert res["structured_data"]["new_balance"] == 0.0

    conn = get_connection(test_db)
    cur = conn.cursor()
    cur.execute("SELECT current_balance FROM customers WHERE name = 'Ramesh Teacher'")
    assert cur.fetchone()[0] == 0.0
    conn.close()

# Test 15: Undo credit entry restores previous balance
def test_undo_credit_entry(test_db):
    # Ramesh has balance 450. Log 100g toor dal (160 * 0.1 = 16.0)
    log_credit_entry("Ramesh Teacher", [{"item_name": "toor dal", "quantity": "100g"}], db_path=test_db)
    bal_res = get_customer_balance("Ramesh Teacher", db_path=test_db)
    assert bal_res["structured_data"]["current_balance"] == 466.0

    undo_res = undo_last_entry("Ramesh Teacher", db_path=test_db)
    assert undo_res["success"] is True
    assert undo_res["structured_data"]["restored_balance"] == 450.0

    bal_after = get_customer_balance("Ramesh Teacher", db_path=test_db)
    assert bal_after["structured_data"]["current_balance"] == 450.0

# Test 16: Undo payment restores last_payment_date
def test_undo_payment_restores_last_payment(test_db):
    conn = get_connection(test_db)
    cur = conn.cursor()
    cur.execute("SELECT last_payment_date FROM customers WHERE name = 'Ramesh Teacher'")
    orig_date = cur.fetchone()[0]
    conn.close()

    # Record payment
    record_payment("Ramesh Teacher", 100.0, db_path=test_db)

    # Undo payment
    undo_res = undo_last_entry("Ramesh Teacher", db_path=test_db)
    assert undo_res["success"] is True

    conn = get_connection(test_db)
    cur = conn.cursor()
    cur.execute("SELECT last_payment_date, current_balance FROM customers WHERE name = 'Ramesh Teacher'")
    restored_row = cur.fetchone()
    assert restored_row[0] == orig_date
    assert restored_row[1] == 450.0
    conn.close()

# Test 17: Nothing to undo
def test_nothing_to_undo(test_db):
    res = undo_last_entry(db_path=test_db)
    assert res["success"] is False
    assert res["status"] == "NOTHING_TO_UNDO"
    assert "no recent entries to undo" in res["spoken_summary"]

# Test 18: Overdue accounts ordering
def test_overdue_accounts_ordering(test_db):
    res = get_overdue_accounts(db_path=test_db)
    assert res["success"] is True
    accounts = res["structured_data"]["accounts"]
    assert len(accounts) >= 2
    # Priya Madam (40 days) should come before Ramesh Teacher (35 days)
    assert accounts[0]["name"] == "Priya Madam"
    assert accounts[1]["name"] == "Ramesh Teacher"
    assert accounts[0]["days_overdue"] >= accounts[1]["days_overdue"]

# Test 19: Discretion in log_credit_entry
def test_discretion_log_credit(test_db):
    res = log_credit_entry("Ramesh Teacher", [{"item_name": "curd 500ml", "quantity": 1}], db_path=test_db)
    spoken = res["spoken_summary"].lower()
    # Customer balance is 450 + 35 = 485. Balance or limit must NOT be spoken!
    assert "485" not in spoken
    assert "balance" not in spoken
    assert "limit" not in spoken
    assert "say undo if that's wrong" in spoken

# Test 20: Discretion in record_payment
def test_discretion_record_payment(test_db):
    res = record_payment("Ramesh Teacher", 50.0, db_path=test_db)
    spoken = res["spoken_summary"].lower()
    # Remaining balance is 400. Balance must NOT be spoken!
    assert "400" not in spoken
    assert "remaining" not in spoken
    assert "balance" not in spoken
    assert "50 rupees" in spoken or "50" in spoken

# Test 21: Discretion in undo_last_entry
def test_discretion_undo(test_db):
    log_credit_entry("Ramesh Teacher", [{"item_name": "curd 500ml", "quantity": 1}], db_path=test_db)
    undo_res = undo_last_entry("Ramesh Teacher", db_path=test_db)
    spoken = undo_res["spoken_summary"].lower()
    assert "balance" not in spoken
    assert "450" not in spoken

# Test 22: Overdue nudge in screen_note
def test_overdue_nudge_screen_note(test_db):
    # Ramesh is unpaid for 35 days (>30). Screen note must include overdue notice.
    res = log_credit_entry("Ramesh Teacher", [{"item_name": "curd 500ml", "quantity": 1}], db_path=test_db)
    assert res["screen_note"] is not None
    assert "unpaid for 35 days" in res["screen_note"].lower()
    # Spoken summary must NOT speak the overdue nudge
    assert "unpaid" not in res["spoken_summary"].lower()

# Test 23: Balance spoken when explicitly requested in get_customer_balance
def test_spoken_balance_allowed_for_get_balance(test_db):
    res = get_customer_balance("Ramesh Teacher", db_path=test_db)
    spoken = res["spoken_summary"].lower()
    assert "450" in spoken
    assert "balance" in spoken

# Test 24: Unit gram conversion
def test_unit_gram_conversion(test_db):
    # 250g of toor dal @ 160/kg = 0.25 * 160 = Rs 40.0
    res = log_credit_entry("Ramesh Teacher", [{"item_name": "toor dal", "quantity": 250, "unit": "g"}], db_path=test_db)
    assert res["success"] is True
    assert res["structured_data"]["total_amount"] == 40.0
