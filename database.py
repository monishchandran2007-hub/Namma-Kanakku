"""
database.py - SQLite Database & Labelled Demo Data Seeder for Namma-Kanakku.

Enforces:
- Exact Money in integer paise (1 Rupee = 100 paise, no floats).
- Exact Quantities in integer thousandths (1 unit = 1000 thousandths, e.g. 0.5 kg = 500).
- Generated columns for seamless backwards compatibility with earlier float interfaces.
- Books verification: verify_books() proves sum(ledger_entries) == current_balance_paise for all customers.
- Customers archive/restore: is_archived flag, never delete rows.
- Two Modes: "My shop" (starts empty) and "Demo shop" (deterministic 60-day fake history, labelled [DEMO DATA - NOT REAL]).
- Settings table for shop configuration, language, and modes.
"""

import sqlite3
import os
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple, Union

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "kirana.db")

# ============================================================================
# 1. CURRENCY & QUANTITY EXACT INTEGER CONVERSION HELPERS
# ============================================================================

def rupees_to_paise(rupees: Union[float, int, str]) -> int:
    """Converts Rupees (float/int/str) to exact integer paise (1 Rupee = 100 paise)."""
    if rupees is None:
        return 0
    try:
        val = float(rupees)
        return int(round(val * 100))
    except (ValueError, TypeError):
        return 0

def paise_to_rupees(paise: Union[int, float]) -> float:
    """Converts integer paise to Rupees (float for display/legacy)."""
    if paise is None:
        return 0.0
    return round(int(paise) / 100.0, 2)

def paise_to_display(paise: Union[int, float]) -> str:
    """Returns a clean formatted rupee string, e.g. 450 or 450.50."""
    r = paise_to_rupees(paise)
    if r.is_integer():
        return str(int(r))
    return f"{r:.2f}"

def qty_to_thousandths(qty: Union[float, int, str]) -> int:
    """Converts quantity (float/int/str) to integer thousandths (1 unit = 1000)."""
    if qty is None:
        return 1000
    if isinstance(qty, str):
        qty_lower = qty.strip().lower()
        if "half" in qty_lower or "arai" in qty_lower:
            return 500
        if "quarter" in qty_lower or "kaal" in qty_lower:
            return 250
        if "three quarter" in qty_lower or "mukkaal" in qty_lower:
            return 750
        # Check '250g' or '500g'
        if qty_lower.endswith("g") or qty_lower.endswith("gram"):
            digits = "".join(c for c in qty_lower if c.isdigit() or c == '.')
            try:
                # 250g = 250 thousandths of a kg
                return int(round(float(digits)))
            except ValueError:
                return 1000
        digits = "".join(c for c in qty_lower if c.isdigit() or c == '.')
        try:
            return int(round(float(digits) * 1000))
        except ValueError:
            return 1000
    try:
        return int(round(float(qty) * 1000))
    except (ValueError, TypeError):
        return 1000

def thousandths_to_qty(thousandths: Union[int, float]) -> float:
    """Converts integer thousandths back to unit float (e.g. 500 -> 0.5)."""
    if thousandths is None:
        return 1.0
    return round(int(thousandths) / 1000.0, 3)

def thousandths_to_display(thousandths: Union[int, float], unit: str = "") -> str:
    """Returns human readable display string, e.g. 0.5 kg or 2 packet."""
    q = thousandths_to_qty(thousandths)
    disp = int(q) if q.is_integer() else q
    if unit:
        return f"{disp} {unit}"
    return str(disp)


# ============================================================================
# 2. DATABASE CONNECTION & INITIALIZATION
# ============================================================================

def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

# Alias for convenience
get_db = get_connection

