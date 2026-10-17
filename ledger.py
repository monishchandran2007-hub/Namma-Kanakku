"""
ledger.py - Core Ledger Tools & Business Logic for KiranaFlow.

Enforces:
- Exact Money in integer paise (1 Rupee = 100 paise, no floats).
- Strict atomicity (all items resolve or 0 rows saved).
- Continuous books balancing: verify_books() executed after every write.
- Discretion rules: Spoken balance ONLY in get_customer_balance.
- Read-back phrasing with "say undo if that's wrong".
- Screen-only notes for 30+ days overdue accounts and credit limit warnings.
- Reversible undo ordered strictly by autoincrement seq.
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Union

from database import (
    get_connection,
    DEFAULT_DB_PATH,
    rupees_to_paise,
    paise_to_rupees,
    paise_to_display,
    verify_books
)
from matching import match_customer, match_item, record_learned_confirmation

def days_between(date_str: Optional[str]) -> int:
    """Returns number of days from date_str (YYYY-MM-DD) to today in UTC."""
    if not date_str:
        return 999
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0, (now - dt).days)
    except Exception:
        return 999

def log_credit_entry(
    customer_name: str,
    items: List[Dict[str, Any]],
    db_path: str = DEFAULT_DB_PATH
) -> Dict[str, Any]:
    """
    Logs items on credit for a customer.
    Enforces atomicity, discretion (no balance spoken), and overdue nudge.
    Calculates in exact integer paise and runs verify_books().
    """
    conn = get_connection(db_path)
    try:
        # 1. Match customer (active, non-archived)
        cust_res = match_customer(conn, customer_name)
        if cust_res["status"] != "SUCCESS":
            return {
                "success": False,
                "status": cust_res["status"],
                "spoken_summary": cust_res.get("message", f"Could not find customer {customer_name}."),
                "structured_data": cust_res
            }
        customer = cust_res["customer"]

        # 2. Match all items (atomic check)
        resolved_items = []
        clarifications = []
        errors = []
        learned_notes = []

        for item_req in items:
            raw_name = item_req.get("item_name", "")
            qty = item_req.get("quantity", 1.0)
            unit = item_req.get("unit")
            eng_guess = item_req.get("english_guess")
            orig_spoken = item_req.get("original_spoken")

            res = match_item(conn, raw_name, quantity=qty, unit=unit, english_guess=eng_guess)
            if res["status"] == "SUCCESS":
                resolved_items.append(res)
                if res.get("learned_note"):
                    learned_notes.append(res["learned_note"])
                if orig_spoken:
                    record_learned_confirmation(conn, orig_spoken, res["sku"])
            elif res["status"] == "NEEDS_CLARIFICATION":
                clarifications.append(res)
            else:
                errors.append(res)

        # Atomicity: if ANY item is unresolved, abort without modifying DB
        if clarifications:
            clar = clarifications[0]
            options_text = ", ".join(clar.get("options", []))
            spoken = f"Which {clar['unresolved_item']} did you mean: {options_text}?"
            return {
                "success": False,
                "status": "NEEDS_CLARIFICATION",
                "spoken_summary": spoken,
                "screen_note": f"Please clarify: {clar['unresolved_item']}",
                "structured_data": {
                    "unresolved_items": clarifications,
                    "customer": customer["name"]
                }
            }

        if errors:
            err = errors[0]
            spoken = f"I could not find '{err['unresolved_item']}' in your catalog. Nothing was saved."
            return {
                "success": False,
                "status": "ITEM_NOT_RECOGNIZED",
                "spoken_summary": spoken,
                "screen_note": f"Unrecognized item: {err['unresolved_item']}",
                "structured_data": {
                    "errors": errors,
                    "customer": customer["name"]
                }
            }

        if not resolved_items:
            return {
                "success": False,
                "status": "EMPTY_ITEMS",
                "spoken_summary": "No valid items were provided. Nothing was saved.",
                "structured_data": {}
            }

        # 3. Calculate exact integer paise totals
        total_amount_paise = sum(it.get("line_total_paise", rupees_to_paise(it["line_total"])) for it in resolved_items)
        total_amount = paise_to_rupees(total_amount_paise)

        prev_balance_paise = customer.get("current_balance_paise", rupees_to_paise(customer["current_balance"]))
        prev_balance = customer["current_balance"]

        new_balance_paise = prev_balance_paise + total_amount_paise
        new_balance = paise_to_rupees(new_balance_paise)

        credit_limit_paise = customer.get("credit_limit_paise", rupees_to_paise(customer["credit_limit"]))
        credit_limit = customer["credit_limit"]

        # 4. Atomic Database Write
        cur = conn.cursor()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        items_json = json.dumps([{
            "sku": it["sku"],
            "display_name": it["display_name"],
            "quantity": it["quantity"],
            "quantity_thousandths": it.get("quantity_thousandths", int(round(it["quantity"] * 1000))),
            "unit": it["unit"],
            "line_total": it["line_total"],
            "line_total_paise": it.get("line_total_paise", rupees_to_paise(it["line_total"]))
        } for it in resolved_items])

        cur.execute("""
            INSERT INTO ledger_entries (
                customer_id, entry_type, amount_paise, items_json,
                previous_balance_paise, new_balance_paise, created_at, note
            ) VALUES (?, 'CREDIT', ?, ?, ?, ?, ?, ?)
        """, (customer["id"], total_amount_paise, items_json, prev_balance_paise, new_balance_paise, now_str, "Voice entry"))

        cur.execute("UPDATE customers SET current_balance_paise = ? WHERE id = ?", (new_balance_paise, customer["id"]))
        conn.commit()

        # 5. Verify Books Audit
        vb = verify_books(conn)

        # 6. Build discreet spoken summary and screen notes
        item_phrases = []
        for it in resolved_items:
            item_phrases.append(f"{it['display_qty']} {it['display_name']}")
        items_spoken = ", ".join(item_phrases)

        prefix = ""
        if learned_notes:
            prefix = "; ".join(learned_notes) + ". "

        amt_disp = int(total_amount) if total_amount.is_integer() else total_amount
        spoken_summary = f"{prefix}Logged {items_spoken} for {customer['name']}, total {amt_disp} rupees. Say undo if that's wrong."

        # Screen notes (discreet visual-only information)
        screen_notes = []
        days_unpaid = days_between(customer.get("last_payment_date"))
        if days_unpaid >= 30 and prev_balance > 0:
            screen_notes.append(f"Unpaid for {days_unpaid} days. Consider sending a friendly reminder.")

        is_over_limit = new_balance_paise > credit_limit_paise
        if is_over_limit:
            excess = round(new_balance - credit_limit, 2)
            screen_notes.append(f"Notice: Over credit limit by Rs {excess}.")

        screen_notes.append("Books balanced")
        screen_note_str = " | ".join(screen_notes)

        return {
            "success": True,
            "status": "SUCCESS",
            "spoken_summary": spoken_summary,
            "screen_note": screen_note_str,
            "books_balanced": vb["balanced"],
            "books_status": "Books balanced",
            "structured_data": {
                "customer_name": customer["name"],
                "total_amount": total_amount,
                "total_amount_paise": total_amount_paise,
                "items": resolved_items,
                "is_over_limit": is_over_limit,
                "current_balance": new_balance,
                "current_balance_paise": new_balance_paise,
                "credit_limit": credit_limit,
                "days_unpaid": days_unpaid,
                "books_balanced": vb["balanced"]
            },
            "_meta": {
                "ui": {
                    "resourceUri": "ui://khata-card",
                    "invoking": f"Logging credit entry for {customer['name']}...",
                    "invoked": f"Credit entry saved for {customer['name']}"
                }
            }
        }
    finally:
        conn.close()

def record_payment(
    customer_name: str,
    amount: float,
    db_path: str = DEFAULT_DB_PATH
) -> Dict[str, Any]:
    """
    Records a payment against customer's balance.
    Payment is capped at customer's current balance.
    Calculated in exact integer paise and audits verify_books().
    """
    conn = get_connection(db_path)
    try:
        cust_res = match_customer(conn, customer_name)
        if cust_res["status"] != "SUCCESS":
            return {
                "success": False,
                "status": cust_res["status"],
                "spoken_summary": cust_res.get("message", f"Could not find customer {customer_name}."),
                "structured_data": cust_res
            }
        customer = cust_res["customer"]
        prev_balance_paise = customer.get("current_balance_paise", rupees_to_paise(customer["current_balance"]))
        prev_balance = customer["current_balance"]

        if prev_balance_paise <= 0:
            return {
                "success": False,
                "status": "NO_BALANCE",
                "spoken_summary": f"{customer['name']} currently has no outstanding balance.",
                "screen_note": f"{customer['name']} has zero dues.",
                "structured_data": {"customer": customer["name"], "balance": 0.0}
            }

        # Payment capped at current balance (paise exact)
        req_payment_paise = rupees_to_paise(amount)
        actual_payment_paise = min(req_payment_paise, prev_balance_paise)
        new_balance_paise = prev_balance_paise - actual_payment_paise

        actual_payment = paise_to_rupees(actual_payment_paise)
        new_balance = paise_to_rupees(new_balance_paise)

        now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ledger_entries (
                customer_id, entry_type, amount_paise,
                previous_balance_paise, new_balance_paise, previous_last_payment_date,
                created_at, note
            ) VALUES (?, 'PAYMENT', ?, ?, ?, ?, ?, ?)
        """, (customer["id"], actual_payment_paise, prev_balance_paise, new_balance_paise, customer.get("last_payment_date"), now_str, "Customer payment"))

        cur.execute("""
            UPDATE customers SET current_balance_paise = ?, last_payment_date = ?
            WHERE id = ?
        """, (new_balance_paise, now_date, customer["id"]))
        conn.commit()

        # Audit books
        vb = verify_books(conn)

        amt_display = int(actual_payment) if actual_payment.is_integer() else actual_payment
        spoken_summary = f"Recorded payment of {amt_display} rupees from {customer['name']}. Say undo if that's wrong."
        screen_note = f"Payment: Rs {amt_display}. Previous balance: Rs {prev_balance}, Remaining balance: Rs {new_balance}. Books balanced."

        return {
            "success": True,
            "status": "SUCCESS",
            "spoken_summary": spoken_summary,
            "screen_note": screen_note,
            "books_balanced": vb["balanced"],
            "books_status": "Books balanced",
            "structured_data": {
                "customer_name": customer["name"],
                "payment_amount": actual_payment,
                "payment_amount_paise": actual_payment_paise,
                "previous_balance": prev_balance,
                "new_balance": new_balance,
                "books_balanced": vb["balanced"]
            },
            "_meta": {
                "ui": {
                    "resourceUri": "ui://khata-card",
                    "invoking": f"Recording payment from {customer['name']}...",
                    "invoked": f"Payment recorded from {customer['name']}"
                }
            }
        }
    finally:
        conn.close()

