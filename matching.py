"""
matching.py - Deterministic matching engine for KiranaFlow.

Pipeline order (strict):
1. Exact alias match on normalized text (Tamil script transliterated to Latin first).
2. Phonetic key match (collapsing th/t, dh/d, aa/a, ee/i, oo/u, zh/l, doubled letters, etc.).
3. Learned aliases (auto-promoted if >= 2 confirmations and >= 2x runner-up).
4. Fuzzy match (rapidfuzz WRatio on phonetic keys: score >= 90, unique SKU, gap >= 8).
5. Alexa+'s english_guess fallback (runs pipeline steps 1-4 on english_guess).
6. Otherwise return NEEDS_CLARIFICATION (up to 3 options) or ITEM_NOT_RECOGNIZED.
   Generic words (oil, ennai, paruppu, dal, soap, rice) trigger clarification until learned.
   Never silently pick.
"""

import re
import sqlite3
from typing import Optional, List, Dict, Any, Tuple
from rapidfuzz import fuzz

# Tamil script Unicode mappings
TAMIL_VOWELS = {
    'அ': 'a', 'ஆ': 'aa', 'இ': 'i', 'ஈ': 'ee', 'உ': 'u', 'ஊ': 'oo',
    'எ': 'e', 'ஏ': 'ae', 'ஐ': 'ai', 'ஒ': 'o', 'ஓ': 'oa', 'ஔ': 'au', 'ஃ': 'k'
}
TAMIL_CONSONANTS = {
    'க': 'k', 'ங': 'ng', 'ச': 's', 'ஞ': 'nj', 'ட': 't', 'ண': 'n',
    'த': 'th', 'ந': 'n', 'ப': 'p', 'ம': 'm', 'ய': 'y', 'ர': 'r',
    'ல': 'l', 'வ': 'v', 'ழ': 'zh', 'ள': 'l', 'ற': 'r', 'ன': 'n',
    'ஜ': 'j', 'ஷ': 'sh', 'ஸ': 's', 'ஹ': 'h'
}
TAMIL_SIGNS = {
    'ா': 'aa', 'ி': 'i', 'ீ': 'ee', 'ு': 'u', 'ூ': 'oo',
    'ெ': 'e', 'ே': 'ae', 'ை': 'ai', 'ொ': 'o', 'ோ': 'oa', 'ௌ': 'au',
    '்': ''  # Pulli (virama) suppresses default 'a'
}

# Generic words that require clarification until learned
GENERIC_ITEM_MAP = {
    "oil": ["sunflower_oil_1l", "groundnut_oil_1l"],
    "ennai": ["sunflower_oil_1l", "groundnut_oil_1l"],
    "yennai": ["sunflower_oil_1l", "groundnut_oil_1l"],
    "oil packet": ["sunflower_oil_1l", "groundnut_oil_1l"],
    "soap": ["bath_soap", "washing_soap"],
    "sope": ["bath_soap", "washing_soap"],
    "dal": ["toor_dal"],
    "dhal": ["toor_dal"],
    "paruppu": ["toor_dal"],
    "rice": ["ponni_rice"],
}

CUSTOMER_FILLER_WORDS = {
    "tab", "khata", "account", "kitta", "uku", "ku", "oda", "da", "de",
    "please", "bill", "le", "la", "lae"
}

def transliterate_tamil(text: str) -> str:
    """Accurately transliterates Tamil script to Latin alphabet."""
    if not text:
        return ""
    res = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in TAMIL_VOWELS:
            res.append(TAMIL_VOWELS[c])
            i += 1
        elif c in TAMIL_CONSONANTS:
            base = TAMIL_CONSONANTS[c]
            if i + 1 < n and text[i + 1] in TAMIL_SIGNS:
                sign = TAMIL_SIGNS[text[i + 1]]
                res.append(base + sign)
                i += 2
            else:
                # Default inherent vowel 'a'
                res.append(base + 'a')
                i += 1
        else:
            res.append(c)
            i += 1
    return "".join(res)

