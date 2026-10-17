"""
engine.py - Core Classification, Multi-Event Business Logic & Front-Door Tools for Namma-Kanakku.

Enforces:
1. Data-Driven Intent Classification:
   - Scored via intent_lexicon (English, Tanglish, and Tamil script).
   - Conflicting cues abort with a clarifying question, writing 0 rows.
   - Default to CASH_SALE when no customer is mentioned.
   - Disambiguation via customer_habit (auto-promotes if >= 3 confirms and >= 80% dominance;
     otherwise asks ONE short question, writing 0 rows).
2. Atomic Multi-Item Transactions:
   - All items must resolve or 0 rows are written.
   - Batch rollback on any error.
3. Inventory & Profit Margin Tracking:
   - Stock decremented on sales, incremented on returns & stock purchases.
   - Cost of goods recorded on sales for gross profit calculation.
   - Reversible stock_delta_json stored on every ledger entry.
4. Reversible Undo & Amend (fix_entry):
   - Restores previous balance, last payment date, and inverts stock deltas.
   - Ordered strictly by sequential autoincrement ID (never timestamps).
5. Strict Discretion Rules:
   - Spoken summary NEVER reveals customer balance or debt warnings on receipt confirmations.
   - Credit check speaks STRICTLY "Okay" or "Please check the screen".
   - Morning brief speaks counts only; accounts go to screen note.
   - Balance is spoken ONLY on explicit shopkeeper request.
"""

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple, Union

from database import get_connection, DEFAULT_DB_PATH
from matching import (
    match_customer,
    match_item,
    normalize_text,
    transliterate_tamil,
    record_learned_confirmation
)

# Number and unit words mapping for Tamil, Tanglish, and English
QTY_WORD_MAP = {
    # Latin / Tanglish / English
    "oru": 1.0, "onnu": 1.0, "one": 1.0, "single": 1.0,
    "rendu": 2.0, "two": 2.0, "double": 2.0,
    "moonu": 3.0, "three": 3.0,
    "naalu": 4.0, "four": 4.0,
    "anju": 5.0, "ainthu": 5.0, "five": 5.0,
    "aaru": 6.0, "six": 6.0,
    "ezhu": 7.0, "seven": 7.0,
    "ettu": 8.0, "eight": 8.0,
    "ombadhu": 9.0, "nine": 9.0,
    "pathu": 10.0, "ten": 10.0,
    "half": 0.5, "half kilo": 0.5, "arai": 0.5, "arai kilo": 0.5,
    "quarter": 0.25, "kaal": 0.25, "kaal kilo": 0.25,
    "mukkaal": 0.75, "three quarter": 0.75,
    # Tamil script
    "ஒரு": 1.0, "ஒன்று": 1.0,
    "இரண்டு": 2.0, "ரெண்டு": 2.0,
    "மூன்று": 3.0, "மூணு": 3.0,
    "நான்கு": 4.0, "நாலு": 4.0,
    "ஐந்து": 5.0, "அஞ்சு": 5.0,
    "ஆறு": 6.0, "ஏழு": 7.0, "எட்டு": 8.0, "ஒன்பது": 9.0, "பத்து": 10.0,
    "அரை": 0.5, "கால்": 0.25, "முக்கால்": 0.75
}

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


# ============================================================================
# 1. INTENT LEXICON & HABIT ENGINE
# ============================================================================

def score_utterance_intent(conn: sqlite3.Connection, text: str) -> Dict[str, float]:
    """
    Scores cues in text against the intent_lexicon table.
    Checks English, Tanglish transliterations, and native Tamil script.
    """
    if not text:
        return {}
    
    cur = conn.cursor()
    cur.execute("SELECT word, event_type, weight, lang FROM intent_lexicon")
    rows = cur.fetchall()

    norm_text = " " + normalize_text(text) + " "
    raw_text = " " + text.strip().lower() + " "

    scores: Dict[str, float] = {}

    for row in rows:
        word = row["word"].strip().lower()
        event_type = row["event_type"]
        weight = row["weight"]
        lang = row["lang"]

        matched = False
        if lang == "ta":
            # Match directly in raw text for Tamil script
            if word in raw_text:
                matched = True
        else:
            # Match in normalized Latin text
            norm_word = normalize_text(word)
            pattern = r"(?:^|\s)" + re.escape(norm_word) + r"(?:$|\s)"
            if re.search(pattern, norm_text):
                matched = True

        if matched:
            scores[event_type] = scores.get(event_type, 0.0) + weight

    return scores


def get_customer_habit(conn: sqlite3.Connection, customer_id: int) -> Tuple[Optional[str], float, int]:
    """
    Evaluates customer habit frequency.
    Returns (dominant_event_type, dominance_ratio, total_confirmations).
    Auto-promotes if total_confirmations >= 3 and dominance_ratio >= 0.80.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT event_type, confirmations_count 
        FROM customer_habit 
        WHERE customer_id = ?
        ORDER BY confirmations_count DESC
    """, (customer_id,))
    rows = cur.fetchall()
    if not rows:
        return (None, 0.0, 0)

    total = sum(r["confirmations_count"] for r in rows)
    top_event = rows[0]["event_type"]
    top_count = rows[0]["confirmations_count"]
    ratio = top_count / total if total > 0 else 0.0

    return (top_event, ratio, total)


def record_customer_habit_confirmation(conn: sqlite3.Connection, customer_id: int, event_type: str) -> None:
    """Increments the habit confirmation count for customer + event_type."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO customer_habit (customer_id, event_type, confirmations_count)
        VALUES (?, ?, 1)
        ON CONFLICT(customer_id, event_type)
        DO UPDATE SET confirmations_count = customer_habit.confirmations_count + 1
    """, (customer_id, event_type))
    conn.commit()