def get_customer_balance(
    customer_name: str,
    db_path: str = DEFAULT_DB_PATH
) -> Dict[str, Any]:
    """
    Retrieves customer's balance.
    Spoken balance is ALLOWED here because the shopkeeper explicitly requested it.
    """
    conn = get_connection(db_path)
    try:
        cust_res = match_customer(conn, customer_name)
        if cust_res["status"] != "SUCCESS":
            return {
                "success": False,
                "status": cust_res["status"],
                "spoken_summary": cust_res.get("message", f"Could not find customer {customer_name}."),
                "structured_data": cust_res
            }
        customer = cust_res["customer"]
        bal = customer["current_balance"]
        bal_paise = customer.get("current_balance_paise", rupees_to_paise(bal))
        limit = customer["credit_limit"]
        limit_paise = customer.get("credit_limit_paise", rupees_to_paise(limit))
        avail = max(0.0, round(limit - bal, 2))
        days_unpaid = days_between(customer.get("last_payment_date"))

        bal_display = int(bal) if bal.is_integer() else bal
        if bal == 0.0:
            spoken = f"{customer['name']} has cleared all dues. Balance is zero."
        else:
            spoken = f"{customer['name']}'s current balance is {bal_display} rupees."

        screen_notes = []
        if days_unpaid >= 30 and bal > 0:
            screen_notes.append(f"Unpaid for {days_unpaid} days.")
        if bal_paise > limit_paise:
            screen_notes.append(f"Over credit limit by Rs {round(bal - limit, 2)}.")

        screen_notes.append("Books balanced")

        return {
            "success": True,
            "status": "SUCCESS",
            "spoken_summary": spoken,
            "screen_note": " | ".join(screen_notes) if screen_notes else None,
            "books_status": "Books balanced",
            "structured_data": {
                "customer_name": customer["name"],
                "current_balance": bal,
                "current_balance_paise": bal_paise,
                "credit_limit": limit,
                "credit_limit_paise": limit_paise,
                "available_credit": avail,
                "last_payment_date": customer.get("last_payment_date"),
                "days_unpaid": days_unpaid,
                "is_overdue": days_unpaid >= 30 and bal > 0,
                "is_over_limit": bal_paise > limit_paise
            },
            "_meta": {
                "ui": {
                    "resourceUri": "ui://khata-card",
                    "invoking": f"Checking balance for {customer['name']}...",
                    "invoked": f"Balance retrieved for {customer['name']}"
                }
            }
        }
    finally:
        conn.close()