def normalize_text(text: str) -> str:
    """Transliterates Tamil if present, strips punctuation, normalizes spacing."""
    if not text:
        return ""
    # Transliterate Tamil characters first
    t = transliterate_tamil(text.strip().lower())
    # Replace punctuation with space
    t = re.sub(r"[^\w\s]", " ", t)
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    return t

def make_phonetic_key(text: str) -> str:
    """
    Collapses common phonetic variations in Indian English / Tanglish / Tamil transliteration:
    - th -> t, dh -> d
    - aa -> a
    - ee, ea -> i
    - oo, ou -> u
    - zh, lh -> l
    - w -> v
    - y at word start before e -> e (yennai -> ennai)
    - doubled consonants collapsed (rr->r, tt->t, etc.)
    """
    t = normalize_text(text)
    if not t:
        return ""

    words = t.split()
    processed_words = []
    for w in words:
        if w.startswith("ye"):
            w = w[1:]  # yennai -> ennai
        w = w.replace("th", "t").replace("dh", "d")
        w = w.replace("aa", "a")
        w = w.replace("ee", "i").replace("ea", "i")
        w = w.replace("oo", "u").replace("ou", "u")
        w = w.replace("zh", "l").replace("lh", "l")
        w = w.replace("ph", "f")
        w = w.replace("w", "v")
        w = w.replace("ck", "k")
        # Collapse doubled letters (tt -> t, pp -> p, etc.)
        w = re.sub(r"(.)\1+", r"\1", w)
        processed_words.append(w)
    return " ".join(processed_words)

def parse_quantity_and_unit(qty_input: Any, unit_input: Optional[str] = None) -> Tuple[float, str]:
    """
    Parses spoken quantities:
    - 'half kilo' / 'half' -> 0.5 kg
    - grams converted to kg: 500g -> 0.5 kg, 250g -> 0.25 kg
    """
    raw_str = str(qty_input).strip().lower()
    unit = (unit_input or "").strip().lower()

    # Check for text fractions
    if "half" in raw_str or "1/2" in raw_str:
        num = 0.5
    elif "quarter" in raw_str or "1/4" in raw_str:
        num = 0.25
    elif "three quarter" in raw_str or "3/4" in raw_str:
        num = 0.75
    else:
        # Extract numeric component
        match = re.search(r"[-+]?\d*\.?\d+", raw_str)
        num = float(match.group()) if match else 1.0

    # Unit normalization
    if "kilo" in raw_str or "kg" in raw_str or unit in ("kg", "kilo", "kilogram", "kilograms"):
        return num, "kg"
    elif "gram" in raw_str or "g" in raw_str or unit in ("g", "gram", "grams", "gm"):
        # Grams convert to kg for loose items
        return num / 1000.0, "kg"
    elif "packet" in raw_str or unit in ("packet", "pkt", "packets"):
        return num, "packet"
    elif "piece" in raw_str or unit in ("piece", "pcs", "piece"):
        return num, "piece"
    elif "bunch" in raw_str or unit in ("bunch", "bunches"):
        return num, "bunch"
    
    return num, unit or "unit"