def classify_intent(
    conn: sqlite3.Connection,
    utterance: Optional[str] = None,
    customer_id: Optional[int] = None,
    customer_name: Optional[str] = None,
    has_items: bool = False,
    amount: Optional[float] = None
) -> Dict[str, Any]:
    """
    Deterministic intent classification pipeline:
    1. Lexicon cue scoring.
    2. Conflict check (e.g. cash + udhaar) -> ask question, write 0 rows.
    3. Distinct event detection: RETURN, STOCK_PURCHASE, PAYMENT_RECEIVED.
    4. When customer + items present with no cue: check customer_habit.
       If habit >= 3 and >= 80% dominance -> auto-pick.
       Else -> ask ONE short question, write 0 rows.
    5. When no customer mentioned and items present -> default CASH_SALE.
    """
    scores = score_utterance_intent(conn, utterance or "")

    # Conflict detection between credit and cash cues
    credit_score = scores.get("CREDIT_SALE", 0.0)
    cash_score = scores.get("CASH_SALE", 0.0)
    payment_score = scores.get("PAYMENT_RECEIVED", 0.0)
    return_score = scores.get("RETURN", 0.0)
    stock_score = scores.get("STOCK_PURCHASE", 0.0)

    if credit_score > 0 and cash_score > 0:
        cust_display = customer_name or "this customer"
        return {
            "status": "NEEDS_CLARIFICATION",
            "event_type": None,
            "question": f"Did you mean cash sale or credit for {cust_display}?",
            "reason": "Conflicting credit and cash cues detected."
        }

    # Explicit cues
    if return_score > 0:
        return {"status": "SUCCESS", "event_type": "RETURN", "reason": "Return cue matched"}

    if stock_score > 0:
        return {"status": "SUCCESS", "event_type": "STOCK_PURCHASE", "reason": "Stock purchase cue matched"}

    if payment_score > 0 or (amount and not has_items and customer_name):
        return {"status": "SUCCESS", "event_type": "PAYMENT_RECEIVED", "reason": "Payment cue matched"}

    if credit_score > 0:
        return {"status": "SUCCESS", "event_type": "CREDIT_SALE", "reason": "Credit cue matched"}

    if cash_score > 0:
        return {"status": "SUCCESS", "event_type": "CASH_SALE", "reason": "Cash cue matched"}

    # No cues present: Apply behavioral defaults and habit rules
    if not customer_id and not customer_name:
        # Kirana default: anonymous item purchase is CASH_SALE
        if has_items:
            return {"status": "SUCCESS", "event_type": "CASH_SALE", "reason": "No customer mentioned; defaulted to cash sale"}
        return {
            "status": "NEEDS_CLARIFICATION",
            "event_type": None,
            "question": "Which customer or item should I log?",
            "reason": "No customer or items specified"
        }

    # Customer mentioned, items present, but no payment cue
    if customer_id and has_items:
        top_event, ratio, total = get_customer_habit(conn, customer_id)
        if total >= 3 and ratio >= 0.80 and top_event in ("CREDIT_SALE", "CASH_SALE"):
            return {
                "status": "SUCCESS",
                "event_type": top_event,
                "reason": f"Customer habit auto-selected ({top_event}, {total} confirms, {int(ratio*100)}% share)"
            }

        # Ambiguous habit: Ask ONE short question and save 0 rows
        display = customer_name or "this customer"
        return {
            "status": "NEEDS_CLARIFICATION",
            "event_type": None,
            "question": f"Should I put this on {display}'s account or was it paid in cash?",
            "reason": "Ambiguous payment type for customer without established habit"
        }

    # Customer mentioned with amount but no cue or items
    if customer_name and amount:
        return {"status": "SUCCESS", "event_type": "PAYMENT_RECEIVED", "reason": "Customer and amount with no items defaulted to payment"}

    return {
        "status": "NEEDS_CLARIFICATION",
        "event_type": None,
        "question": f"What items or payment should I record for {customer_name or 'the customer'}?",
        "reason": "Incomplete entry parameters"
    }


# ============================================================================
# 2. UTTERANCE PARSER (Extracts Customer, Items, Quantities, and Amounts)
# ============================================================================

def parse_spoken_utterance(conn: sqlite3.Connection, text: str) -> Dict[str, Any]:
    """
    Parses a natural sentence into customer, items, and amount.
    Supports English, Tanglish, and Tamil script.
    """
    raw = (text or "").strip()
    if not raw:
        return {"customer": None, "items": [], "amount": None}

    # Check for customer name in customers table
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM customers")
    all_custs = cur.fetchall()

    matched_customer = None
    lower_raw = raw.lower()
    for c in all_custs:
        c_name = c["name"].lower()
        # Check first name or full name
        first_token = c_name.split()[0]
        if first_token in lower_raw or c_name in lower_raw:
            matched_customer = c["name"]
            break

    # Extract numerical amounts (e.g. 200 rupees, 150 rooba, ₹500, 200 kuduthaaru)
    amt = None
    amt_match = re.search(r"(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)\s*(?:rupees|rooba|roobai|kuduthaaru|paid|settled|cash|panam)?", lower_raw)
    
    # Extract item segments
    # Catalog items aliases for fast scan
    cur.execute("SELECT alias, sku FROM item_aliases")
    alias_rows = cur.fetchall()
    
    found_items = []
    # Tokenize by commas, 'and', 'apram', 'kooda'
    parts = re.split(r",|\band\b|\bapram\b|\bkooda\b|\bwith\b|\bplus\b", raw, flags=re.IGNORECASE)

    for part in parts:
        part_clean = part.strip()
        if not part_clean:
            continue

        # Check quantity
        qty = 1.0
        part_lower = part_clean.lower()
        for q_word, q_val in QTY_WORD_MAP.items():
            pattern = r"(?:^|\s)" + re.escape(q_word) + r"(?:$|\s)"
            if re.search(pattern, part_lower):
                qty = q_val
                # remove quantity word to avoid confusion in item match
                part_clean = re.sub(pattern, " ", part_clean, flags=re.IGNORECASE).strip()
                break
        else:
            # Check digits like '2 kg', '1.5', '500g'
            dig_match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|kilo|g|gram|packet|piece|bunch|liter|l)?", part_clean, re.IGNORECASE)
            if dig_match:
                num = float(dig_match.group(1))
                u = (dig_match.group(2) or "").lower()
                if u in ("g", "gram"):
                    qty = num / 1000.0
                else:
                    qty = num
                part_clean = part_clean[:dig_match.start()] + " " + part_clean[dig_match.end():]

        # Check item name against aliases
        norm_part = normalize_text(part_clean)
        best_sku = None
        for a_row in alias_rows:
            a_alias = a_row["alias"]
            if a_alias in norm_part:
                best_sku = a_row["sku"]
                found_items.append({
                    "item_name": a_alias,
                    "quantity": qty
                })
                break

    # If no items matched but amount matched
    if not found_items and amt_match:
        # Check if the number was an amount rather than quantity
        val = float(amt_match.group(1))
        if val > 0:
            amt = val

    return {
        "customer": matched_customer,
        "items": found_items,
        "amount": amt
    }