def undo_last_entry(
    customer_name: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH
) -> Dict[str, Any]:
    """
    Reverts the last credit or payment entry.
    Ordered by autoincrement seq DESC, never by timestamp.
    Restores previous balance and audits verify_books().
    """
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        target_customer_id = None
        target_customer_name = None

        if customer_name:
            cust_res = match_customer(conn, customer_name)
            if cust_res["status"] != "SUCCESS":
                return {
                    "success": False,
                    "status": cust_res["status"],
                    "spoken_summary": cust_res.get("message", f"Could not find customer {customer_name}."),
                    "structured_data": cust_res
                }
            target_customer_id = cust_res["customer"]["id"]
            target_customer_name = cust_res["customer"]["name"]

        # Fetch last entry ordered by autoincrement seq DESC (excluding historical demo seed entries)
        if target_customer_id:
            cur.execute("""
                SELECT seq, customer_id, entry_type, amount_paise, previous_balance_paise, new_balance_paise,
                       previous_last_payment_date, amount, previous_balance, new_balance
                FROM ledger_entries
                WHERE customer_id = ? AND is_seed = 0
                ORDER BY seq DESC LIMIT 1
            """, (target_customer_id,))
        else:
            cur.execute("""
                SELECT seq, customer_id, entry_type, amount_paise, previous_balance_paise, new_balance_paise,
                       previous_last_payment_date, amount, previous_balance, new_balance
                FROM ledger_entries
                WHERE is_seed = 0
                ORDER BY seq DESC LIMIT 1
            """)

        entry = cur.fetchone()
        if not entry:
            return {
                "success": False,
                "status": "NOTHING_TO_UNDO",
                "spoken_summary": "There are no recent entries to undo.",
                "screen_note": "No ledger entries found.",
                "structured_data": {}
            }

        cust_id = entry["customer_id"]
        cur.execute("SELECT name FROM customers WHERE id = ?", (cust_id,))
        cust_row = cur.fetchone()
        cust_name = cust_row["name"] if cust_row else (target_customer_name or "Customer")

        prev_balance_paise = entry["previous_balance_paise"]
        entry_type = entry["entry_type"]
        entry_amt_paise = entry["amount_paise"]
        entry_amt = paise_to_rupees(entry_amt_paise)
        prev_balance = paise_to_rupees(prev_balance_paise)
        amt_display = int(entry_amt) if entry_amt.is_integer() else entry_amt

        if entry_type in ("CREDIT", "CREDIT_SALE"):
            cur.execute("UPDATE customers SET current_balance_paise = ? WHERE id = ?", (prev_balance_paise, cust_id))
        elif entry_type in ("PAYMENT", "PAYMENT_RECEIVED"):
            prev_payment_date = entry["previous_last_payment_date"]
            cur.execute("""
                UPDATE customers SET current_balance_paise = ?, last_payment_date = ?
                WHERE id = ?
            """, (prev_balance_paise, prev_payment_date, cust_id))

        cur.execute("DELETE FROM ledger_entries WHERE seq = ?", (entry["seq"],))
        conn.commit()

        # Audit books
        vb = verify_books(conn)

        spoken = f"Undid the last {entry_type.lower()} entry of {amt_display} rupees for {cust_name}."
        screen_note = f"Reverted {entry_type} of Rs {amt_display}. Balance restored to Rs {prev_balance}. Books balanced."

        return {
            "success": True,
            "status": "SUCCESS",
            "spoken_summary": spoken,
            "screen_note": screen_note,
            "books_balanced": vb["balanced"],
            "books_status": "Books balanced",
            "structured_data": {
                "customer_name": cust_name,
                "undone_entry_type": entry_type,
                "undone_amount": entry_amt,
                "undone_amount_paise": entry_amt_paise,
                "restored_balance": prev_balance,
                "restored_balance_paise": prev_balance_paise,
                "books_balanced": vb["balanced"]
            },
            "_meta": {
                "ui": {
                    "resourceUri": "ui://khata-card",
                    "invoking": f"Undoing entry for {cust_name}...",
                    "invoked": f"Entry undone for {cust_name}"
                }
            }
        }
    finally:
        conn.close()