def match_customer(conn: sqlite3.Connection, raw_name: str) -> Dict[str, Any]:
    """
    Matches customer name with filler-word stripping and ambiguity detection.
    - 'Ramesh tab' -> 'Ramesh Teacher'
    - 'Karthik' -> Ambiguous between 'Karthik 3B' and 'Karthik 5A'
    """
    norm = normalize_text(raw_name)
    words = [w for w in norm.split() if w not in CUSTOMER_FILLER_WORDS]
    clean_name = " ".join(words) if words else norm

    cur = conn.cursor()
    cur.execute("SELECT id, name, phone, credit_limit, current_balance, last_payment_date FROM customers")
    customers = [dict(row) for row in cur.fetchall()]

    # 1. Exact match
    for c in customers:
        if c["name"].lower() == clean_name:
            return {"status": "SUCCESS", "customer": c}

    # 2. Substring match (e.g., 'Ramesh' matches 'Ramesh Teacher', 'Karthik' matches 3B and 5A)
    matches = []
    for c in customers:
        c_name_lower = c["name"].lower()
        # Direct word containment
        if clean_name in c_name_lower or any(w in c_name_lower.split() for w in words):
            matches.append(c)

    if len(matches) == 1:
        return {"status": "SUCCESS", "customer": matches[0]}
    elif len(matches) > 1:
        options = [c["name"] for c in matches]
        return {
            "status": "CUSTOMER_AMBIGUOUS",
            "message": f"Multiple customers match '{raw_name}': {', '.join(options)}. Which one?",
            "options": options
        }

    # 3. Fuzzy match on customers
    best_c = None
    best_score = 0
    runner_up = 0
    for c in customers:
        score = fuzz.WRatio(clean_name, c["name"].lower())
        if score > best_score:
            runner_up = best_score
            best_score = score
            best_c = c
        elif score > runner_up:
            runner_up = score

    if best_score >= 85 and (best_score - runner_up >= 8):
        return {"status": "SUCCESS", "customer": best_c}

    return {
        "status": "CUSTOMER_NOT_FOUND",
        "message": f"Customer '{raw_name}' was not found in your customer list."
    }