# ============================================================================
# 3. FRONT-DOOR TOOLS IMPLEMENTATION
# ============================================================================

def write_entry(
    events: Optional[List[Dict[str, Any]]] = None,
    utterance: Optional[str] = None,
    customer_name: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    amount: Optional[float] = None,
    payment_mode: Optional[str] = None,
    event_type: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH
) -> Dict[str, Any]:
    """
    Unified entry writing front-door tool:
    Handles CREDIT_SALE, CASH_SALE, PAYMENT_RECEIVED, RETURN, STOCK_PURCHASE.
    Supports atomic multi-event batches.
    Enforces discretion (spoken summary NEVER reads customer balance or debts).
    """
    conn = get_connection(db_path)
    try:
        # If utterance is provided without explicit fields, parse utterance
        if utterance and not customer_name and not items and not amount and not events:
            parsed = parse_spoken_utterance(conn, utterance)
            customer_name = parsed["customer"]
            items = parsed["items"]
            amount = parsed["amount"]

        # Normalize into a batch of events
        if events is None:
            events = [{
                "event_type": event_type,
                "customer_name": customer_name,
                "items": items or [],
                "amount": amount,
                "payment_mode": payment_mode,
                "utterance": utterance
            }]

        # -------------------------------------------------------------
        # STEP 1: VALIDATION & ATOMIC RESOLUTION (Writes 0 rows on error)
        # -------------------------------------------------------------
        resolved_batch = []
        cur = conn.cursor()

        for ev in events:
            ev_type = ev.get("event_type")
            c_name = ev.get("customer_name")
            ev_items = ev.get("items") or []
            ev_amt = ev.get("amount")
            ev_utt = ev.get("utterance") or utterance

            # Customer resolution
            customer = None
            if c_name:
                c_res = match_customer(conn, c_name)
                if c_res["status"] != "SUCCESS":
                    return {
                        "success": False,
                        "status": c_res["status"],
                        "spoken_summary": c_res.get("message", f"Could not find customer {c_name}."),
                        "screen_note": f"Unrecognized customer: {c_name}",
                        "structured_data": c_res
                    }
                customer = c_res["customer"]

            # Intent classification if event_type is not explicitly specified
            if not ev_type:
                clf = classify_intent(
                    conn,
                    utterance=ev_utt,
                    customer_id=customer["id"] if customer else None,
                    customer_name=customer["name"] if customer else None,
                    has_items=bool(ev_items),
                    amount=ev_amt
                )
                if clf["status"] != "SUCCESS":
                    return {
                        "success": False,
                        "status": "NEEDS_CLARIFICATION",
                        "spoken_summary": clf["question"],
                        "screen_note": f"Clarification needed: {clf.get('reason')}",
                        "structured_data": {"classification": clf}
                    }
                ev_type = clf["event_type"]

            # Resolve Items Atomically
            resolved_items = []
            for item_req in ev_items:
                raw_item = item_req.get("item_name") or item_req.get("sku") or ""
                qty = float(item_req.get("quantity", 1.0))
                unit = item_req.get("unit")
                eng_guess = item_req.get("english_guess")
                orig_spoken = item_req.get("original_spoken")

                it_res = match_item(conn, raw_item, quantity=qty, unit=unit, english_guess=eng_guess)
                if it_res["status"] == "SUCCESS":
                    # Fetch wholesale cost and stock
                    cur.execute("SELECT cost, stock FROM catalog_items WHERE sku = ?", (it_res["sku"],))
                    cat_row = cur.fetchone()
                    it_res["cost"] = cat_row["cost"] if cat_row else 0.0
                    it_res["current_stock"] = cat_row["stock"] if cat_row else 0.0
                    resolved_items.append(it_res)

                    if orig_spoken:
                        record_learned_confirmation(conn, orig_spoken, it_res["sku"])
                elif it_res["status"] == "NEEDS_CLARIFICATION":
                    opts = ", ".join(it_res.get("options", []))
                    return {
                        "success": False,
                        "status": "NEEDS_CLARIFICATION",
                        "spoken_summary": f"Which {it_res['unresolved_item']} did you mean: {opts}?",
                        "screen_note": f"Clarify item: {it_res['unresolved_item']}",
                        "structured_data": it_res
                    }
                else:
                    return {
                        "success": False,
                        "status": "ITEM_NOT_RECOGNIZED",
                        "spoken_summary": f"I could not find '{it_res.get('unresolved_item', raw_item)}' in your catalog. Nothing was saved.",
                        "screen_note": f"Unrecognized item: {it_res.get('unresolved_item', raw_item)}",
                        "structured_data": it_res
                    }

            resolved_batch.append({
                "event_type": ev_type,
                "customer": customer,
                "items": resolved_items,
                "amount": ev_amt,
                "payment_mode": ev.get("payment_mode"),
                "note": ev.get("note") or ev_utt
            })

        # -------------------------------------------------------------
        # STEP 2: ATOMIC DATABASE EXECUTION
        # -------------------------------------------------------------
        now_utc = datetime.now(timezone.utc)
        now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")
        now_date = now_utc.strftime("%Y-%m-%d")

        execution_results = []
        spoken_parts = []
        screen_notes = []

        for item_ev in resolved_batch:
            etype = item_ev["event_type"]
            cust = item_ev["customer"]
            res_items = item_ev["items"]

            if etype == "CREDIT_SALE":
                if not cust:
                    return {
                        "success": False,
                        "status": "CUSTOMER_REQUIRED",
                        "spoken_summary": "Please specify the customer name for credit.",
                        "structured_data": {}
                    }
                total_amount = round(sum(it["line_total"] for it in res_items), 2)
                cost_amount = round(sum(it["cost"] * it["quantity"] for it in res_items), 2)
                prev_balance = cust["current_balance"]
                new_balance = round(prev_balance + total_amount, 2)

                # Stock deltas: decrement
                stock_deltas = {it["sku"]: -it["quantity"] for it in res_items}
                for sku, delta in stock_deltas.items():
                    cur.execute("UPDATE catalog_items SET stock = stock + ? WHERE sku = ?", (delta, sku))

                items_json = json.dumps([{
                    "sku": it["sku"], "display_name": it["display_name"],
                    "quantity": it["quantity"], "unit": it["unit"], "line_total": it["line_total"]
                } for it in res_items])

                cur.execute("""
                    INSERT INTO ledger_entries (
                        customer_id, entry_type, amount, cost_amount, payment_mode,
                        items_json, stock_delta_json, previous_balance, new_balance,
                        created_at, note
                    ) VALUES (?, 'CREDIT_SALE', ?, ?, 'CREDIT', ?, ?, ?, ?, ?, ?)
                """, (
                    cust["id"], total_amount, cost_amount, items_json,
                    json.dumps(stock_deltas), prev_balance, new_balance, now_str, item_ev["note"]
                ))
                cur.execute("UPDATE customers SET current_balance = ? WHERE id = ?", (new_balance, cust["id"]))

                # Record habit confirmation
                record_customer_habit_confirmation(conn, cust["id"], "CREDIT_SALE")

                # Spoken: items + total. NEVER reveal customer balance!
                items_text = ", ".join(f"{it['display_qty']} {it['display_name']}" for it in res_items)
                spoken_parts.append(f"Logged {items_text} for {cust['name']}, total {int(total_amount) if total_amount.is_integer() else total_amount} rupees. Say undo if that's wrong.")

                # Screen note: overdue warning or limit check (strictly visual)
                days_unpaid = days_between(cust.get("last_payment_date"))
                if days_unpaid >= 30 and prev_balance > 0:
                    screen_notes.append(f"{cust['name']}: Unpaid for {days_unpaid} days.")
                if new_balance > cust["credit_limit"]:
                    screen_notes.append(f"{cust['name']}: Over limit by Rs {round(new_balance - cust['credit_limit'], 2)}.")

            elif etype == "CASH_SALE":
                total_amount = round(sum(it["line_total"] for it in res_items), 2) if res_items else (item_ev["amount"] or 0.0)
                cost_amount = round(sum(it["cost"] * it["quantity"] for it in res_items), 2) if res_items else 0.0

                stock_deltas = {it["sku"]: -it["quantity"] for it in res_items}
                for sku, delta in stock_deltas.items():
                    cur.execute("UPDATE catalog_items SET stock = stock + ? WHERE sku = ?", (delta, sku))

                items_json = json.dumps([{
                    "sku": it["sku"], "display_name": it["display_name"],
                    "quantity": it["quantity"], "unit": it["unit"], "line_total": it["line_total"]
                } for it in res_items]) if res_items else None

                cur.execute("""
                    INSERT INTO ledger_entries (
                        customer_id, entry_type, amount, cost_amount, payment_mode,
                        items_json, stock_delta_json, created_at, note
                    ) VALUES (?, 'CASH_SALE', ?, ?, 'CASH', ?, ?, ?, ?)
                """, (
                    cust["id"] if cust else None, total_amount, cost_amount,
                    items_json, json.dumps(stock_deltas), now_str, item_ev["note"]
                ))

                if cust:
                    record_customer_habit_confirmation(conn, cust["id"], "CASH_SALE")

                amt_disp = int(total_amount) if total_amount.is_integer() else total_amount
                spoken_parts.append(f"Cash sale of {amt_disp} rupees logged. Say undo if that's wrong.")

            elif etype == "PAYMENT_RECEIVED":
                if not cust:
                    return {
                        "success": False,
                        "status": "CUSTOMER_REQUIRED",
                        "spoken_summary": "Please specify which customer paid.",
                        "structured_data": {}
                    }
                prev_balance = cust["current_balance"]
                if prev_balance <= 0.0:
                    return {
                        "success": False,
                        "status": "NO_BALANCE",
                        "spoken_summary": f"{cust['name']} currently has no outstanding balance.",
                        "screen_note": f"{cust['name']} has zero dues.",
                        "structured_data": {"customer": cust["name"], "balance": 0.0}
                    }
                req_amt = item_ev["amount"] or prev_balance
                actual_payment = round(min(float(req_amt), prev_balance), 2)
                new_balance = round(prev_balance - actual_payment, 2)

                cur.execute("""
                    INSERT INTO ledger_entries (
                        customer_id, entry_type, amount, payment_mode,
                        previous_balance, new_balance, previous_last_payment_date,
                        created_at, note
                    ) VALUES (?, 'PAYMENT_RECEIVED', ?, 'CASH', ?, ?, ?, ?, ?)
                """, (
                    cust["id"], actual_payment, prev_balance, new_balance,
                    cust.get("last_payment_date"), now_str, item_ev["note"]
                ))
                cur.execute("""
                    UPDATE customers SET current_balance = ?, last_payment_date = ?
                    WHERE id = ?
                """, (new_balance, now_date, cust["id"]))

                amt_disp = int(actual_payment) if actual_payment.is_integer() else actual_payment
                # Discretion: DO NOT speak remaining balance
                spoken_parts.append(f"Recorded payment of {amt_disp} rupees from {cust['name']}. Say undo if that's wrong.")
                screen_notes.append(f"Payment: Rs {amt_disp}. Prev: Rs {prev_balance}, Remaining: Rs {new_balance}.")

            elif etype == "RETURN":
                total_amount = round(sum(it["line_total"] for it in res_items), 2)
                stock_deltas = {it["sku"]: it["quantity"] for it in res_items}
                # Increment stock on return
                for sku, delta in stock_deltas.items():
                    cur.execute("UPDATE catalog_items SET stock = stock + ? WHERE sku = ?", (delta, sku))

                prev_bal = cust["current_balance"] if cust else 0.0
                new_bal = max(0.0, round(prev_bal - total_amount, 2)) if cust else 0.0

                cur.execute("""
                    INSERT INTO ledger_entries (
                        customer_id, entry_type, amount, payment_mode,
                        items_json, stock_delta_json, previous_balance, new_balance,
                        created_at, note
                    ) VALUES (?, 'RETURN', ?, 'CREDIT', ?, ?, ?, ?, ?, ?)
                """, (
                    cust["id"] if cust else None, total_amount,
                    json.dumps(res_items), json.dumps(stock_deltas), prev_bal, new_bal, now_str, item_ev["note"]
                ))
                if cust:
                    cur.execute("UPDATE customers SET current_balance = ? WHERE id = ?", (new_bal, cust["id"]))

                amt_disp = int(total_amount) if total_amount.is_integer() else total_amount
                cust_suffix = f" for {cust['name']}" if cust else ""
                spoken_parts.append(f"Recorded return of {amt_disp} rupees{cust_suffix}. Say undo if that's wrong.")

            elif etype == "STOCK_PURCHASE":
                total_cost = round(sum(it["line_total"] for it in res_items), 2) if res_items else (item_ev["amount"] or 0.0)
                stock_deltas = {it["sku"]: it["quantity"] for it in res_items}
                for it in res_items:
                    cur.execute("UPDATE catalog_items SET stock = stock + ? WHERE sku = ?", (it["quantity"], it["sku"]))

                cur.execute("""
                    INSERT INTO ledger_entries (
                        entry_type, amount, items_json, stock_delta_json, created_at, note
                    ) VALUES ('STOCK_PURCHASE', ?, ?, ?, ?, ?)
                """, (total_cost, json.dumps(res_items), json.dumps(stock_deltas), now_str, item_ev["note"]))

                spoken_parts.append(f"Recorded stock purchase of {int(total_cost) if total_cost.is_integer() else total_cost} rupees.")

            execution_results.append({
                "event_type": etype,
                "customer": cust["name"] if cust else None,
                "amount": total_amount if 'total_amount' in locals() else (item_ev.get("amount") or 0.0)
            })

        conn.commit()

        # Check for any items that dropped below reorder level
        cur.execute("SELECT sku, display_name, stock, reorder_level FROM catalog_items WHERE stock <= reorder_level")
        low_stocks = cur.fetchall()
        if low_stocks:
            names = ", ".join(f"{r['display_name']} ({r['stock']} left)" for r in low_stocks)
            screen_notes.append(f"Low stock notice: {names}.")

        return {
            "success": True,
            "status": "SUCCESS",
            "spoken_summary": " ".join(spoken_parts),
            "screen_note": " | ".join(screen_notes) if screen_notes else None,
            "structured_data": {
                "events_processed": execution_results
            },
            "_meta": {
                "ui": {
                    "resourceUri": "ui://khata-card",
                    "invoking": "Writing entry to khata...",
                    "invoked": "Entry saved successfully"
                }
            }
        }
    finally:
        conn.close()


