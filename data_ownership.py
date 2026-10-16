"""
data_ownership.py - Data-Ownership Tools for KiranaFlow.

Implements:
1. teach_item_alias: Teaches the shop's custom vocabulary and aliases.
2. set_item_price: Updates unit price in shop's catalog (affects next total, preserves past ledger).
3. add_catalog_item: Adds a new product to shop's catalog with initial aliases.
4. add_customer: Registers a new customer with a credit limit (duplicate customer rejected).
"""

import sqlite3
import re
from typing import Optional, List, Dict, Any, Union
from database import get_connection, DEFAULT_DB_PATH
from matching import normalize_text, match_item, match_customer

def teach_item_alias(
    alias: str,
    item_name_or_sku: str,
    db_path: str = DEFAULT_DB_PATH
) -> Dict[str, Any]:
    """
    Teaches the system that a spoken alias or brand name maps to an existing SKU.
    Example: "remember kothamalli means coriander leaves"
    """
    norm_alias = normalize_text(alias)
    if not norm_alias:
        return {
            "success": False,
            "status": "INVALID_ALIAS",
            "spoken_summary": "Please provide a valid alias name.",
            "screen_note": "Invalid alias provided.",
            "structured_data": {}
        }

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        
        # 1. Resolve target item
        cur.execute("SELECT sku, display_name, price, unit FROM catalog_items WHERE sku = ? AND is_active = 1", (item_name_or_sku,))
        row = cur.fetchone()

        if not row:
            # Try matching as item name
            res = match_item(conn, item_name_or_sku)
            if res["status"] == "SUCCESS":
                target_sku = res["sku"]
                display_name = res["display_name"]
            else:
                return {
                    "success": False,
                    "status": "ITEM_NOT_FOUND",
                    "spoken_summary": f"Could not find catalog item '{item_name_or_sku}' to link.",
                    "screen_note": f"Item '{item_name_or_sku}' not found in catalog.",
                    "structured_data": {}
                }
        else:
            target_sku = row["sku"]
            display_name = row["display_name"]

        # 2. Insert or update alias
        cur.execute("""
            INSERT INTO item_aliases (alias, sku)
            VALUES (?, ?)
            ON CONFLICT(alias) DO UPDATE SET sku = excluded.sku
        """, (norm_alias, target_sku))
        conn.commit()

        spoken = f"Got it. I've linked '{alias}' to {display_name}."
        screen_note = f"Linked alias '{alias}' -> {display_name} ({target_sku})."

        return {
            "success": True,
            "status": "SUCCESS",
            "spoken_summary": spoken,
            "screen_note": screen_note,
            "structured_data": {
                "alias": norm_alias,
                "sku": target_sku,
                "display_name": display_name
            },
            "_meta": {
                "ui": {
                    "resourceUri": "ui://khata-card",
                    "invoking": f"Teaching alias '{alias}'...",
                    "invoked": f"Learned alias '{alias}'"
                }
            }
        }
    finally:
        conn.close()

def set_item_price(
    item_name_or_sku: str,
    new_price: float,
    db_path: str = DEFAULT_DB_PATH
) -> Dict[str, Any]:
    """
    Sets the unit price of an item in the shop's catalog.
    Affects subsequent transactions; preserves historical ledger entries.
    """
    try:
        price_val = float(new_price)
        if price_val <= 0:
            return {
                "success": False,
                "status": "INVALID_PRICE",
                "spoken_summary": "Price must be greater than zero.",
                "screen_note": "Invalid price: must be positive.",
                "structured_data": {}
            }
    except (ValueError, TypeError):
        return {
            "success": False,
            "status": "INVALID_PRICE",
            "spoken_summary": "Please specify a valid numeric price.",
            "screen_note": "Invalid price format.",
            "structured_data": {}
        }

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()

        # Check by SKU first
        cur.execute("SELECT sku, display_name, price, unit FROM catalog_items WHERE sku = ? AND is_active = 1", (item_name_or_sku,))
        row = cur.fetchone()

        if not row:
            res = match_item(conn, item_name_or_sku)
            if res["status"] == "SUCCESS":
                target_sku = res["sku"]
                display_name = res["display_name"]
                unit = res["unit"]
                old_price = res["unit_price"]
            else:
                return {
                    "success": False,
                    "status": "ITEM_NOT_FOUND",
                    "spoken_summary": f"Could not find item '{item_name_or_sku}' in your catalog.",
                    "screen_note": f"Item '{item_name_or_sku}' not found.",
                    "structured_data": {}
                }
        else:
            target_sku = row["sku"]
            display_name = row["display_name"]
            unit = row["unit"]
            old_price = row["price"]

        cur.execute("UPDATE catalog_items SET price = ? WHERE sku = ?", (price_val, target_sku))
        conn.commit()

        price_disp = int(price_val) if price_val.is_integer() else price_val
        spoken = f"Updated price for {display_name} to {price_disp} rupees per {unit}."
        screen_note = f"Price updated: {display_name} was Rs {old_price}, now Rs {price_disp}/{unit}."

        return {
            "success": True,
            "status": "SUCCESS",
            "spoken_summary": spoken,
            "screen_note": screen_note,
            "structured_data": {
                "sku": target_sku,
                "display_name": display_name,
                "old_price": old_price,
                "new_price": price_val,
                "unit": unit
            },
            "_meta": {
                "ui": {
                    "resourceUri": "ui://khata-card",
                    "invoking": f"Updating price for {display_name}...",
                    "invoked": f"Price updated for {display_name}"
                }
            }
        }
    finally:
        conn.close()