def match_item(
    conn: sqlite3.Connection,
    item_name: str,
    quantity: Any = 1.0,
    unit: Optional[str] = None,
    english_guess: Optional[str] = None,
    original_spoken: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes the 6-step deterministic matching pipeline for an item.
    """
    cur = conn.cursor()

    # Load all catalog items
    cur.execute("SELECT sku, display_name, price, unit, is_loose FROM catalog_items WHERE is_active = 1")
    catalog = {row["sku"]: dict(row) for row in cur.fetchall()}

    # Load all aliases
    cur.execute("SELECT alias, sku FROM item_aliases")
    aliases = [(row["alias"], row["sku"]) for row in cur.fetchall()]

    qty_val, parsed_unit = parse_quantity_and_unit(quantity, unit)

    # Helper: resolve candidate options into display names
    def get_options_info(skus: List[str]) -> List[str]:
        names = []
        for sku in skus[:3]:
            if sku in catalog:
                names.append(catalog[sku]["display_name"])
        return names

    # Internal pipeline runner
    def run_pipeline_for_term(term: str) -> Optional[Tuple[str, str, Optional[str]]]:
        """
        Returns (sku, match_type, learned_note) if resolved, else None.
        """
        norm_term = normalize_text(term)
        phone_key = make_phonetic_key(term)

        # Check if this term is an unlearned generic word
        # (Generic words MUST trigger clarification unless learned)
        if norm_term in GENERIC_ITEM_MAP:
            # Check if learned first
            cur.execute("""
                SELECT sku, confirmations_count FROM learned_aliases
                WHERE spoken_word = ? ORDER BY confirmations_count DESC
            """, (norm_term,))
            learned_rows = cur.fetchall()
            if learned_rows:
                top_sku = learned_rows[0]["sku"]
                top_count = learned_rows[0]["confirmations_count"]
                runner_count = learned_rows[1]["confirmations_count"] if len(learned_rows) > 1 else 0
                if top_count >= 2 and top_count >= 2 * runner_count:
                    note = f"I understood {term} as {catalog[top_sku]['display_name']}"
                    return (top_sku, "LEARNED", note)
            # Not learned -> do NOT match directly; must clarify
            return None

        # Step 1: Exact alias match
        for alias, sku in aliases:
            if normalize_text(alias) == norm_term:
                return (sku, "EXACT", None)

        # Step 2: Phonetic key match
        for alias, sku in aliases:
            if make_phonetic_key(alias) == phone_key:
                return (sku, "PHONETIC", None)

        # Step 3: Learned aliases
        cur.execute("""
            SELECT sku, confirmations_count FROM learned_aliases
            WHERE spoken_word = ? OR spoken_word = ?
            ORDER BY confirmations_count DESC
        """, (norm_term, phone_key))
        learned_rows = cur.fetchall()
        if learned_rows:
            top_sku = learned_rows[0]["sku"]
            top_count = learned_rows[0]["confirmations_count"]
            runner_count = learned_rows[1]["confirmations_count"] if len(learned_rows) > 1 else 0
            if top_count >= 2 and top_count >= 2 * runner_count:
                note = f"I understood {term} as {catalog[top_sku]['display_name']}"
                return (top_sku, "LEARNED", note)

        # Step 4: Fuzzy match (rapidfuzz WRatio on phonetic keys)
        # Accept only if score >= 90, maps to one SKU, and gap >= 8
        best_sku = None
        best_score = 0.0
        runner_up_score = 0.0
        best_sku_candidates = set()

        for alias, sku in aliases:
            alias_key = make_phonetic_key(alias)
            score = fuzz.WRatio(phone_key, alias_key)
            if score > best_score:
                runner_up_score = best_score
                best_score = score
                best_sku = sku
                best_sku_candidates = {sku}
            elif score == best_score:
                best_sku_candidates.add(sku)
            elif score > runner_up_score:
                runner_up_score = score

        if (
            best_score >= 90.0
            and len(best_sku_candidates) == 1
            and (best_score - runner_up_score >= 8.0)
        ):
            return (best_sku, "FUZZY", None)

        return None

    # Execute on primary item_name
    match_result = run_pipeline_for_term(item_name)

    # Step 5: If spoken word failed, try english_guess
    used_english_guess = False
    if not match_result and english_guess:
        match_result = run_pipeline_for_term(english_guess)
        if match_result:
            used_english_guess = True

    # If resolved, calculate line total and structure response
    if match_result:
        sku, match_type, learned_note = match_result
        item_data = catalog[sku]
        
        # Calculate pricing
        unit_price = item_data["price"]
        if item_data["is_loose"]:
            # Priced per kg
            line_total = round(qty_val * unit_price, 2)
            display_qty = f"{qty_val} kg"
        else:
            line_total = round(qty_val * unit_price, 2)
            display_qty = f"{qty_val} {item_data['unit']}"

        return {
            "status": "SUCCESS",
            "sku": sku,
            "display_name": item_data["display_name"],
            "quantity": qty_val,
            "unit": item_data["unit"],
            "unit_price": unit_price,
            "line_total": line_total,
            "display_qty": display_qty,
            "match_type": match_type,
            "learned_note": learned_note,
            "used_english_guess": used_english_guess,
        }

    # Step 6: Clarification or Not Recognized
    norm_term = normalize_text(item_name)
    if norm_term in GENERIC_ITEM_MAP:
        options = get_options_info(GENERIC_ITEM_MAP[norm_term])
        return {
            "status": "NEEDS_CLARIFICATION",
            "message": f"Which {item_name} did you mean: {', '.join(options)}?",
            "options": options,
            "unresolved_item": item_name,
        }

    # Check if fuzzy gave ambiguous close candidates
    phone_key = make_phonetic_key(item_name)
    close_skus = set()
    for alias, sku in aliases:
        if fuzz.WRatio(phone_key, make_phonetic_key(alias)) >= 75.0:
            close_skus.add(sku)

    if close_skus:
        options = get_options_info(list(close_skus))
        return {
            "status": "NEEDS_CLARIFICATION",
            "message": f"Did you mean: {', '.join(options)}?",
            "options": options,
            "unresolved_item": item_name,
        }

    return {
        "status": "ITEM_NOT_RECOGNIZED",
        "message": f"Item '{item_name}' was not recognized in your shop catalog.",
        "unresolved_item": item_name,
    }

def record_learned_confirmation(conn: sqlite3.Connection, spoken_word: str, sku: str) -> None:
    """
    Records a confirmation when a shopkeeper clarifies an ambiguous or unlisted word.
    Once confirmations >= 2 (and >= 2x runner up), it auto-resolves in future.
    """
    norm_word = normalize_text(spoken_word)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO learned_aliases (spoken_word, sku, confirmations_count)
        VALUES (?, ?, 1)
        ON CONFLICT(spoken_word, sku) DO UPDATE SET
            confirmations_count = confirmations_count + 1
    """, (norm_word, sku))
    conn.commit()
