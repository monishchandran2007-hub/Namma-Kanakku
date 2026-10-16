"""
ledger.py - Core Ledger Tools & Business Logic for KiranaFlow.

Enforces:
- Stateless SQLite execution.
- Strict atomicity (all items resolve or 0 rows saved).
- Discretion rules: Spoken balance ONLY in get_customer_balance.
- Read-back phrasing with "say undo if that's wrong".
- Screen-only notes for 30+ days overdue accounts and credit limit warnings.
- Reversible undo ordered strictly by autoincrement seq.
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from database import get_connection, DEFAULT_DB_PATH
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
    """
    conn = get_connection(db_path)
    try:
        # 1. Match customer
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
                # Record confirmation if answering an earlier clarification
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

        # 3. Calculate financial totals
        total_amount = round(sum(it["line_total"] for it in resolved_items), 2)
        prev_balance = customer["current_balance"]
        new_balance = round(prev_balance + total_amount, 2)
        credit_limit = customer["credit_limit"]

        # 4. Atomic Database Write
        cur = conn.cursor()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        items_json = json.dumps([{
            "sku": it["sku"],
            "display_name": it["display_name"],
            "quantity": it["quantity"],
            "unit": it["unit"],
            "line_total": it["line_total"]
        } for it in resolved_items])

        cur.execute("""
            INSERT INTO ledger_entries (
                customer_id, entry_type, amount, items_json,
                previous_balance, new_balance, created_at, note
            ) VALUES (?, 'CREDIT', ?, ?, ?, ?, ?, ?)
        """, (customer["id"], total_amount, items_json, prev_balance, new_balance, now_str, "Voice entry"))

        cur.execute("UPDATE customers SET current_balance = ? WHERE id = ?", (new_balance, customer["id"]))
        conn.commit()

        # 5. Build discreet spoken summary and screen notes
        # Discretion Rule: Spoken summary must NEVER speak balance or limit!
        item_phrases = []
        for it in resolved_items:
            item_phrases.append(f"{it['display_qty']} {it['display_name']}")
        items_spoken = ", ".join(item_phrases)

        prefix = ""
        if learned_notes:
            prefix = "; ".join(learned_notes) + ". "

        spoken_summary = f"{prefix}Logged {items_spoken} for {customer['name']}, total {int(total_amount) if total_amount.is_integer() else total_amount} rupees. Say undo if that's wrong."

        # Screen notes (discreet visual-only information)
        screen_notes = []
        days_unpaid = days_between(customer.get("last_payment_date"))
        if days_unpaid >= 30 and prev_balance > 0:
            screen_notes.append(f"Unpaid for {days_unpaid} days. Consider sending a friendly reminder.")

        is_over_limit = new_balance > credit_limit
        if is_over_limit:
            excess = round(new_balance - credit_limit, 2)
            screen_notes.append(f"Notice: Over credit limit by Rs {excess}.")

        screen_note_str = " | ".join(screen_notes) if screen_notes else None

        return {
            "success": True,
            "status": "SUCCESS",
            "spoken_summary": spoken_summary,
            "screen_note": screen_note_str,
            "structured_data": {
                "customer_name": customer["name"],
                "total_amount": total_amount,
                "items": resolved_items,
                "is_over_limit": is_over_limit,
                "current_balance": new_balance,
                "credit_limit": credit_limit,
                "days_unpaid": days_unpaid
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
    Discretion rule: spoken_summary does not disclose customer's remaining balance.
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
        prev_balance = customer["current_balance"]

        if prev_balance <= 0.0:
            return {
                "success": False,
                "status": "NO_BALANCE",
                "spoken_summary": f"{customer['name']} currently has no outstanding balance.",
                "screen_note": f"{customer['name']} has zero dues.",
                "structured_data": {"customer": customer["name"], "balance": 0.0}
            }

        # Payment capped at current balance
        actual_payment = round(min(float(amount), prev_balance), 2)
        new_balance = round(prev_balance - actual_payment, 2)
        now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ledger_entries (
                customer_id, entry_type, amount,
                previous_balance, new_balance, previous_last_payment_date,
                created_at, note
            ) VALUES (?, 'PAYMENT', ?, ?, ?, ?, ?, ?)
        """, (customer["id"], actual_payment, prev_balance, new_balance, customer.get("last_payment_date"), now_str, "Customer payment"))

        cur.execute("""
            UPDATE customers SET current_balance = ?, last_payment_date = ?
            WHERE id = ?
        """, (new_balance, now_date, customer["id"]))
        conn.commit()

        # Discretion rule: Do NOT speak remaining balance
        amt_display = int(actual_payment) if actual_payment.is_integer() else actual_payment
        spoken_summary = f"Recorded payment of {amt_display} rupees from {customer['name']}. Say undo if that's wrong."
        screen_note = f"Payment: Rs {amt_display}. Previous balance: Rs {prev_balance}, Remaining balance: Rs {new_balance}."

        return {
            "success": True,
            "status": "SUCCESS",
            "spoken_summary": spoken_summary,
            "screen_note": screen_note,
            "structured_data": {
                "customer_name": customer["name"],
                "payment_amount": actual_payment,
                "previous_balance": prev_balance,
                "new_balance": new_balance
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
        limit = customer["credit_limit"]
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
        if bal > limit:
            screen_notes.append(f"Over credit limit by Rs {round(bal - limit, 2)}.")

        return {
            "success": True,
            "status": "SUCCESS",
            "spoken_summary": spoken,
            "screen_note": " | ".join(screen_notes) if screen_notes else None,
            "structured_data": {
                "customer_name": customer["name"],
                "current_balance": bal,
                "credit_limit": limit,
                "available_credit": avail,
                "last_payment_date": customer.get("last_payment_date"),
                "days_unpaid": days_unpaid,
                "is_overdue": days_unpaid >= 30 and bal > 0,
                "is_over_limit": bal > limit
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
    Restores previous balance and previous_last_payment_date.
    Discretion rule: spoken_summary confirms undo without stating customer balance.
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

        # Fetch last entry ordered by autoincrement seq DESC
        if target_customer_id:
            cur.execute("""
                SELECT seq, customer_id, entry_type, amount, previous_balance, new_balance, previous_last_payment_date
                FROM ledger_entries
                WHERE customer_id = ?
                ORDER BY seq DESC LIMIT 1
            """, (target_customer_id,))
        else:
            cur.execute("""
                SELECT seq, customer_id, entry_type, amount, previous_balance, new_balance, previous_last_payment_date
                FROM ledger_entries
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

        # Fetch customer info for name
        cust_id = entry["customer_id"]
        cur.execute("SELECT name FROM customers WHERE id = ?", (cust_id,))
        cust_row = cur.fetchone()
        cust_name = cust_row["name"] if cust_row else (target_customer_name or "Customer")

        # Revert in database
        prev_balance = entry["previous_balance"]
        entry_type = entry["entry_type"]
        entry_amt = entry["amount"]
        amt_display = int(entry_amt) if entry_amt.is_integer() else entry_amt

        if entry_type == "CREDIT":
            cur.execute("UPDATE customers SET current_balance = ? WHERE id = ?", (prev_balance, cust_id))
        elif entry_type == "PAYMENT":
            prev_payment_date = entry["previous_last_payment_date"]
            cur.execute("""
                UPDATE customers SET current_balance = ?, last_payment_date = ?
                WHERE id = ?
            """, (prev_balance, prev_payment_date, cust_id))

        cur.execute("DELETE FROM ledger_entries WHERE seq = ?", (entry["seq"],))
        conn.commit()

        # Discretion: Confirm undo without stating customer balance
        spoken = f"Undid the last {entry_type.lower()} entry of {amt_display} rupees for {cust_name}."
        screen_note = f"Reverted {entry_type} of Rs {amt_display}. Balance restored to Rs {prev_balance}."

        return {
            "success": True,
            "status": "SUCCESS",
            "spoken_summary": spoken,
            "screen_note": screen_note,
            "structured_data": {
                "customer_name": cust_name,
                "undone_entry_type": entry_type,
                "undone_amount": entry_amt,
                "restored_balance": prev_balance
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
    Discretion rule: spoken_summary states count of overdue accounts, never reciting balances aloud.
    """
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, phone, credit_limit, current_balance, last_payment_date
            FROM customers
            WHERE current_balance > 0
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
                    "credit_limit": r["credit_limit"],
                    "last_payment_date": r["last_payment_date"],
                    "days_overdue": days
                })

        # Order by days overdue descending
        overdue_list.sort(key=lambda x: x["days_overdue"], reverse=True)

        count = len(overdue_list)
        if count == 0:
            spoken = "All customer accounts are up to date. No accounts are 30 days overdue."
        elif count == 1:
            spoken = f"There is 1 customer account with payments overdue by 30 days or more. Details are on your screen."
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