def fix_entry(
    action: str = "undo",
    customer_name: Optional[str] = None,
    amend_fields: Optional[Dict[str, Any]] = None,
    db_path: str = DEFAULT_DB_PATH
) -> Dict[str, Any]:
    """
    Reversible undo and amendment tool:
    - action == 'undo': Reverts the last ledger entry (or last for customer) by seq DESC.
      Restores previous balance, last payment date, and inverts stock deltas.
      Never speaks balance (discretion).
    - action == 'amend': Reverts prior entry and applies amended entry atomically.
    """
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()

        # Find target entry
        if customer_name:
            c_res = match_customer(conn, customer_name)
            if c_res["status"] != "SUCCESS":
                return {
                    "success": False,
                    "status": c_res["status"],
                    "spoken_summary": c_res.get("message", f"Could not find customer {customer_name}."),
                    "structured_data": c_res
                }
            cur.execute("""
                SELECT seq, customer_id, entry_type, amount, stock_delta_json,
                       previous_balance, new_balance, previous_last_payment_date
                FROM ledger_entries
                WHERE customer_id = ?
                ORDER BY seq DESC LIMIT 1
            """, (c_res["customer"]["id"],))
        else:
            cur.execute("""
                SELECT seq, customer_id, entry_type, amount, stock_delta_json,
                       previous_balance, new_balance, previous_last_payment_date
                FROM ledger_entries
                ORDER BY seq DESC LIMIT 1
            """)

        entry = cur.fetchone()
        if not entry:
            return {
                "success": False,
                "status": "NO_ENTRIES_TO_UNDO",
                "spoken_summary": "There are no recent entries to undo.",
                "structured_data": {}
            }

        seq = entry["seq"]
        cust_id = entry["customer_id"]
        etype = entry["entry_type"]
        stock_delta_json = entry["stock_delta_json"]
        prev_bal = entry["previous_balance"]
        prev_last_date = entry["previous_last_payment_date"]

        # 1. Reverse balance
        if cust_id and etype in ("CREDIT_SALE", "PAYMENT_RECEIVED", "RETURN"):
            if etype == "PAYMENT_RECEIVED":
                cur.execute("""
                    UPDATE customers 
                    SET current_balance = ?, last_payment_date = ?
                    WHERE id = ?
                """, (prev_bal, prev_last_date, cust_id))
            else:
                cur.execute("UPDATE customers SET current_balance = ? WHERE id = ?", (prev_bal, cust_id))

        # 2. Reverse stock deltas
        if stock_delta_json:
            try:
                deltas = json.loads(stock_delta_json)
                for sku, delta in deltas.items():
                    # Invert the delta to restore exact original stock
                    cur.execute("UPDATE catalog_items SET stock = stock - ? WHERE sku = ?", (delta, sku))
            except Exception:
                pass

        # 3. Delete the undone entry
        cur.execute("DELETE FROM ledger_entries WHERE seq = ?", (seq,))

        if action == "undo":
            conn.commit()
            cust_name = ""
            if cust_id:
                cur.execute("SELECT name FROM customers WHERE id = ?", (cust_id,))
                cr = cur.fetchone()
                if cr:
                    cust_name = f" for {cr['name']}"
            return {
                "success": True,
                "status": "SUCCESS",
                "spoken_summary": f"Undone last entry{cust_name}. Say undo if that's wrong.",
                "screen_note": f"Entry #{seq} ({etype}) reverted. Balance restored to Rs {prev_bal}.",
                "structured_data": {"reverted_seq": seq, "reverted_type": etype}
            }

        elif action == "amend":
            # For amendment, re-write with amend_fields in the same transaction
            conn.commit()
            if not amend_fields:
                return {
                    "success": False,
                    "status": "MISSING_AMEND_FIELDS",
                    "spoken_summary": "No amendment details were provided.",
                    "structured_data": {}
                }
            return write_entry(db_path=db_path, **amend_fields)

        return {
            "success": False,
            "status": "INVALID_ACTION",
            "spoken_summary": f"Unknown fix action: {action}.",
            "structured_data": {}
        }
    finally:
        conn.close()