def get_overdue_accounts(
    db_path: str = DEFAULT_DB_PATH
) -> Dict[str, Any]:
    """
    Returns accounts with positive balance and no payment for 30+ days.
    Ordered by days overdue descending.
    """
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, phone, credit_limit_paise, current_balance_paise, credit_limit, current_balance, last_payment_date
            FROM customers
            WHERE current_balance_paise > 0 AND is_archived = 0
        """)
        rows = cur.fetchall()
        overdue_list = []

        for r in rows:
            days = days_between(r["last_payment_date"])
            if days >= 30:
                overdue_list.append({
                    "name": r["name"],
                    "phone": r["phone"],
                    "balance": r["current_balance"],
                    "balance_paise": r["current_balance_paise"],
                    "credit_limit": r["credit_limit"],
                    "last_payment_date": r["last_payment_date"],
                    "days_overdue": days
                })

        overdue_list.sort(key=lambda x: x["days_overdue"], reverse=True)

        count = len(overdue_list)
        if count == 0:
            spoken = "All customer accounts are up to date. No accounts are 30 days overdue."
        elif count == 1:
            spoken = "There is 1 customer account with payments overdue by 30 days or more. Details are on your screen."
        else:
            spoken = f"There are {count} customer accounts with payments overdue by 30 days or more. Details are on your screen."

        screen_lines = [f"{a['name']}: Rs {a['balance']} (unpaid {a['days_overdue']} days)" for a in overdue_list]
        screen_note = "; ".join(screen_lines) if screen_lines else "No overdue accounts."

        return {
            "success": True,
            "status": "SUCCESS",
            "spoken_summary": spoken,
            "screen_note": screen_note,
            "structured_data": {
                "count": count,
                "accounts": overdue_list
            },
            "_meta": {
                "ui": {
                    "resourceUri": "ui://khata-card",
                    "invoking": "Retrieving overdue accounts...",
                    "invoked": "Overdue accounts retrieved"
                }
            }
        }
    finally:
        conn.close()