def add_catalog_item(
    sku: str,
    display_name: str,
    price: float,
    unit: str = "packet",
    is_loose: bool = False,
    aliases: Optional[List[str]] = None,
    db_path: str = DEFAULT_DB_PATH
) -> Dict[str, Any]:
    """
    Adds a new item to the catalog.
    Enforces no third-party brand names in display_name.
    """
    clean_sku = re.sub(r"[^a-zA-Z0-9_]", "_", sku.lower().strip())
    clean_name = display_name.strip()

    if not clean_sku or not clean_name:
        return {
            "success": False,
            "status": "INVALID_INPUT",
            "spoken_summary": "Item name and SKU are required.",
            "screen_note": "Invalid item name or SKU.",
            "structured_data": {}
        }

    try:
        price_val = float(price)
        if price_val <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return {
            "success": False,
            "status": "INVALID_PRICE",
            "spoken_summary": "Item price must be greater than zero.",
            "screen_note": "Invalid item price.",
            "structured_data": {}
        }

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT sku FROM catalog_items WHERE sku = ?", (clean_sku,))
        if cur.fetchone():
            return {
                "success": False,
                "status": "DUPLICATE_SKU",
                "spoken_summary": f"An item with SKU '{clean_sku}' already exists in your catalog.",
                "screen_note": f"Item SKU '{clean_sku}' already exists.",
                "structured_data": {"sku": clean_sku}
            }

        cur.execute("""
            INSERT INTO catalog_items (sku, display_name, price, unit, is_loose)
            VALUES (?, ?, ?, ?, ?)
        """, (clean_sku, clean_name, price_val, unit.strip().lower(), 1 if is_loose else 0))

        # Add initial alias for display_name
        cur.execute("""
            INSERT OR IGNORE INTO item_aliases (alias, sku)
            VALUES (?, ?)
        """, (normalize_text(clean_name), clean_sku))

        # Add optional custom aliases
        if aliases:
            for al in aliases:
                norm_al = normalize_text(al)
                if norm_al:
                    cur.execute("""
                        INSERT OR IGNORE INTO item_aliases (alias, sku)
                        VALUES (?, ?)
                    """, (norm_al, clean_sku))

        conn.commit()

        price_disp = int(price_val) if price_val.is_integer() else price_val
        spoken = f"Added {clean_name} to your catalog at {price_disp} rupees per {unit}."
        screen_note = f"New catalog item: {clean_name} (Rs {price_disp} / {unit})."

        return {
            "success": True,
            "status": "SUCCESS",
            "spoken_summary": spoken,
            "screen_note": screen_note,
            "structured_data": {
                "sku": clean_sku,
                "display_name": clean_name,
                "price": price_val,
                "unit": unit,
                "is_loose": is_loose
            },
            "_meta": {
                "ui": {
                    "resourceUri": "ui://khata-card",
                    "invoking": f"Adding {clean_name} to catalog...",
                    "invoked": f"{clean_name} added to catalog"
                }
            }
        }
    finally:
        conn.close()

def add_customer(
    name: str,
    phone: Optional[str] = None,
    credit_limit: float = 2000.0,
    db_path: str = DEFAULT_DB_PATH
) -> Dict[str, Any]:
    """
    Registers a new customer.
    Rejects duplicate customer names (case-insensitive).
    """
    clean_name = name.strip()
    if not clean_name:
        return {
            "success": False,
            "status": "INVALID_NAME",
            "spoken_summary": "Customer name cannot be empty.",
            "screen_note": "Invalid customer name.",
            "structured_data": {}
        }

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        # Case-insensitive duplicate check
        cur.execute("SELECT id, name FROM customers WHERE LOWER(name) = LOWER(?)", (clean_name,))
        existing = cur.fetchone()
        if existing:
            return {
                "success": False,
                "status": "DUPLICATE_CUSTOMER",
                "spoken_summary": f"Customer '{existing['name']}' already exists in your records.",
                "screen_note": f"Customer '{existing['name']}' already registered.",
                "structured_data": {"existing_id": existing["id"], "name": existing["name"]}
            }

        limit_val = float(credit_limit) if credit_limit else 2000.0
        cur.execute("""
            INSERT INTO customers (name, phone, credit_limit, current_balance, notes)
            VALUES (?, ?, ?, 0.0, ?)
        """, (clean_name, phone or "", limit_val, "[DEMO DATA - NOT REAL] Added via voice"))
        new_id = cur.lastrowid
        conn.commit()

        limit_disp = int(limit_val) if limit_val.is_integer() else limit_val
        spoken = f"Added customer {clean_name} with a credit limit of {limit_disp} rupees."
        screen_note = f"New customer: {clean_name} | Credit limit: Rs {limit_disp}."

        return {
            "success": True,
            "status": "SUCCESS",
            "spoken_summary": spoken,
            "screen_note": screen_note,
            "structured_data": {
                "id": new_id,
                "name": clean_name,
                "credit_limit": limit_val,
                "current_balance": 0.0
            },
            "_meta": {
                "ui": {
                    "resourceUri": "ui://khata-card",
                    "invoking": f"Adding customer {clean_name}...",
                    "invoked": f"Customer {clean_name} registered"
                }
            }
        }
    finally:
        conn.close()


