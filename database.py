"""
database.py - SQLite Database & Labelled Demo Data Seeder for KiranaFlow.

Enforces:
- Stateless SQLite persistence (all state in SQLite, survives within session).
- Idempotent startup seeding with clearly labelled fake demo data ([DEMO DATA - NOT REAL]).
- Transactional atomicity.
- Reversible autoincrement sequence ordering (never rely on timestamps for undo).
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
            price REAL NOT NULL,
            unit TEXT NOT NULL,          -- 'kg', 'packet', 'piece', 'liter'
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

        CREATE TABLE IF NOT EXISTS ledger_entries (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            entry_type TEXT NOT NULL,    -- 'CREDIT' or 'PAYMENT'
            amount REAL NOT NULL,
            items_json TEXT,             -- JSON breakdown of items for credit entries
            previous_balance REAL NOT NULL,
            new_balance REAL NOT NULL,
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

    # 2. Labelled Demo Catalog Items (NO 3rd-party brand names in display_name)
    catalog = [
        ("toor_dal", "Toor Dal", 160.0, "kg", 1),              # loose per kg
        ("curd_500ml", "Curd 500ml", 35.0, "packet", 0),       # packaged
        ("sunflower_oil_1l", "Sunflower Oil 1L", 140.0, "packet", 0), # packaged
        ("groundnut_oil_1l", "Groundnut Oil 1L", 190.0, "packet", 0), # packaged
        ("ponni_rice", "Ponni Rice", 60.0, "kg", 1),           # loose per kg
        ("bath_soap", "Bathing Soap 100g", 40.0, "piece", 0),   # packaged
        ("washing_soap", "Washing Soap 250g", 30.0, "piece", 0), # packaged
        ("coriander_leaves", "Coriander Leaves", 15.0, "bunch", 0), # bunch
    ]
    cur.executemany("""
        INSERT OR REPLACE INTO catalog_items (sku, display_name, price, unit, is_loose)
        VALUES (?, ?, ?, ?, ?)
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

    conn.commit()
    conn.close()

if __name__ == "__main__":
    seed_demo_data(force=True)
    print("Database initialized and demo data seeded successfully.")