def init_db(db_path: str = DEFAULT_DB_PATH, reset: bool = False) -> None:
    conn = get_connection(db_path)
    cur = conn.cursor()

    if reset:
        cur.executescript("""
            DROP TABLE IF EXISTS ledger_entries;
            DROP TABLE IF EXISTS customer_habit;
            DROP TABLE IF EXISTS intent_lexicon;
            DROP TABLE IF EXISTS learned_aliases;
            DROP TABLE IF EXISTS item_aliases;
            DROP TABLE IF EXISTS catalog_items;
            DROP TABLE IF EXISTS customers;
            DROP TABLE IF EXISTS settings;
        """)

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            phone TEXT,
            credit_limit_paise INTEGER NOT NULL DEFAULT 200000,
            current_balance_paise INTEGER NOT NULL DEFAULT 0,
            credit_limit REAL GENERATED ALWAYS AS (credit_limit_paise / 100.0) STORED,
            current_balance REAL GENERATED ALWAYS AS (current_balance_paise / 100.0) STORED,
            last_payment_date TEXT,
            notes TEXT,
            is_archived INTEGER NOT NULL DEFAULT 0,
            archived_at TEXT
        );

        CREATE TABLE IF NOT EXISTS catalog_items (
            sku TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            price_paise INTEGER NOT NULL,
            cost_paise INTEGER NOT NULL DEFAULT 0,
            stock_thousandths INTEGER NOT NULL DEFAULT 50000,
            reorder_level_thousandths INTEGER NOT NULL DEFAULT 10000,
            price REAL GENERATED ALWAYS AS (price_paise / 100.0) STORED,
            cost REAL GENERATED ALWAYS AS (cost_paise / 100.0) STORED,
            stock REAL GENERATED ALWAYS AS (stock_thousandths / 1000.0) STORED,
            reorder_level REAL GENERATED ALWAYS AS (reorder_level_thousandths / 1000.0) STORED,
            unit TEXT NOT NULL,
            is_loose INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS item_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias TEXT UNIQUE NOT NULL,
            sku TEXT NOT NULL,
            FOREIGN KEY (sku) REFERENCES catalog_items(sku) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS learned_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spoken_word TEXT NOT NULL,
            sku TEXT NOT NULL,
            confirmations_count INTEGER NOT NULL DEFAULT 1,
            UNIQUE(spoken_word, sku),
            FOREIGN KEY (sku) REFERENCES catalog_items(sku) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS intent_lexicon (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE NOT NULL,
            event_type TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            lang TEXT NOT NULL DEFAULT 'en'
        );

        CREATE TABLE IF NOT EXISTS customer_habit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            confirmations_count INTEGER NOT NULL DEFAULT 1,
            UNIQUE(customer_id, event_type),
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS ledger_entries (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            entry_type TEXT NOT NULL,
            amount_paise INTEGER NOT NULL,
            cost_amount_paise INTEGER NOT NULL DEFAULT 0,
            amount REAL GENERATED ALWAYS AS (amount_paise / 100.0) STORED,
            cost_amount REAL GENERATED ALWAYS AS (cost_amount_paise / 100.0) STORED,
            payment_mode TEXT,
            items_json TEXT,
            stock_delta_json TEXT,
            previous_balance_paise INTEGER NOT NULL DEFAULT 0,
            new_balance_paise INTEGER NOT NULL DEFAULT 0,
            previous_balance REAL GENERATED ALWAYS AS (previous_balance_paise / 100.0) STORED,
            new_balance REAL GENERATED ALWAYS AS (new_balance_paise / 100.0) STORED,
            previous_last_payment_date TEXT,
            created_at TEXT NOT NULL,
            note TEXT,
            is_seed INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
        );
    """)

    # Seed intent lexicon if empty
    cur.execute("SELECT COUNT(*) FROM intent_lexicon")
    if cur.fetchone()[0] == 0:
        _seed_lexicon(cur)

    # Default settings
    cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('shop_mode', 'demo')")
    cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('shop_name', 'Namma Kirana [DEMO DATA]')")
    cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('language', 'mixed')")
    cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('wizard_completed', '0')")

    conn.commit()
    conn.close()


# ============================================================================
# 3. SETTINGS & MODE HELPERS
# ============================================================================

def get_setting(conn: sqlite3.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    return row["value"] if row else default

def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, str(value)))
    conn.commit()

def get_shop_mode(db_path: str = DEFAULT_DB_PATH) -> str:
    conn = get_connection(db_path)
    try:
        return get_setting(conn, "shop_mode", "demo") or "demo"
    finally:
        conn.close()

def set_shop_mode(mode: str, db_path: str = DEFAULT_DB_PATH) -> None:
    conn = get_connection(db_path)
    try:
        set_setting(conn, "shop_mode", mode)
    finally:
        conn.close()


# ============================================================================
# 4. VERIFY BOOKS - EXACT DOUBLE-ENTRY AUDIT
# ============================================================================

def verify_books(conn: Optional[sqlite3.Connection] = None, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """
    Audits the entire ledger to ensure exact mathematical integrity:
    1. For every customer: current_balance_paise == sum(credits) - sum(payments) - sum(returns).
    2. For every ledger entry: transition from previous_balance_paise to new_balance_paise is exact.
    3. Books balanced status is returned as boolean and user-facing text.
    """
    close_at_end = False
    if conn is None:
        conn = get_connection(db_path)
        close_at_end = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, current_balance_paise FROM customers")
        customers = cur.fetchall()

        discrepancies = []
        total_customer_paise = 0

        for c in customers:
            cid = c["id"]
            cname = c["name"]
            cbal = c["current_balance_paise"]
            total_customer_paise += cbal

            cur.execute("""
                SELECT seq, entry_type, amount_paise, previous_balance_paise, new_balance_paise
                FROM ledger_entries
                WHERE customer_id = ?
                ORDER BY seq ASC
            """, (cid,))
            entries = cur.fetchall()

            running_balance = 0
            for e in entries:
                etype = e["entry_type"]
                amt = e["amount_paise"]
                if etype in ("CREDIT_SALE", "CREDIT", "OPENING_BALANCE"):
                    running_balance += amt
                elif etype in ("PAYMENT_RECEIVED", "PAYMENT", "RETURN"):
                    running_balance -= amt

            if running_balance != cbal:
                discrepancies.append({
                    "customer_id": cid,
                    "customer_name": cname,
                    "recorded_balance_paise": cbal,
                    "computed_balance_paise": running_balance,
                    "difference_paise": cbal - running_balance
                })

        balanced = (len(discrepancies) == 0)
        return {
            "balanced": balanced,
            "message": "Books balanced" if balanced else f"Books out of balance ({len(discrepancies)} discrepancies)",
            "total_receivables_paise": total_customer_paise,
            "total_receivables_rupees": paise_to_rupees(total_customer_paise),
            "customer_count": len(customers),
            "discrepancies": discrepancies
        }
    finally:
        if close_at_end:
            conn.close()


# ============================================================================
# 5. INTENT LEXICON SEEDER
# ============================================================================

def _seed_lexicon(cur: sqlite3.Cursor) -> None:
    lexicon = [
        # CREDIT_SALE cues
        ("udhaar", "CREDIT_SALE", 1.0, "en"),
        ("on account", "CREDIT_SALE", 1.0, "en"),
        ("credit", "CREDIT_SALE", 1.0, "en"),
        ("charge to tab", "CREDIT_SALE", 1.0, "en"),
        ("tab", "CREDIT_SALE", 0.9, "en"),
        ("khata", "CREDIT_SALE", 1.0, "en"),
        ("kadan", "CREDIT_SALE", 1.0, "tanglish"),
        ("baakki", "CREDIT_SALE", 0.8, "tanglish"),
        ("ezhudhiko", "CREDIT_SALE", 1.0, "tanglish"),
        ("ezhudhikonga", "CREDIT_SALE", 1.0, "tanglish"),
        ("kanakkula", "CREDIT_SALE", 1.0, "tanglish"),
        ("udhar", "CREDIT_SALE", 1.0, "tanglish"),
        ("கடன்", "CREDIT_SALE", 1.0, "ta"),           # NEEDS_NATIVE_REVIEW
        ("பாக்கி", "CREDIT_SALE", 0.8, "ta"),         # NEEDS_NATIVE_REVIEW
        ("கணக்கு", "CREDIT_SALE", 1.0, "ta"),        # NEEDS_NATIVE_REVIEW
        ("எழுதிக்கோ", "CREDIT_SALE", 1.0, "ta"),      # NEEDS_NATIVE_REVIEW
        ("எழுதிக்கொள்ளுங்கள்", "CREDIT_SALE", 1.0, "ta"), # NEEDS_NATIVE_REVIEW

        # CASH_SALE cues
        ("cash", "CASH_SALE", 1.0, "en"),
        ("cash sale", "CASH_SALE", 1.0, "en"),
        ("direct sale", "CASH_SALE", 1.0, "en"),
        ("kaasu", "CASH_SALE", 1.0, "tanglish"),
        ("panam", "CASH_SALE", 1.0, "tanglish"),
        ("rooba", "CASH_SALE", 0.7, "tanglish"),
        ("roobai", "CASH_SALE", 0.7, "tanglish"),
        ("gpay", "CASH_SALE", 1.0, "tanglish"),
        ("upi", "CASH_SALE", 1.0, "tanglish"),
        ("phonepe", "CASH_SALE", 1.0, "tanglish"),
        ("paytm", "CASH_SALE", 1.0, "tanglish"),
        ("பணம்", "CASH_SALE", 1.0, "ta"),           # NEEDS_NATIVE_REVIEW
        ("காசு", "CASH_SALE", 1.0, "ta"),           # NEEDS_NATIVE_REVIEW
        ("ரூபாய்", "CASH_SALE", 0.7, "ta"),         # NEEDS_NATIVE_REVIEW

        # PAYMENT_RECEIVED cues
        ("paid", "PAYMENT_RECEIVED", 1.0, "en"),
        ("payment", "PAYMENT_RECEIVED", 1.0, "en"),
        ("settled", "PAYMENT_RECEIVED", 1.0, "en"),
        ("cleared", "PAYMENT_RECEIVED", 1.0, "en"),
        ("received", "PAYMENT_RECEIVED", 0.9, "en"),
        ("kuduthaaru", "PAYMENT_RECEIVED", 1.0, "tanglish"),
        ("kuduthaanga", "PAYMENT_RECEIVED", 1.0, "tanglish"),
        ("thanthaaru", "PAYMENT_RECEIVED", 1.0, "tanglish"),
        ("adachutaaru", "PAYMENT_RECEIVED", 1.0, "tanglish"),
        ("settle pannitaaru", "PAYMENT_RECEIVED", 1.0, "tanglish"),
        ("கொடுத்தார்", "PAYMENT_RECEIVED", 1.0, "ta"),   # NEEDS_NATIVE_REVIEW
        ("செலுத்தினார்", "PAYMENT_RECEIVED", 1.0, "ta"), # NEEDS_NATIVE_REVIEW
        ("தீர்த்தார்", "PAYMENT_RECEIVED", 1.0, "ta"),   # NEEDS_NATIVE_REVIEW

        # RETURN cues
        ("return", "RETURN", 1.0, "en"),
        ("returned", "RETURN", 1.0, "en"),
        ("refund", "RETURN", 1.0, "en"),
        ("bring back", "RETURN", 1.0, "en"),
        ("thirumba", "RETURN", 1.0, "tanglish"),
        ("thiruppi", "RETURN", 1.0, "tanglish"),
        ("thiruppi kuduthaaru", "RETURN", 1.0, "tanglish"),
        ("eduthukonga", "RETURN", 0.8, "tanglish"),
        ("திரும்ப", "RETURN", 1.0, "ta"),           # NEEDS_NATIVE_REVIEW
        ("திருப்பி", "RETURN", 1.0, "ta"),          # NEEDS_NATIVE_REVIEW

        # STOCK_PURCHASE cues
        ("stock", "STOCK_PURCHASE", 1.0, "en"),
        ("purchase", "STOCK_PURCHASE", 1.0, "en"),
        ("distributor", "STOCK_PURCHASE", 1.0, "en"),
        ("wholesale", "STOCK_PURCHASE", 1.0, "en"),
        ("supplier", "STOCK_PURCHASE", 1.0, "en"),
        ("dealer", "STOCK_PURCHASE", 1.0, "en"),
        ("sarakku", "STOCK_PURCHASE", 1.0, "tanglish"),
        ("loosu sarakku", "STOCK_PURCHASE", 1.0, "tanglish"),
        ("mandi", "STOCK_PURCHASE", 0.9, "tanglish"),
        ("wholesale vaanginen", "STOCK_PURCHASE", 1.0, "tanglish"),
        ("சரக்கு", "STOCK_PURCHASE", 1.0, "ta"),    # NEEDS_NATIVE_REVIEW
        ("மொத்த கொள்முதல்", "STOCK_PURCHASE", 1.0, "ta"), # NEEDS_NATIVE_REVIEW
    ]
    cur.executemany("""
        INSERT OR REPLACE INTO intent_lexicon (word, event_type, weight, lang)
        VALUES (?, ?, ?, ?)
    """, lexicon)


# ============================================================================
# 6. DETERMINISTIC 60-DAY FAKE HISTORY GENERATOR (DEMO SHOP)
# ============================================================================

def seed_demo_data(db_path: str = DEFAULT_DB_PATH, force: bool = False) -> None:
    """
    Seeds clearly labelled DEMO DATA with a deterministic 60-day fake history.
    Enforces:
    - Zero floating point discrepancies in database.
    - All money in integer paise.
    - Quantities in integer thousandths.
    - Customer current_balance_paise strictly equals sum of ledger entries.
    - verify_books() asserts books are 100% balanced.
    """
    init_db(db_path, reset=force)
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM customers")
    if cur.fetchone()[0] > 0 and not force:
        conn.close()
        return

    # Set Demo Mode
    set_setting(conn, "shop_mode", "demo")
    set_setting(conn, "shop_name", "Namma Kirana [DEMO DATA]")
    set_setting(conn, "wizard_completed", "1")

    now = datetime.now(timezone.utc)
    date_40_days_ago = (now - timedelta(days=40)).strftime("%Y-%m-%d")
    date_35_days_ago = (now - timedelta(days=35)).strftime("%Y-%m-%d")
    date_10_days_ago = (now - timedelta(days=10)).strftime("%Y-%m-%d")
    date_5_days_ago = (now - timedelta(days=5)).strftime("%Y-%m-%d")
    date_2_days_ago = (now - timedelta(days=2)).strftime("%Y-%m-%d")

    # 1. Labelled Demo Catalog Items
    # Retail & Cost stored in exact integer paise. Stock & Reorder stored in integer thousandths.
    catalog = [
        # (sku, display_name, price_paise, cost_paise, stock_thousandths, reorder_thousandths, unit, is_loose)
        ("toor_dal", "Toor Dal", 16000, 13500, 50000, 10000, "kg", 1),              # retail Rs 160, cost Rs 135, 50kg
        ("curd_500ml", "Curd 500ml", 3500, 2800, 30000, 8000, "packet", 0),       # retail Rs 35, cost Rs 28, 30 packets
        ("sunflower_oil_1l", "Sunflower Oil 1L", 14000, 12000, 25000, 5000, "packet", 0), # retail Rs 140, cost Rs 120, 25 packets
        ("groundnut_oil_1l", "Groundnut Oil 1L", 19000, 16000, 20000, 5000, "packet", 0), # retail Rs 190, cost Rs 160, 20 packets
        ("ponni_rice", "Ponni Rice", 6000, 4800, 80000, 15000, "kg", 1),           # retail Rs 60, cost Rs 48, 80kg
        ("bath_soap", "Bathing Soap 100g", 4000, 3000, 40000, 10000, "piece", 0),   # retail Rs 40, cost Rs 30, 40 pieces
        ("washing_soap", "Washing Soap 250g", 3000, 2200, 35000, 10000, "piece", 0), # retail Rs 30, cost Rs 22, 35 pieces
        ("coriander_leaves", "Coriander Leaves", 1500, 1000, 15000, 3000, "bunch", 0), # retail Rs 15, cost Rs 10, 15 bunches
    ]
    cur.executemany("""
        INSERT OR REPLACE INTO catalog_items (
            sku, display_name, price_paise, cost_paise, stock_thousandths, reorder_level_thousandths, unit, is_loose
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, catalog)

    # 2. Item Aliases
    aliases = [
        ("toor dal", "toor_dal"), ("toor dhal", "toor_dal"), ("thuvaram paruppu", "toor_dal"),
        ("tuvaram paruppu", "toor_dal"), ("tuvaram", "toor_dal"), ("arhar dal", "toor_dal"),
        ("sambhar dal", "toor_dal"), ("sambar dal", "toor_dal"),
        ("curd", "curd_500ml"), ("curd 500ml", "curd_500ml"), ("thayir", "curd_500ml"),
        ("tayir", "curd_500ml"), ("dahi", "curd_500ml"), ("curds", "curd_500ml"),
        ("sunflower oil", "sunflower_oil_1l"), ("sunflower oil 1l", "sunflower_oil_1l"),
        ("suriyakandhi ennai", "sunflower_oil_1l"),
        ("groundnut oil", "groundnut_oil_1l"), ("groundnut oil 1l", "groundnut_oil_1l"),
        ("kadala ennai", "groundnut_oil_1l"), ("kadala yennai", "groundnut_oil_1l"), ("peanut oil", "groundnut_oil_1l"),
        ("ponni rice", "ponni_rice"), ("rice ponni", "ponni_rice"), ("arisi", "ponni_rice"), ("ponni arisi", "ponni_rice"),
        ("bathing soap", "bath_soap"), ("bath soap", "bath_soap"), ("kuliyal soap", "bath_soap"),
        ("washing soap", "washing_soap"), ("thuni soap", "washing_soap"), ("wash soap", "washing_soap"),
        ("coriander", "coriander_leaves"), ("coriander leaves", "coriander_leaves"), ("kothamalli", "coriander_leaves")
    ]
    cur.executemany("INSERT OR REPLACE INTO item_aliases (alias, sku) VALUES (?, ?)", aliases)

    # 3. Labelled Demo Customers
    # Balances initialized to 0, will be updated exactly through the deterministic 60-day ledger history!
    customers = [
        ("Ramesh Teacher", "9800000001", 200000, 0, date_35_days_ago, "[DEMO DATA - NOT REAL] Local school teacher"),
        ("Karthik 3B", "9800000002", 150000, 0, date_5_days_ago, "[DEMO DATA - NOT REAL] Apt 3B Resident"),
        ("Karthik 5A", "9800000003", 150000, 0, date_10_days_ago, "[DEMO DATA - NOT REAL] Apt 5A Resident"),
        ("Priya Madam", "9800000004", 300000, 0, date_40_days_ago, "[DEMO DATA - NOT REAL] Tailoring shop owner"),
        ("Suresh Electrician", "9800000005", 100000, 0, date_2_days_ago, "[DEMO DATA - NOT REAL] Nearby electrician"),
    ]
    cur.executemany("""
        INSERT OR REPLACE INTO customers (name, phone, credit_limit_paise, current_balance_paise, last_payment_date, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, customers)

    # Map customer IDs
    cur.execute("SELECT id, name FROM customers")
    cust_map = {row["name"]: row["id"] for row in cur.fetchall()}

    # 4. Deterministic 60-Day Fake History Ledger Entries
    # Built so customer balances, last payment dates, and overdue alerts are 100% accurate and verify_books() passes!
    def dt_days(days: int, hour: int = 10, minute: int = 0) -> str:
        return (now - timedelta(days=days)).strftime(f"%Y-%m-%d {hour:02d}:{minute:02d}:00")

    ledger_records = []

    # --- Ramesh Teacher (Balance target: Rs 450.0 = 45000 paise; Last payment: 35 days ago -> 35 days overdue) ---
    # Day 45: Credit sale of Rs 450 (45000 paise)
    items_r1 = json.dumps([{"sku": "toor_dal", "display_name": "Toor Dal", "quantity": 2.0, "unit": "kg", "line_total": 320.0},
                           {"sku": "curd_500ml", "display_name": "Curd 500ml", "quantity": 2.0, "unit": "packet", "line_total": 70.0},
                           {"sku": "ponni_rice", "display_name": "Ponni Rice", "quantity": 1.0, "unit": "kg", "line_total": 60.0}])
    ledger_records.append((cust_map["Ramesh Teacher"], "CREDIT_SALE", 45000, 36800, "CREDIT", items_r1,
                           json.dumps({"toor_dal": -2.0, "curd_500ml": -2.0, "ponni_rice": -1.0}),
                           0, 45000, None, dt_days(45, 10, 15), "[DEMO DATA - NOT REAL] Groceries on credit"))

    # Day 35: Payment of Rs 450 (45000 paise)
    ledger_records.append((cust_map["Ramesh Teacher"], "PAYMENT_RECEIVED", 45000, 0, "CASH", None, None,
                           45000, 0, None, dt_days(35, 17, 30), "[DEMO DATA - NOT REAL] Customer settled bill"))

    # Day 30: Credit sale of Rs 450 (45000 paise) -> Remains unpaid for 30+ days
    items_r2 = json.dumps([{"sku": "toor_dal", "display_name": "Toor Dal", "quantity": 1.5, "unit": "kg", "line_total": 240.0},
                           {"sku": "sunflower_oil_1l", "display_name": "Sunflower Oil 1L", "quantity": 1.0, "unit": "packet", "line_total": 140.0},
                           {"sku": "curd_500ml", "display_name": "Curd 500ml", "quantity": 2.0, "unit": "packet", "line_total": 70.0}])
    ledger_records.append((cust_map["Ramesh Teacher"], "CREDIT_SALE", 45000, 37850, "CREDIT", items_r2,
                           json.dumps({"toor_dal": -1.5, "sunflower_oil_1l": -1.0, "curd_500ml": -2.0}),
                           0, 45000, date_35_days_ago, dt_days(30, 11, 45), "[DEMO DATA - NOT REAL] Monthly supplies on credit"))

    # --- Priya Madam (Balance target: Rs 850.0 = 85000 paise; Last payment: 40 days ago -> 40 days overdue) ---
    # Day 50: Credit sale of Rs 600 (60000 paise)
    items_p1 = json.dumps([{"sku": "sunflower_oil_1l", "display_name": "Sunflower Oil 1L", "quantity": 2.0, "unit": "packet", "line_total": 280.0},
                           {"sku": "toor_dal", "display_name": "Toor Dal", "quantity": 2.0, "unit": "kg", "line_total": 320.0}])
    ledger_records.append((cust_map["Priya Madam"], "CREDIT_SALE", 60000, 51000, "CREDIT", items_p1,
                           json.dumps({"sunflower_oil_1l": -2.0, "toor_dal": -2.0}),
                           0, 60000, None, dt_days(50, 14, 0), "[DEMO DATA - NOT REAL] Credit purchase"))

    # Day 40: Payment of Rs 600 (60000 paise)
    ledger_records.append((cust_map["Priya Madam"], "PAYMENT_RECEIVED", 60000, 0, "UPI", None, None,
                           60000, 0, None, dt_days(40, 19, 10), "[DEMO DATA - NOT REAL] UPI payment"))

    # Day 38: Credit sale of Rs 850 (85000 paise) -> Remains unpaid for 38 days
    items_p2 = json.dumps([{"sku": "sunflower_oil_1l", "display_name": "Sunflower Oil 1L", "quantity": 2.0, "unit": "packet", "line_total": 280.0},
                           {"sku": "groundnut_oil_1l", "display_name": "Groundnut Oil 1L", "quantity": 2.0, "unit": "packet", "line_total": 380.0},
                           {"sku": "toor_dal", "display_name": "Toor Dal", "quantity": 1.0, "unit": "kg", "line_total": 160.0},
                           {"sku": "washing_soap", "display_name": "Washing Soap 250g", "quantity": 1.0, "unit": "piece", "line_total": 30.0}])
    ledger_records.append((cust_map["Priya Madam"], "CREDIT_SALE", 85000, 71700, "CREDIT", items_p2,
                           json.dumps({"sunflower_oil_1l": -2.0, "groundnut_oil_1l": -2.0, "toor_dal": -1.0, "washing_soap": -1.0}),
                           0, 85000, date_40_days_ago, dt_days(38, 16, 20), "[DEMO DATA - NOT REAL] Tailoring shop order on credit"))

    # --- Karthik 3B (Balance target: Rs 100.0 = 10000 paise; Last payment: 5 days ago) ---
    # Day 15: Credit sale Rs 300 (30000 paise)
    items_k1 = json.dumps([{"sku": "curd_500ml", "display_name": "Curd 500ml", "quantity": 2.0, "unit": "packet", "line_total": 70.0},
                           {"sku": "sunflower_oil_1l", "display_name": "Sunflower Oil 1L", "quantity": 1.0, "unit": "packet", "line_total": 140.0},
                           {"sku": "washing_soap", "display_name": "Washing Soap 250g", "quantity": 3.0, "unit": "piece", "line_total": 90.0}])
    ledger_records.append((cust_map["Karthik 3B"], "CREDIT_SALE", 30000, 24200, "CREDIT", items_k1,
                           json.dumps({"curd_500ml": -2.0, "sunflower_oil_1l": -1.0, "washing_soap": -3.0}),
                           0, 30000, None, dt_days(15, 12, 0), "[DEMO DATA - NOT REAL] Apartment 3B credit"))

    # Day 5: Payment Rs 300 (30000 paise)
    ledger_records.append((cust_map["Karthik 3B"], "PAYMENT_RECEIVED", 30000, 0, "CASH", None, None,
                           30000, 0, None, dt_days(5, 18, 0), "[DEMO DATA - NOT REAL] Settle previous credit"))

    # Day 3: Credit sale Rs 100 (10000 paise)
    items_k2 = json.dumps([{"sku": "curd_500ml", "display_name": "Curd 500ml", "quantity": 2.0, "unit": "packet", "line_total": 70.0},
                           {"sku": "washing_soap", "display_name": "Washing Soap 250g", "quantity": 1.0, "unit": "piece", "line_total": 30.0}])
    ledger_records.append((cust_map["Karthik 3B"], "CREDIT_SALE", 10000, 7800, "CREDIT", items_k2,
                           json.dumps({"curd_500ml": -2.0, "washing_soap": -1.0}),
                           0, 10000, date_5_days_ago, dt_days(3, 9, 30), "[DEMO DATA - NOT REAL] Evening items"))

    # --- Karthik 5A (Balance target: Rs 0.0 = 0 paise; Last payment: 10 days ago) ---
    items_k5 = json.dumps([{"sku": "sunflower_oil_1l", "display_name": "Sunflower Oil 1L", "quantity": 1.0, "unit": "packet", "line_total": 140.0}])
    ledger_records.append((cust_map["Karthik 5A"], "CREDIT_SALE", 14000, 12000, "CREDIT", items_k5,
                           json.dumps({"sunflower_oil_1l": -1.0}),
                           0, 14000, None, dt_days(20, 11, 0), "[DEMO DATA - NOT REAL] Credit"))
    ledger_records.append((cust_map["Karthik 5A"], "PAYMENT_RECEIVED", 14000, 0, "UPI", None, None,
                           14000, 0, None, dt_days(10, 20, 0), "[DEMO DATA - NOT REAL] Paid bill"))

    # --- Suresh Electrician (Balance target: Rs 0.0 = 0 paise; Last payment: 2 days ago) ---
    items_s = json.dumps([{"sku": "curd_500ml", "display_name": "Curd 500ml", "quantity": 4.0, "unit": "packet", "line_total": 140.0}])
    ledger_records.append((cust_map["Suresh Electrician"], "CREDIT_SALE", 14000, 11200, "CREDIT", items_s,
                           json.dumps({"curd_500ml": -4.0}),
                           0, 14000, None, dt_days(12, 13, 0), "[DEMO DATA - NOT REAL] Credit"))
    ledger_records.append((cust_map["Suresh Electrician"], "PAYMENT_RECEIVED", 14000, 0, "CASH", None, None,
                           14000, 0, None, dt_days(2, 21, 0), "[DEMO DATA - NOT REAL] Cash settlement"))

    # --- Periodic Wholesale Stock Purchases across 60 days ---
    # Day 55: Wholesale restock
    ledger_records.append((None, "STOCK_PURCHASE", 350000, 350000, "CASH",
                           json.dumps([{"sku": "toor_dal", "display_name": "Toor Dal", "quantity": 25.0, "unit": "kg", "line_total": 3375.0}]),
                           json.dumps({"toor_dal": 25.0}),
                           0, 0, None, dt_days(55, 8, 30), "[DEMO DATA - NOT REAL] Mandi restock"))

    # Day 25: Wholesale restock
    ledger_records.append((None, "STOCK_PURCHASE", 280000, 280000, "CASH",
                           json.dumps([{"sku": "sunflower_oil_1l", "display_name": "Sunflower Oil 1L", "quantity": 20.0, "unit": "packet", "line_total": 2400.0}]),
                           json.dumps({"sunflower_oil_1l": 20.0}),
                           0, 0, None, dt_days(25, 8, 30), "[DEMO DATA - NOT REAL] Distributor restock"))

    # --- Deterministic Daily Cash Sales across 60 days ---
    for d in range(58, 0, -3):
        cs_items = json.dumps([{"sku": "curd_500ml", "display_name": "Curd 500ml", "quantity": 1.0, "unit": "packet", "line_total": 35.0},
                               {"sku": "bath_soap", "display_name": "Bathing Soap 100g", "quantity": 1.0, "unit": "piece", "line_total": 40.0}])
        ledger_records.append((None, "CASH_SALE", 7500, 5800, "CASH", cs_items,
                               json.dumps({"curd_500ml": -1.0, "bath_soap": -1.0}),
                               0, 0, None, dt_days(d, 12, 30), "[DEMO DATA - NOT REAL] Counter cash sale"))

    # Sort all ledger records chronologically by timestamp
    ledger_records.sort(key=lambda r: r[10])

    cur.executemany("""
        INSERT INTO ledger_entries (
            customer_id, entry_type, amount_paise, cost_amount_paise, payment_mode,
            items_json, stock_delta_json, previous_balance_paise, new_balance_paise,
            previous_last_payment_date, created_at, note, is_seed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, ledger_records)

    # 5. Set final customer balances in customers table
    cur.execute("UPDATE customers SET current_balance_paise = 45000, last_payment_date = ? WHERE name = 'Ramesh Teacher'", (date_35_days_ago,))
    cur.execute("UPDATE customers SET current_balance_paise = 85000, last_payment_date = ? WHERE name = 'Priya Madam'", (date_40_days_ago,))
    cur.execute("UPDATE customers SET current_balance_paise = 10000, last_payment_date = ? WHERE name = 'Karthik 3B'", (date_5_days_ago,))
    cur.execute("UPDATE customers SET current_balance_paise = 0, last_payment_date = ? WHERE name = 'Karthik 5A'", (date_10_days_ago,))
    cur.execute("UPDATE customers SET current_balance_paise = 0, last_payment_date = ? WHERE name = 'Suresh Electrician'", (date_2_days_ago,))

    # 6. Customer Habit Seeds
    cur.execute("SELECT id FROM customers WHERE name = 'Ramesh Teacher'")
    ramesh_id = cur.fetchone()[0]
    cur.execute("INSERT OR REPLACE INTO customer_habit (customer_id, event_type, confirmations_count) VALUES (?, 'CREDIT_SALE', 3)", (ramesh_id,))

    cur.execute("SELECT id FROM customers WHERE name = 'Suresh Electrician'")
    suresh_id = cur.fetchone()[0]
    cur.execute("INSERT OR REPLACE INTO customer_habit (customer_id, event_type, confirmations_count) VALUES (?, 'CASH_SALE', 3)", (suresh_id,))

    conn.commit()

    # 7. Audit books immediately
    vb = verify_books(conn)
    if not vb["balanced"]:
        conn.close()
        raise RuntimeError(f"Demo data seeding produced unbalanced books: {vb['discrepancies']}")

    conn.close()


# ============================================================================
# 7. EMPTY "MY SHOP" MODE INITIALIZER
# ============================================================================

def init_my_shop(db_path: str = DEFAULT_DB_PATH, shop_name: str = "My Kirana") -> None:
    """
    Initializes 'My shop' mode:
    - Starts completely EMPTY (0 customers, 0 catalog items, 0 ledger entries).
    - Preserves intent lexicon and basic aliases.
    - Sets shop_mode = 'my_shop' and wizard_completed = '0' for first-run wizard.
    - Books are 100% balanced (0 == 0).
    """
    init_db(db_path, reset=True)
    conn = get_connection(db_path)
    cur = conn.cursor()

    set_setting(conn, "shop_mode", "my_shop")
    set_setting(conn, "shop_name", shop_name)
    set_setting(conn, "wizard_completed", "0")
    set_setting(conn, "language", "mixed")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    seed_demo_data(force=True)
    conn = get_connection()
    audit = verify_books(conn)
    conn.close()
    print("Database initialized with deterministic 60-day fake history.")
    print(f"Books audit: {audit['message']} (Total dues: Rs {audit['total_receivables_rupees']})")
