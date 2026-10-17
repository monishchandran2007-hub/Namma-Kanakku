"""
database.py - SQLite Database & Labelled Demo Data Seeder for Namma-Kanakku.

Enforces:
- Stateless SQLite persistence (all state in SQLite, survives within session).
- Idempotent startup seeding with clearly labelled fake demo data ([DEMO DATA - NOT REAL]).
- Transactional atomicity.
- Reversible autoincrement sequence ordering (never rely on timestamps for undo).
- Multi-event schema: CREDIT_SALE, CASH_SALE, PAYMENT_RECEIVED, RETURN, STOCK_PURCHASE.
- Inventory tracking (stock, cost, reorder_level) and profit margin tracking.
- Data-driven intent lexicon and customer habit frequency counters.
"""

import sqlite3
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "kirana.db")

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
        """)

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            phone TEXT,
            credit_limit REAL NOT NULL DEFAULT 2000.0,
            current_balance REAL NOT NULL DEFAULT 0.0,
            last_payment_date TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS catalog_items (
            sku TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            price REAL NOT NULL,                 -- Retail price per unit
            cost REAL NOT NULL DEFAULT 0.0,      -- Wholesale cost per unit (for profit calculation)
            stock REAL NOT NULL DEFAULT 50.0,    -- Units on hand
            reorder_level REAL NOT NULL DEFAULT 10.0, -- Threshold for low_stock
            unit TEXT NOT NULL,                  -- 'kg', 'packet', 'piece', 'liter'
            is_loose INTEGER NOT NULL DEFAULT 0, -- 1 for items sold by weight (kg/g)
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS item_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias TEXT UNIQUE NOT NULL,  -- normalized lower-case Latin/Tanglish alias
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
            event_type TEXT NOT NULL,    -- 'CREDIT_SALE', 'CASH_SALE', 'PAYMENT_RECEIVED', 'RETURN', 'STOCK_PURCHASE'
            weight REAL NOT NULL DEFAULT 1.0,
            lang TEXT NOT NULL DEFAULT 'en' -- 'en', 'ta', 'tanglish'
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
            customer_id INTEGER,         -- can be NULL for anonymous cash sales or stock purchase
            entry_type TEXT NOT NULL,    -- 'CREDIT_SALE', 'CASH_SALE', 'PAYMENT_RECEIVED', 'RETURN', 'STOCK_PURCHASE'
            amount REAL NOT NULL,        -- Total transaction amount
            cost_amount REAL NOT NULL DEFAULT 0.0, -- Total wholesale cost (for profit tracking)
            payment_mode TEXT,           -- 'CASH', 'UPI', 'CREDIT'
            items_json TEXT,             -- JSON breakdown of items
            stock_delta_json TEXT,       -- JSON delta of stock changes for exact reversible rollback
            previous_balance REAL NOT NULL DEFAULT 0.0,
            new_balance REAL NOT NULL DEFAULT 0.0,
            previous_last_payment_date TEXT,
            created_at TEXT NOT NULL,
            note TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()

def seed_demo_data(db_path: str = DEFAULT_DB_PATH, force: bool = False) -> None:
    """
    Idempotent seeder: inserts labelled fake demo data if not already seeded.
    No real phone numbers, no real customer debts, no third-party displayed brand names.
    """
    init_db(db_path, reset=force)
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM customers")
    if cur.fetchone()[0] > 0 and not force:
        conn.close()
        return

    now = datetime.now(timezone.utc)
    date_35_days_ago = (now - timedelta(days=35)).strftime("%Y-%m-%d")
    date_40_days_ago = (now - timedelta(days=40)).strftime("%Y-%m-%d")
    date_5_days_ago = (now - timedelta(days=5)).strftime("%Y-%m-%d")
    date_10_days_ago = (now - timedelta(days=10)).strftime("%Y-%m-%d")
    date_2_days_ago = (now - timedelta(days=2)).strftime("%Y-%m-%d")

    # 1. Labelled Demo Customers
    customers = [
        ("Ramesh Teacher", "9800000001", 2000.0, 450.0, date_35_days_ago, "[DEMO DATA - NOT REAL] Local school teacher"),
        ("Karthik 3B", "9800000002", 1500.0, 100.0, date_5_days_ago, "[DEMO DATA - NOT REAL] Apt 3B Resident"),
        ("Karthik 5A", "9800000003", 1500.0, 0.0, date_10_days_ago, "[DEMO DATA - NOT REAL] Apt 5A Resident"),
        ("Priya Madam", "9800000004", 3000.0, 850.0, date_40_days_ago, "[DEMO DATA - NOT REAL] Tailoring shop owner"),
        ("Suresh Electrician", "9800000005", 1000.0, 0.0, date_2_days_ago, "[DEMO DATA - NOT REAL] Nearby electrician"),
    ]
    cur.executemany("""
        INSERT OR REPLACE INTO customers (name, phone, credit_limit, current_balance, last_payment_date, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, customers)

    # 2. Labelled Demo Catalog Items with wholesale cost, stock, and reorder levels
    # (NO 3rd-party brand names in display_name)
    catalog = [
        ("toor_dal", "Toor Dal", 160.0, 135.0, 50.0, 10.0, "kg", 1),              # loose per kg (retail 160, cost 135)
        ("curd_500ml", "Curd 500ml", 35.0, 28.0, 30.0, 8.0, "packet", 0),       # packaged (retail 35, cost 28)
        ("sunflower_oil_1l", "Sunflower Oil 1L", 140.0, 120.0, 25.0, 5.0, "packet", 0), # packaged (retail 140, cost 120)
        ("groundnut_oil_1l", "Groundnut Oil 1L", 190.0, 160.0, 20.0, 5.0, "packet", 0), # packaged (retail 190, cost 160)
        ("ponni_rice", "Ponni Rice", 60.0, 48.0, 80.0, 15.0, "kg", 1),           # loose per kg (retail 60, cost 48)
        ("bath_soap", "Bathing Soap 100g", 40.0, 30.0, 40.0, 10.0, "piece", 0),   # packaged (retail 40, cost 30)
        ("washing_soap", "Washing Soap 250g", 30.0, 22.0, 35.0, 10.0, "piece", 0), # packaged (retail 30, cost 22)
        ("coriander_leaves", "Coriander Leaves", 15.0, 10.0, 15.0, 3.0, "bunch", 0), # bunch (retail 15, cost 10)
    ]
    cur.executemany("""
        INSERT OR REPLACE INTO catalog_items (sku, display_name, price, cost, stock, reorder_level, unit, is_loose)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, catalog)

    # 3. Normalized Item Aliases (Tanglish, Tamil transliterations, generic variations)
    aliases = [
        # Toor Dal
        ("toor dal", "toor_dal"),
        ("toor dhal", "toor_dal"),
        ("thuvaram paruppu", "toor_dal"),
        ("tuvaram paruppu", "toor_dal"),
        ("tuvaram", "toor_dal"),
        ("arhar dal", "toor_dal"),
        ("sambhar dal", "toor_dal"),
        ("sambar dal", "toor_dal"),
        # Curd
        ("curd", "curd_500ml"),
        ("curd 500ml", "curd_500ml"),
        ("thayir", "curd_500ml"),
        ("tayir", "curd_500ml"),
        ("dahi", "curd_500ml"),
        ("curds", "curd_500ml"),
        # Sunflower Oil
        ("sunflower oil", "sunflower_oil_1l"),
        ("sunflower oil 1l", "sunflower_oil_1l"),
        ("suriyakandhi ennai", "sunflower_oil_1l"),
        # Groundnut Oil
        ("groundnut oil", "groundnut_oil_1l"),
        ("groundnut oil 1l", "groundnut_oil_1l"),
        ("kadala ennai", "groundnut_oil_1l"),
        ("kadala yennai", "groundnut_oil_1l"),
        ("peanut oil", "groundnut_oil_1l"),
        # Ponni Rice
        ("ponni rice", "ponni_rice"),
        ("rice ponni", "ponni_rice"),
        ("arisi", "ponni_rice"),
        ("ponni arisi", "ponni_rice"),
        # Bath Soap
        ("bathing soap", "bath_soap"),
        ("bath soap", "bath_soap"),
        ("kuliyal soap", "bath_soap"),
        # Washing Soap
        ("washing soap", "washing_soap"),
        ("thuni soap", "washing_soap"),
        ("wash soap", "washing_soap"),
        # Coriander leaves
        ("coriander", "coriander_leaves"),
        ("coriander leaves", "coriander_leaves"),
        ("kothamalli", "coriander_leaves"),
    ]
    cur.executemany("""
        INSERT OR REPLACE INTO item_aliases (alias, sku)
        VALUES (?, ?)
    """, aliases)

    # 4. Intent Lexicon Seeds (English, Tanglish, and Tamil Script)
    # Every Tamil script entry is marked # NEEDS_NATIVE_REVIEW for shopkeeper validation.
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

    # 5. Customer Habit Seeds
    # Ramesh Teacher has 3 past CREDIT_SALE confirmations (habituated udhaar)
    cur.execute("SELECT id FROM customers WHERE name = 'Ramesh Teacher'")
    ramesh_id = cur.fetchone()[0]
    cur.execute("""
        INSERT OR REPLACE INTO customer_habit (customer_id, event_type, confirmations_count)
        VALUES (?, 'CREDIT_SALE', 3)
    """, (ramesh_id,))

    # Suresh Electrician has 3 past CASH_SALE confirmations (habituated cash customer)
    cur.execute("SELECT id FROM customers WHERE name = 'Suresh Electrician'")
    suresh_id = cur.fetchone()[0]
    cur.execute("""
        INSERT OR REPLACE INTO customer_habit (customer_id, event_type, confirmations_count)
        VALUES (?, 'CASH_SALE', 3)
    """, (suresh_id,))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    seed_demo_data(force=True)
    print("Database initialized and demo data seeded successfully.")