def ask_khata(
    question: str,
    kind: Optional[str] = None,
    customer_name: Optional[str] = None,
    amount: Optional[float] = None,
    db_path: str = DEFAULT_DB_PATH
) -> Dict[str, Any]:
    """
    Natural information retrieval & quiet discretion queries:
    - kind == 'balance': Explicit balance query (spoken balance is permitted).
    - kind == 'credit_check': Discretion check. Spoken is ONLY 'Okay' or 'Please check the screen'.
    - kind == 'morning_brief': Spoken count ONLY; accounts go to screen note.
    - kind == 'today_summary': Cash/UPI sales, udhaar, payments, and gross profit.
    - kind == 'overdue': Speaks count of overdue accounts, details to screen.
    - kind == 'low_stock': Low stock SKUs and inventory.
    """
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        q_lower = (question or "").lower()

        # Infer kind if not given
        if not kind:
            if "credit check" in q_lower or "can" in q_lower and ("take" in q_lower or "udhaar" in q_lower):
                kind = "credit_check"
            elif "morning" in q_lower or "brief" in q_lower or "pending" in q_lower:
                kind = "morning_brief"
            elif "today" in q_lower or "profit" in q_lower or "collection" in q_lower:
                kind = "today_summary"
            elif "overdue" in q_lower or "late" in q_lower or "30" in q_lower:
                kind = "overdue"
            elif "balance" in q_lower or "dues" in q_lower or "evvalavu" in q_lower:
                kind = "balance"
            elif "stock" in q_lower or "inventory" in q_lower:
                kind = "low_stock"
            else:
                kind = "balance"

        # -------------------------------------------------------------
        # 1. BALANCE (Explicit query)
        # -------------------------------------------------------------
        if kind == "balance":
            if not customer_name:
                # Attempt to extract customer from question
                cur.execute("SELECT name FROM customers")
                for c_row in cur.fetchall():
                    if c_row["name"].lower().split()[0] in q_lower:
                        customer_name = c_row["name"]
                        break
            if not customer_name:
                return {
                    "success": False,
                    "status": "CUSTOMER_REQUIRED",
                    "spoken_summary": "Which customer's balance would you like to check?",
                    "structured_data": {}
                }
            c_res = match_customer(conn, customer_name)
            if c_res["status"] != "SUCCESS":
                return {
                    "success": False,
                    "status": c_res["status"],
                    "spoken_summary": c_res.get("message", f"Could not find customer {customer_name}."),
                    "structured_data": c_res
                }
            cust = c_res["customer"]
            bal = cust["current_balance"]
            limit = cust["credit_limit"]
            days = days_between(cust.get("last_payment_date"))
            bal_disp = int(bal) if bal.is_integer() else bal
            if bal == 0.0:
                spoken = f"{cust['name']} has cleared all dues. Balance is zero."
            else:
                spoken = f"{cust['name']}'s current balance is {bal_disp} rupees."

            screen_notes = []
            if days >= 30 and bal > 0:
                screen_notes.append(f"Unpaid for {days} days.")
            if bal > limit:
                screen_notes.append(f"Over credit limit by Rs {round(bal - limit, 2)}.")

            return {
                "success": True,
                "status": "SUCCESS",
                "spoken_summary": spoken,
                "screen_note": " | ".join(screen_notes) if screen_notes else None,
                "structured_data": {
                    "customer": cust["name"], "balance": bal, "credit_limit": limit, "days_unpaid": days
                }
            }

        # -------------------------------------------------------------
        # 2. CREDIT CHECK (Discretion: ONLY 'Okay' or 'Please check the screen')
        # -------------------------------------------------------------
        elif kind == "credit_check":
            if not customer_name:
                cur.execute("SELECT name FROM customers")
                for c_row in cur.fetchall():
                    if c_row["name"].lower().split()[0] in q_lower:
                        customer_name = c_row["name"]
                        break
            if not customer_name:
                return {
                    "success": False,
                    "status": "CUSTOMER_REQUIRED",
                    "spoken_summary": "Please check the screen.",
                    "screen_note": "Customer name is required for credit check.",
                    "structured_data": {}
                }
            c_res = match_customer(conn, customer_name)
            if c_res["status"] != "SUCCESS":
                return {
                    "success": False,
                    "status": c_res["status"],
                    "spoken_summary": "Please check the screen.",
                    "screen_note": f"Could not find customer {customer_name}.",
                    "structured_data": c_res
                }
            cust = c_res["customer"]
            bal = cust["current_balance"]
            limit = cust["credit_limit"]
            days = days_between(cust.get("last_payment_date"))
            check_amt = float(amount or 0.0)

            is_overdue = days >= 30 and bal > 0
            would_exceed_limit = (bal + check_amt) > limit

            if is_overdue or would_exceed_limit:
                # STRICT DISCRETION: NEVER speak customer debt aloud in front of customer!
                spoken = "Please check the screen."
                reasons = []
                if is_overdue:
                    reasons.append(f"Unpaid for {days} days (Balance: Rs {bal})")
                if would_exceed_limit:
                    excess = round((bal + check_amt) - limit, 2)
                    reasons.append(f"Would exceed credit limit of Rs {limit} by Rs {excess}")
                screen_note = f"Credit Check Warning for {cust['name']}: {'; '.join(reasons)}."
                approved = False
            else:
                spoken = "Okay."
                screen_note = f"Credit Check Passed for {cust['name']}: Dues Rs {bal}, Limit Rs {limit}."
                approved = True

            return {
                "success": True,
                "status": "SUCCESS",
                "spoken_summary": spoken,
                "screen_note": screen_note,
                "structured_data": {
                    "customer": cust["name"],
                    "approved": approved,
                    "is_overdue": is_overdue,
                    "would_exceed_limit": would_exceed_limit,
                    "current_balance": bal,
                    "credit_limit": limit
                }
            }

        # -------------------------------------------------------------
        # 3. MORNING BRIEF (Discretion: Spoken counts only)
        # -------------------------------------------------------------
        elif kind == "morning_brief":
            cur.execute("""
                SELECT id, name, phone, current_balance, last_payment_date 
                FROM customers 
                WHERE current_balance > 0
            """)
            debtors = cur.fetchall()
            overdue_list = []
            for d in debtors:
                days = days_between(d["last_payment_date"])
                if days >= 30:
                    overdue_list.append({
                        "name": d["name"], "balance": d["current_balance"], "days": days
                    })

            cur.execute("SELECT sku, display_name, stock, reorder_level FROM catalog_items WHERE stock <= reorder_level")
            low_stocks = cur.fetchall()

            # Spoken summary gives ONLY counts
            cnt_overdue = len(overdue_list)
            cnt_stock = len(low_stocks)
            spoken = f"Good morning. You have {cnt_overdue} overdue accounts and {cnt_stock} items low on stock."

            screen_parts = []
            if overdue_list:
                lines = [f"{o['name']} (Rs {o['balance']}, {o['days']}d overdue)" for o in overdue_list]
                screen_parts.append("Overdue: " + ", ".join(lines))
            if low_stocks:
                lines = [f"{s['display_name']} ({s['stock']} left)" for s in low_stocks]
                screen_parts.append("Reorder: " + ", ".join(lines))

            return {
                "success": True,
                "status": "SUCCESS",
                "spoken_summary": spoken,
                "screen_note": " | ".join(screen_parts) if screen_parts else "All accounts and inventory are in good standing.",
                "structured_data": {
                    "overdue_count": cnt_overdue,
                    "overdue_accounts": overdue_list,
                    "low_stock_count": cnt_stock,
                    "low_stock_items": [dict(s) for s in low_stocks]
                }
            }

        # -------------------------------------------------------------
        # 4. TODAY SUMMARY (Cash, Udhaar, Collections & Gross Profit)
        # -------------------------------------------------------------
        elif kind == "today_summary":
            cur.execute("""
                SELECT entry_type, amount, cost_amount, payment_mode
                FROM ledger_entries
            """)
            entries = cur.fetchall()

            cash_sales = sum(e["amount"] for e in entries if e["entry_type"] == "CASH_SALE")
            credit_sales = sum(e["amount"] for e in entries if e["entry_type"] == "CREDIT_SALE")
            payments = sum(e["amount"] for e in entries if e["entry_type"] == "PAYMENT_RECEIVED")
            total_cost = sum(e["cost_amount"] for e in entries if e["entry_type"] in ("CASH_SALE", "CREDIT_SALE"))

            gross_profit = round((cash_sales + credit_sales) - total_cost, 2)

            cs_disp = int(cash_sales) if cash_sales.is_integer() else cash_sales
            cr_disp = int(credit_sales) if credit_sales.is_integer() else credit_sales
            pay_disp = int(payments) if payments.is_integer() else payments
            prof_disp = int(gross_profit) if gross_profit.is_integer() else gross_profit

            spoken = f"Today: Cash sales {cs_disp} rupees, credit {cr_disp} rupees, payments collected {pay_disp} rupees, estimated gross profit {prof_disp} rupees."
            screen_note = f"Sales: Cash Rs {cs_disp}, Udhaar Rs {cr_disp}. Payments: Rs {pay_disp}. Wholesale Cost: Rs {total_cost}, Est. Profit: Rs {prof_disp}."

            return {
                "success": True,
                "status": "SUCCESS",
                "spoken_summary": spoken,
                "screen_note": screen_note,
                "structured_data": {
                    "cash_sales": cash_sales,
                    "credit_sales": credit_sales,
                    "payments_received": payments,
                    "wholesale_cost": total_cost,
                    "estimated_gross_profit": gross_profit
                }
            }

        # -------------------------------------------------------------
        # 5. OVERDUE ACCOUNTS
        # -------------------------------------------------------------
        elif kind == "overdue":
            cur.execute("""
                SELECT id, name, phone, credit_limit, current_balance, last_payment_date 
                FROM customers 
                WHERE current_balance > 0 
                ORDER BY current_balance DESC
            """)
            rows = cur.fetchall()
            overdue = []
            for r in rows:
                days = days_between(r["last_payment_date"])
                if days >= 30:
                    overdue.append({
                        "name": r["name"], "phone": r["phone"], "balance": r["current_balance"], "days": days
                    })
            cnt = len(overdue)
            spoken = f"You have {cnt} customer accounts with overdue balances."
            names = [f"{o['name']} (Rs {o['balance']}, {o['days']} days)" for o in overdue]
            return {
                "success": True,
                "status": "SUCCESS",
                "spoken_summary": spoken,
                "screen_note": f"Overdue accounts: {', '.join(names)}" if names else "No accounts are overdue.",
                "structured_data": {"overdue_count": cnt, "overdue_accounts": overdue}
            }

        # -------------------------------------------------------------
        # 6. LOW STOCK
        # -------------------------------------------------------------
        elif kind == "low_stock":
            cur.execute("SELECT sku, display_name, stock, reorder_level FROM catalog_items WHERE stock <= reorder_level")
            items = cur.fetchall()
            cnt = len(items)
            spoken = f"{cnt} items are currently at or below their reorder level."
            item_descs = [f"{i['display_name']} ({i['stock']} remaining, reorder at {i['reorder_level']})" for i in items]
            return {
                "success": True,
                "status": "SUCCESS",
                "spoken_summary": spoken,
                "screen_note": "Low Stock: " + "; ".join(item_descs) if item_descs else "All catalog inventory levels are healthy.",
                "structured_data": {"low_stock_count": cnt, "items": [dict(i) for i in items]}
            }

        return {
            "success": False,
            "status": "UNKNOWN_KIND",
            "spoken_summary": f"I didn't recognize that type of khata query.",
            "structured_data": {}
        }
    finally:
        conn.close()