def evaluate_wholesale_quote(
    *args,
    **kwargs,
) -> Dict[str, Any]:
    """
    Evaluates a wholesale supplier quote against the shop's current retail price.

    Accepts either:
      evaluate_wholesale_quote(conn, item_name_or_sku, wholesale_price, quantity=1.0)
    or:
      evaluate_wholesale_quote(item_name_or_sku, wholesale_price, quantity=1.0, db_path=DEFAULT_DB_PATH)
    """
    if len(args) > 0 and isinstance(args[0], sqlite3.Connection):
        conn = args[0]
        should_close = False
        item_name_or_sku = args[1] if len(args) > 1 else kwargs.get("item_name_or_sku", "")
        wholesale_price = args[2] if len(args) > 2 else kwargs.get("wholesale_price", 0.0)
        quantity = args[3] if len(args) > 3 else kwargs.get("quantity", 1.0)
    else:
        db_path = kwargs.get("db_path", DEFAULT_DB_PATH)
        conn = get_connection(db_path)
        should_close = True
        item_name_or_sku = args[0] if len(args) > 0 else kwargs.get("item_name_or_sku", "")
        wholesale_price = args[1] if len(args) > 1 else kwargs.get("wholesale_price", 0.0)
        quantity = args[2] if len(args) > 2 else kwargs.get("quantity", 1.0)

    try:
        try:
            wp = float(wholesale_price)
            qty = float(quantity)
            if wp <= 0 or qty <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return {
                "success": False,
                "status": "INVALID_INPUT",
                "spoken_summary": "Please provide valid wholesale price and quantity.",
                "screen_note": "Invalid wholesale price or quantity.",
                "structured_data": {},
            }

        cur = conn.cursor()

        # Resolve item by SKU first, then fuzzy match
        cur.execute(
            "SELECT sku, display_name, price, unit FROM catalog_items WHERE sku = ? AND is_active = 1",
            (item_name_or_sku,),
        )
        row = cur.fetchone()

        if not row:
            res = match_item(conn, item_name_or_sku)
            if res["status"] == "SUCCESS":
                sku = res["sku"]
                display_name = res["display_name"]
                retail_price = res["unit_price"]
                unit = res["unit"]
            else:
                return {
                    "success": False,
                    "status": "ITEM_NOT_FOUND",
                    "spoken_summary": f"Could not find '{item_name_or_sku}' in your catalog.",
                    "screen_note": f"Item '{item_name_or_sku}' not found.",
                    "structured_data": {},
                }
        else:
            sku = row["sku"]
            display_name = row["display_name"]
            retail_price = row["price"]
            unit = row["unit"]

        margin_pct = ((retail_price - wp) / retail_price * 100) if retail_price > 0 else 0.0
        retail_profit = (retail_price - wp) * qty

        verdict = "ACCEPT" if margin_pct >= 10 else "NEGOTIATE"
        spoken = (
            f"Wholesale quote for {display_name}: margin is {margin_pct:.1f}%. "
            + ("Looks good, recommend accepting." if verdict == "ACCEPT" else "Margin is thin, try negotiating.")
        )
        screen_note = (
            f"{display_name} | Retail: Rs {retail_price}/{unit} | Wholesale: Rs {wp} | "
            f"Margin: {margin_pct:.1f}% | Profit on {qty} {unit}s: Rs {retail_profit:.2f} | {verdict}"
        )

        return {
            "success": True,
            "status": verdict,
            "spoken_summary": spoken,
            "screen_note": screen_note,
            "structured_data": {
                "sku": sku,
                "display_name": display_name,
                "retail_price": retail_price,
                "wholesale_price": wp,
                "quantity": qty,
                "unit": unit,
                "margin_pct": round(margin_pct, 2),
                "retail_profit": round(retail_profit, 2),
                "verdict": verdict,
            },
            "_meta": {
                "ui": {
                    "resourceUri": "ui://khata-card",
                    "invoking": f"Evaluating wholesale quote for {display_name}...",
                    "invoked": f"Wholesale quote evaluated for {display_name}",
                }
            },
        }
    finally:
        if should_close:
            conn.close()