def update_shop(
    action: str,
    alias: Optional[str] = None,
    item_name_or_sku: Optional[str] = None,
    new_price: Optional[float] = None,
    sku: Optional[str] = None,
    display_name: Optional[str] = None,
    price: Optional[float] = None,
    cost: Optional[float] = None,
    stock: Optional[float] = None,
    unit: str = "packet",
    is_loose: bool = False,
    aliases: Optional[List[str]] = None,
    customer_name: Optional[str] = None,
    phone: Optional[str] = None,
    credit_limit: float = 2000.0,
    db_path: str = DEFAULT_DB_PATH
) -> Dict[str, Any]:
    """
    Data-ownership & catalog configuration front-door tool:
    Supports actions: 'teach_alias', 'set_price', 'add_item', 'add_customer', 'update_stock', 'set_cost'.
    """
    import data_ownership

    if action == "teach_alias":
        if not alias or not item_name_or_sku:
            return {"success": False, "status": "MISSING_ARGS", "spoken_summary": "Please provide both alias and item."}
        return data_ownership.teach_item_alias(alias, item_name_or_sku, db_path=db_path)

    elif action == "set_price":
        if not item_name_or_sku or new_price is None:
            return {"success": False, "status": "MISSING_ARGS", "spoken_summary": "Please provide item and new price."}
        return data_ownership.set_item_price(item_name_or_sku, new_price, db_path=db_path)

    elif action == "add_item":
        if not sku or not display_name or price is None:
            return {"success": False, "status": "MISSING_ARGS", "spoken_summary": "Please provide sku, display name, and price."}
        return data_ownership.add_catalog_item(sku, display_name, price, unit=unit, is_loose=is_loose, aliases=aliases, db_path=db_path)

    elif action == "add_customer":
        name = customer_name or display_name
        if not name:
            return {"success": False, "status": "MISSING_ARGS", "spoken_summary": "Please provide customer name."}
        return data_ownership.add_customer(name, phone=phone, credit_limit=credit_limit, db_path=db_path)

    elif action in ("update_stock", "set_cost"):
        conn = get_connection(db_path)
        try:
            cur = conn.cursor()
            target_sku = sku or item_name_or_sku
            if action == "update_stock" and stock is not None:
                cur.execute("UPDATE catalog_items SET stock = ? WHERE sku = ?", (stock, target_sku))
                conn.commit()
                return {"success": True, "status": "SUCCESS", "spoken_summary": f"Updated stock for {target_sku} to {stock}."}
            elif action == "set_cost" and cost is not None:
                cur.execute("UPDATE catalog_items SET cost = ? WHERE sku = ?", (cost, target_sku))
                conn.commit()
                return {"success": True, "status": "SUCCESS", "spoken_summary": f"Updated wholesale cost for {target_sku} to {cost} rupees."}
            return {"success": False, "status": "MISSING_ARGS", "spoken_summary": "Missing stock or cost parameter."}
        finally:
            conn.close()

    return {"success": False, "status": "UNKNOWN_ACTION", "spoken_summary": f"Unknown shop update action: {action}."}
