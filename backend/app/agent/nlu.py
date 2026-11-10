"""
Multilingual Natural Language Understanding (NLU) Module for T2T DRIVE.
Supports Tamil, Tanglish (Romanized Tamil), and English for auto-rickshaw and cab drivers.
Extracts intents, entities (amounts, categories, vehicles, dates, doc types), and identifies missing slots.
Includes Phase 5 support for Document Management, Challan Assistance, and Vehicle Maintenance.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, List, Optional, Tuple


# ============================================================================
# INTENT DEFINITIONS
# ============================================================================

class AgentIntent:
    # Core Financial Intents
    RECORD_EXPENSE = "RECORD_EXPENSE"
    RECORD_INCOME = "RECORD_INCOME"
    RECORD_OWNER_PAYMENT = "RECORD_OWNER_PAYMENT"
    RECORD_BATCH_TRANSACTIONS = "RECORD_BATCH_TRANSACTIONS"
    GET_SUMMARY = "GET_SUMMARY"
    CALCULATE_SETTLEMENT = "CALCULATE_SETTLEMENT"
    CONFIRM_ACTION = "CONFIRM_ACTION"
    CANCEL_ACTION = "CANCEL_ACTION"
    CLARIFY_CONFIRMATION = "CLARIFY_CONFIRMATION"
    HELP = "HELP"
    UNKNOWN = "UNKNOWN"

    # Phase 5 Document Intents
    ADD_DOCUMENT = "ADD_DOCUMENT"
    LIST_DOCUMENTS = "LIST_DOCUMENTS"
    CHECK_DOCUMENT_EXPIRY = "CHECK_DOCUMENT_EXPIRY"
    DOCUMENT_DETAILS = "DOCUMENT_DETAILS"

    # Phase 5 Challan Intents
    ADD_CHALLAN = "ADD_CHALLAN"
    LIST_CHALLANS = "LIST_CHALLANS"
    CHECK_UNPAID_CHALLANS = "CHECK_UNPAID_CHALLANS"
    UPDATE_CHALLAN_STATUS = "UPDATE_CHALLAN_STATUS"

    # Phase 5 Maintenance Intents
    ADD_MAINTENANCE = "ADD_MAINTENANCE"
    LIST_MAINTENANCE = "LIST_MAINTENANCE"
    CHECK_UPCOMING_SERVICE = "CHECK_UPCOMING_SERVICE"
    CHECK_OVERDUE_SERVICE = "CHECK_OVERDUE_SERVICE"
    MAINTENANCE_SUMMARY = "MAINTENANCE_SUMMARY"

    # Passenger Extension Trip Intents
    START_TRIP = "START_TRIP"
    CHANGE_DESTINATION = "CHANGE_DESTINATION"
    ADD_STOP = "ADD_STOP"
    CHANGE_FARE = "CHANGE_FARE"
    RECORD_TRIP_PAYMENT = "RECORD_TRIP_PAYMENT"


# ============================================================================
# NUMBER PARSING (TAMIL WORDS, TANGLISH, & DIGITS)
# ============================================================================

TAMIL_NUMBER_WORDS = {
    # Single digits / tens
    "patthu": 10, "pathu": 10, "பத்து": 10,
    "iruvadhu": 20, "irubathu": 20, "இருபது": 20,
    "muppadhu": 30, "muppathu": 30, "முப்பது": 30,
    "naarppadhu": 40, "naarpathu": 40, "நாற்பது": 40,
    "ambadhu": 50, "ambathu": 50, "aimbadhu": 50, "ஐம்பது": 50,
    "aruvadhu": 60, "arubathu": 60, "அறுபது": 60,
    "ezhuvadhu": 70, "ezhubathu": 70, "எழுபது": 70,
    "enbhadhu": 80, "enbadhu": 80, "எண்பது": 80,
    "thonnooru": 90, "thollayiram": 900, "தொண்ணூறு": 90, "தொள்ளாயிரம்": 900,
    # Hundreds
    "nooru": 100, "nuru": 100, "oru nooru": 100, "நூறு": 100,
    "irunooru": 200, "irunuru": 200, "இருநூறு": 200,
    "munnooru": 300, "munnuru": 300, "முந்நூறு": 300,
    "naanooru": 400, "naanuru": 400, "நாநூறு": 400, "நானூறு": 400,
    "ainooru": 500, "ainuru": 500, "ஐந்நூறு": 500,
    "aaranuru": 600, "aaranooru": 600, "அறுநூறு": 600,
    "ezhunuru": 700, "ezhunooru": 700, "எழுநூறு": 700,
    "ennooru": 800, "ennuru": 800, "எண்ணூறு": 800,
    # Thousands
    "aayiram": 1000, "ayiram": 1000, "oru aayiram": 1000, "ஆயிரம்": 1000,
    "rendaayiram": 2000, "irendaayiram": 2000, "இரண்டாயிரம்": 2000,
    "moonaayiram": 3000, "மூன்றாயிரம்": 3000,
    "naalaayiram": 4000, "நான்காயிரம்": 4000,
    "aindhaayiram": 5000, "ஐந்தாயிரம்": 5000,
}


def parse_numeric_amount(text: str) -> Optional[Decimal]:
    """
    Extracts monetary amount from text supporting digits (₹450, 450.00, 450rs, 450 roobai)
    or Tamil/Tanglish number words.
    """
    digit_patterns = [
        r'(?:(?:rs|inr|₹|ரூ)\.?\s*)(\d+(?:\.\d{1,2})?)',  # ₹500, rs 500
        r'(\d+(?:\.\d{1,2})?)\s*(?:rs|inr|ruba|rubai|rooba|roobai|rupees|ரூபாய்|ரூ)',  # 500 rs, 500 ruba
        r'\b(\d+(?:\.\d{1,2})?)\b'  # standalone number
    ]
    
    clean_text = text.lower()
    for pat in digit_patterns:
        match = re.search(pat, clean_text)
        if match:
            val_str = match.group(1)
            try:
                val = Decimal(val_str)
                if val > 0:
                    return val
            except (InvalidOperation, ValueError):
                continue
                
    sorted_words = sorted(TAMIL_NUMBER_WORDS.items(), key=lambda x: len(x[0]), reverse=True)
    for word, amount in sorted_words:
        pattern = r'(?:^|\b|\s)' + re.escape(word) + r'(?:$|\b|\s|aachu|potten|kuduthen|rubai|ruba|rs)'
        if re.search(pattern, clean_text) or word == clean_text:
            return Decimal(str(amount))
            
    return None


# ============================================================================
# CATEGORY EXTRACTION
# ============================================================================

EXPENSE_CATEGORY_KEYWORDS = {
    "FUEL": [
        "diesel", "petrol", "cng", "gas", "fuel", "டீசல்", "பெட்ரோல்", "எரிபொருள்", "காஸ்"
    ],
    "FOOD": [
        "tea", "coffee", "tiffin", "sappadu", "lunch", "dinner", "breakfast", "snack",
        "சாப்பாடு", "டீ", "காபி", "டிபன்", "உணவு"
    ],
    "MAINTENANCE": [
        "puncture", "puncher", "repair", "service", "air", "tyre", "tire", "oil",
        "brake", "clutch", "grease", "maintenance", "servicing", "பழுது", "பஞ்சர்",
        "சர்வீஸ்", "டயர்", "ஆயில்", "பராமரிப்பு"
    ],
    "TOLL": [
        "toll", "fastag", "tollgate", "டோல்", "டோல்கேட்"
    ],
    "PARKING": [
        "parking", "park", "பார்க்கிங்"
    ],
    "VEHICLE_CLEANING": [
        "wash", "cleaning", "water wash", "வாஷ்", "கழுவுதல்"
    ],
    "MOBILE_RECHARGE": [
        "recharge", "mobile recharge", "ரீசார்ஜ்"
    ],
}

INCOME_CATEGORY_KEYWORDS = {
    "FARE": [
        "savari", "trip", "ride", "hire", "passenger", "collection", "cash", "ota",
        "சவாரி", "பயணம்", "வாடகை சவாரி", "கலெக்ஷன்"
    ],
    "TIP": [
        "tip", "tips", "இனாம்"
    ]
}

OWNER_PAYMENT_KEYWORDS = [
    "owner", "vaadagai", "owner rent", "owner payment", "settlement payment",
    "ஓனர்", "வாடகை", "ஓனர் வாடகை", "முதலாளி"
]


def detect_language(text: str) -> str:
    """Detects whether text is Tamil (Tamil script), Tanglish (Tamil in Latin script), or English."""
    if any('\u0B80' <= char <= '\u0BFF' for char in text):
        return "tamil"
        
    lower = text.lower()
    tanglish_markers = [
        "potten", "aachu", "vandhuchu", "kuduthen", "anna", "thambi", "inniku",
        "nethu", "naalaiki", "evvalavu", "sollu", "solra", "aama", "sari", "vendaam",
        "illa", "savari", "rubai", "ruba", "vaadagai", "pannu", "sey", "kanaku", "eppo"
    ]
    if any(marker in lower for marker in tanglish_markers):
        return "tanglish"
        
    return "english"


def extract_vehicle_id(text: str, default_vehicle: Optional[str] = None) -> Optional[str]:
    """Extracts vehicle registration number (e.g., TN-01-AB-1234 or TN 01 AB 1234) or returns default."""
    pattern = r'\b([A-Z]{2}[ -]?[0-9]{1,2}[ -]?[A-Z]{1,3}[ -]?[0-9]{1,4})\b'
    match = re.search(pattern, text.upper())
    if match:
        raw = match.group(1).replace(" ", "-")
        return raw
    return default_vehicle


def extract_document_type(text: str) -> str:
    """Extracts document type from utterance (e.g. INSURANCE, PUC, RC)."""
    lower = text.lower()
    if "puc" in lower or "pollution" in lower or "புகை" in lower:
        return "PUC"
    if "rc" in lower or "registration" in lower or "பதிவு" in lower:
        return "RC"
    if "fitness" in lower or "fc" in lower or "தகுதி" in lower:
        return "FITNESS"
    if "licence" in lower or "license" in lower or "dl" in lower or "ஓட்டுநர் உரிமம்" in lower:
        return "DRIVING_LICENCE"
    if "permit" in lower or "பர்மிட்" in lower:
        return "PERMIT"
    if "tax" in lower or "வரி" in lower:
        return "TAX_RECEIPT"
    return "INSURANCE"


# ============================================================================
# INTENT CLASSIFICATION
# ============================================================================

AFFIRMATIVE_TERMS = [
    "yes", "confirm", "ok", "okay", "sure", "correct", "proceed",
    "aama", "aamaa", "sari", "pannu", "confirm pannu", "sey",
    "ஆம்", "உறுதி", "உறுதி செய்", "சரி", "சரி செய்", "பண்ணு"
]

NEGATIVE_TERMS = [
    "no", "cancel", "stop", "abort", "reject", "wrong", "dont",
    "vendaam", "vendam", "illa", "thappu", "cancel pannu", "venda",
    "வேண்டாம்", "ரத்து", "ரத்து செய்", "இல்லை", "தவறு"
]

SUMMARY_TERMS = [
    "summary", "total", "today", "balance", "earnings",
    "inniku kanaku", "inniku balance", "evvalavu sambadhichen", "kanaku sollu", "collection enna",
    "collection evvalavu", "today collection", "இன்றைய கணக்கு", "கணக்கு", "இருப்பு", "வருமானம் எவ்வளவு", "இன்றைய நிலை"
]

SETTLEMENT_TERMS = [
    "settlement", "settle", "settlement kanaku", "reconcile", "vaadagai settlement",
    "owner settlement", "calculate settlement", "செட்டில்மென்ட்", "கணக்கு முடித்தல்"
]

HELP_TERMS = [
    "help", "guide", "what can you do", "commands", "options",
    "udhavi", "enna panna mudiyum", "உதவி", "வழிகாட்டல்"
]

# Phase 5 Keyword Sets
DOCUMENT_EXPIRY_TERMS = [
    "expire", "expiry", "eppo expire", "eppo mudiyum", "eppothu expire",
    "எப்போது முடியும்", "எப்போ முடியும்", "காலாவதி", "முடிவடையும்",
    "when does my insurance expire", "when does my puc expire", "when does my rc expire",
    "when does my licence expire", "check document expiry"
]

DOCUMENT_LIST_TERMS = [
    "show my vehicle documents", "show documents", "documents list",
    "enna documents irukku", "document list", "ஆவணங்கள் காட்டு", "டாக்குமெண்ட்ஸ் காட்டு",
    "show my documents", "list documents"
]

CHALLAN_UNPAID_TERMS = [
    "unpaid challan", "unpaid challans", "challan irukka", "fine irukka",
    "traffic fine", "show my unpaid challans", "check unpaid challans",
    "டிராஃபிக் ஃபைன்", "சலான் இருக்கா", "அபராதம் இருக்கா", "unpaid fines", "challan check"
]

CHALLAN_LIST_TERMS = [
    "show challans", "list challans", "show all challans", "challan list", "எல்லா சலான்களும்"
]

MAINTENANCE_SERVICE_TERMS = [
    "service eppo", "adutha service eppo", "service eppothu", "when is my next service",
    "next service due", "when is my service", "என் வண்டிக்கு சர்வீஸ் எப்போது",
    "அடுத்த சர்வீஸ் எப்போது", "service schedule", "next service due date", "vandi service eppo",
    "en auto ku service eppo"
]


class MultilingualNLU:
    """
    Rule-based & Regex NLU Parser with high accuracy for domain-specific driver vocabulary.
    Easily extensible with Evon or LLM embeddings.
    """

    @classmethod
    def extract_multi_transactions(cls, text: str) -> List[Dict[str, Any]]:
        """
        Extracts multiple financial transactions from a single compound utterance.
        e.g. 'இன்னிக்கு collection 1500, petrol 300, owner-க்கு 200 கொடுத்தேன்.'
        """
        all_entry_kws = []
        for c, kws in EXPENSE_CATEGORY_KEYWORDS.items():
            all_entry_kws.extend(kws)
        for c, kws in INCOME_CATEGORY_KEYWORDS.items():
            all_entry_kws.extend(kws)
        all_entry_kws.extend(OWNER_PAYMENT_KEYWORDS)
        all_entry_kws = sorted(set(all_entry_kws), key=lambda x: len(x), reverse=True)

        # 1. Delimiter-based splitting (commas, semicolons, conjunctions)
        delimiters = r"[,;]|\band\b|\bapram\b|\bappuram\b|\bpinbu\b|\bmatrum\b"
        raw_segments = [p.strip() for p in re.split(delimiters, text, flags=re.IGNORECASE) if p.strip()]

        # 2. If single segment but multiple numbers exist, split by keyword boundaries
        amounts_in_text = re.findall(r"\b\d+(?:\.\d{1,2})?\b", text)
        if len(raw_segments) <= 1 and len(amounts_in_text) > 1:
            kw_pattern = r"(\b(?:" + "|".join(re.escape(k) for k in all_entry_kws) + r")\b)"
            tokens = re.split(kw_pattern, text, flags=re.IGNORECASE)
            segments = []
            current = ""
            for tok in tokens:
                if not tok.strip():
                    continue
                lower_tok = tok.strip().lower()
                if any(lower_tok == k for k in all_entry_kws):
                    if current and any(char.isdigit() for char in current):
                        segments.append(current.strip())
                        current = tok
                    else:
                        current += " " + tok
                else:
                    current += " " + tok
            if current.strip():
                segments.append(current.strip())
            raw_segments = segments

        transactions = []
        for s in raw_segments:
            amt = parse_numeric_amount(s)
            if not amt:
                continue
            lower_s = s.lower()

            # 1. Owner payment check
            if any(k in lower_s for k in OWNER_PAYMENT_KEYWORDS):
                transactions.append({
                    "action_type": "ADD_OWNER_PAYMENT",
                    "category": "OWNER_RENT",
                    "amount": float(amt),
                    "description": f"Owner payment ₹{amt}"
                })
                continue

            # 2. Expense check
            exp_cat = None
            for c, kws in EXPENSE_CATEGORY_KEYWORDS.items():
                if any(k in lower_s for k in kws):
                    exp_cat = c
                    break
            if exp_cat or any(v in lower_s for v in ["potten", "spent", "kuduthen", "selavu", "போட்டேன்", "செலவு"]):
                transactions.append({
                    "action_type": "ADD_EXPENSE",
                    "category": exp_cat or "OTHER_EXPENSE",
                    "amount": float(amt),
                    "description": f"{exp_cat or 'Expense'} ₹{amt}"
                })
                continue

            # 3. Income check
            inc_cat = None
            for c, kws in INCOME_CATEGORY_KEYWORDS.items():
                if any(k in lower_s for k in kws):
                    inc_cat = c
                    break
            if inc_cat or any(v in lower_s for v in ["vandhuchu", "varumanam", "earned", "got", "collection", "sambathithen", "sambathichen", "வந்தது"]):
                transactions.append({
                    "action_type": "ADD_INCOME",
                    "category": inc_cat or "FARE",
                    "amount": float(amt),
                    "description": f"Collection ₹{amt}"
                })
                continue

        return transactions

    @classmethod
    def parse(cls, text: str, has_active_pending_action: bool = False, default_vehicle: str = "DEFAULT_VEHICLE") -> Dict[str, Any]:
        """
        Analyzes driver message, extracts intent, slots, and missing slots.
        """
        clean_text = text.strip()
        lower = clean_text.lower()
        language = detect_language(clean_text)
        explicit_vehicle = extract_vehicle_id(clean_text, None)
        effective_write_vehicle = explicit_vehicle or default_vehicle or "DEFAULT_VEHICLE"
        vehicle_id = effective_write_vehicle
        
        # 1. Check for Confirmation / Cancellation / Clarification / Partial confirmation first
        if has_active_pending_action:
            # Check for partial confirmation: "only petrol", "petrol mattum", "only collection", "save only 300", etc.
            is_partial = any(w in lower for w in ["only", "mattum", "மட்டும்", "just"])
            filter_cat = None
            if any(w in lower for w in ["petrol", "diesel", "fuel", "பெட்ரோல்", "டீசல்"]):
                filter_cat = "FUEL"
            elif any(w in lower for w in ["collection", "fare", "savari", "கலெக்ஷன்", "சவாரி"]):
                filter_cat = "FARE"
            elif any(w in lower for w in ["owner", "vaadagai", "ஓனர்", "வாடகை"]):
                filter_cat = "OWNER_RENT"

            if filter_cat and (is_partial or any(w in lower for w in ["confirm", "save", "record", "சரி", "பண்ணு"])):
                return {
                    "intent": AgentIntent.CONFIRM_ACTION,
                    "confidence": 0.98,
                    "language": language,
                    "slots": {"filter_category": filter_cat},
                    "missing_slots": []
                }

            # Check negative terms BEFORE affirmative terms so "cancel pannu" or "vendaam" are not misclassified as "pannu"
            for term in NEGATIVE_TERMS:
                if term in lower:
                    return {
                        "intent": AgentIntent.CANCEL_ACTION,
                        "confidence": 0.98,
                        "language": language,
                        "slots": {},
                        "missing_slots": []
                    }
            for term in AFFIRMATIVE_TERMS:
                if term in lower:
                    return {
                        "intent": AgentIntent.CONFIRM_ACTION,
                        "confidence": 0.98,
                        "language": language,
                        "slots": {},
                        "missing_slots": []
                    }

            # Ambiguous response while awaiting confirmation -> request clarification
            ambiguous_terms = [
                "maybe", "what", "repeat", "purila", "therila", "wait", "huh",
                "can you repeat", "doubt", "dont know", "not sure", "yosikanum"
            ]
            if any(term in lower for term in ambiguous_terms):
                return {
                    "intent": AgentIntent.CLARIFY_CONFIRMATION,
                    "confidence": 0.95,
                    "language": language,
                    "slots": {},
                    "missing_slots": []
                }

        # 2. Help Intent
        if any(term in lower for term in HELP_TERMS):
            return {
                "intent": AgentIntent.HELP,
                "confidence": 0.95,
                "language": language,
                "slots": {},
                "missing_slots": []
            }

        # 3. Check for multi-transaction compound utterances (e.g. collection 1500, petrol 300, owner 200)
        multi_txns = cls.extract_multi_transactions(clean_text)
        if len(multi_txns) >= 2:
            return {
                "intent": AgentIntent.RECORD_BATCH_TRANSACTIONS,
                "confidence": 0.96,
                "language": language,
                "slots": {
                    "transactions": multi_txns,
                    "vehicle_id": vehicle_id,
                    "notes": clean_text
                },
                "missing_slots": []
            }

        # 3. Document Expiry Queries (Phase 5)
        if any(term in lower for term in DOCUMENT_EXPIRY_TERMS):
            doc_type = extract_document_type(clean_text)
            return {
                "intent": AgentIntent.CHECK_DOCUMENT_EXPIRY,
                "confidence": 0.94,
                "language": language,
                "slots": {
                    "document_type": doc_type,
                    "vehicle_id": explicit_vehicle
                },
                "missing_slots": []
            }

        # 4. List Documents (Phase 5)
        if any(term in lower for term in DOCUMENT_LIST_TERMS):
            return {
                "intent": AgentIntent.LIST_DOCUMENTS,
                "confidence": 0.92,
                "language": language,
                "slots": {"vehicle_id": explicit_vehicle},
                "missing_slots": []
            }

        # 5. Check Unpaid Challans (Phase 5)
        if any(term in lower for term in CHALLAN_UNPAID_TERMS):
            return {
                "intent": AgentIntent.CHECK_UNPAID_CHALLANS,
                "confidence": 0.94,
                "language": language,
                "slots": {"vehicle_id": explicit_vehicle},
                "missing_slots": []
            }

        # 6. List Challans (Phase 5)
        if any(term in lower for term in CHALLAN_LIST_TERMS):
            return {
                "intent": AgentIntent.LIST_CHALLANS,
                "confidence": 0.90,
                "language": language,
                "slots": {"vehicle_id": explicit_vehicle},
                "missing_slots": []
            }

        # 7. Check Upcoming Service / Maintenance Schedule (Phase 5)
        if any(term in lower for term in MAINTENANCE_SERVICE_TERMS):
            return {
                "intent": AgentIntent.CHECK_UPCOMING_SERVICE,
                "confidence": 0.94,
                "language": language,
                "slots": {"vehicle_id": explicit_vehicle},
                "missing_slots": []
            }

        # 8. Settlement Intent
        if any(term in lower for term in SETTLEMENT_TERMS):
            return {
                "intent": AgentIntent.CALCULATE_SETTLEMENT,
                "confidence": 0.92,
                "language": language,
                "slots": {"vehicle_id": effective_write_vehicle},
                "missing_slots": []
            }

        # 9. Summary Intent
        if any(term in lower for term in SUMMARY_TERMS):
            return {
                "intent": AgentIntent.GET_SUMMARY,
                "confidence": 0.92,
                "language": language,
                "slots": {"vehicle_id": vehicle_id},
                "missing_slots": []
            }

        # 10. Financial Transaction & Maintenance Expense Intents
        amount = parse_numeric_amount(clean_text)
        
        # Check Owner Payment
        is_owner = any(term in lower for term in OWNER_PAYMENT_KEYWORDS)
        if is_owner:
            slots = {
                "amount": float(amount) if amount else None,
                "category": "OWNER_RENT",
                "vehicle_id": vehicle_id,
                "notes": clean_text
            }
            missing = ["amount"] if amount is None else []
            return {
                "intent": AgentIntent.RECORD_OWNER_PAYMENT,
                "confidence": 0.90 if amount else 0.75,
                "language": language,
                "slots": slots,
                "missing_slots": missing
            }

        # Check Expense vs Income
        matched_expense_cat = None
        for cat, kws in EXPENSE_CATEGORY_KEYWORDS.items():
            if any(kw in lower for kw in kws):
                matched_expense_cat = cat
                break
                
        matched_income_cat = None
        for cat, kws in INCOME_CATEGORY_KEYWORDS.items():
            if any(kw in lower for kw in kws):
                matched_income_cat = cat
                break

        expense_verbs = ["potten", "potan", "selavu", "spent", "kuduthen", "kattinen", "போட்டேன்", "செலவு", "கட்டினேன்"]
        income_verbs = [
            "vandhuchu", "varumanam", "earned", "got", "collection", "sambadhichen",
            "sambathithen", "sambathichen", "kedaichathu", "kidaithathu", "சம்பாதித்தேன்", "சம்பாதிச்சேன்", "வந்தது"
        ]
        
        is_expense_verb = any(v in lower for v in expense_verbs)
        is_income_verb = any(v in lower for v in income_verbs)

        if matched_expense_cat or (is_expense_verb and not matched_income_cat):
            category = matched_expense_cat or "OTHER_EXPENSE"
            slots = {
                "amount": float(amount) if amount else None,
                "category": category,
                "vehicle_id": vehicle_id,
                "notes": clean_text
            }
            missing = ["amount"] if amount is None else []
            
            # If specifically maintenance category, also set maintenance intent alias
            intent = AgentIntent.RECORD_EXPENSE
            return {
                "intent": intent,
                "confidence": 0.92 if amount else 0.75,
                "language": language,
                "slots": slots,
                "missing_slots": missing
            }

        if matched_income_cat or is_income_verb:
            category = matched_income_cat or "FARE"
            slots = {
                "amount": float(amount) if amount else None,
                "category": category,
                "vehicle_id": vehicle_id,
                "notes": clean_text
            }
            missing = ["amount"] if amount is None else []
            return {
                "intent": AgentIntent.RECORD_INCOME,
                "confidence": 0.92 if amount else 0.75,
                "language": language,
                "slots": slots,
                "missing_slots": missing
            }

        # Passenger Extension Trip Actions
        if any(w in lower for w in ["start trip", "trip start", "savari start", "சவாரி தொடங்கு"]):
            return {
                "intent": AgentIntent.START_TRIP,
                "confidence": 0.92,
                "language": language,
                "slots": {"vehicle_id": vehicle_id},
                "missing_slots": []
            }

        if any(w in lower for w in ["change destination", "destination mathu", "destination maathu", "சேருமிடம் மாற்று"]) or ("destination" in lower and "change" in lower):
            # Extract destination
            dest = None
            m = re.search(r"(?:to|mathu|maathu)\s+([a-zA-Z\s]{3,25})$", clean_text, re.IGNORECASE)
            if m:
                dest = m.group(1).strip()
            return {
                "intent": AgentIntent.CHANGE_DESTINATION,
                "confidence": 0.88,
                "language": language,
                "slots": {"destination_location": dest},
                "missing_slots": ["destination_location"] if not dest else []
            }

        if any(w in lower for w in ["add stop", "stop at", "extra stop", "நிறுத்தம்"]):
            stop = None
            m = re.search(r"(?:at|stop)\s+([a-zA-Z\s]{3,25})$", clean_text, re.IGNORECASE)
            if m:
                stop = m.group(1).strip()
            return {
                "intent": AgentIntent.ADD_STOP,
                "confidence": 0.88,
                "language": language,
                "slots": {"stop": stop},
                "missing_slots": ["stop"] if not stop else []
            }

        if any(w in lower for w in ["change fare", "fare change", "kattanam maathu", "கட்டணம் மாற்று"]) or ("fare" in lower and amount is not None and not is_income_verb):
            return {
                "intent": AgentIntent.CHANGE_FARE,
                "confidence": 0.88,
                "language": language,
                "slots": {"agreed_fare": float(amount) if amount else None},
                "missing_slots": ["agreed_fare"] if amount is None else []
            }

        if any(w in lower for w in ["trip payment", "passenger paid", "fare collect", "சவாரி கட்டணம்"]):
            return {
                "intent": AgentIntent.RECORD_TRIP_PAYMENT,
                "confidence": 0.90,
                "language": language,
                "slots": {
                    "amount": float(amount) if amount else None,
                    "payment_method": "CASH" if "cash" in lower else ("UPI" if "upi" in lower or "gpay" in lower else "CASH")
                },
                "missing_slots": ["amount"] if amount is None else []
            }

        # Standalone amount provided during slot-filling or conversation
        if amount is not None:
            return {
                "intent": "PROVIDE_AMOUNT",
                "confidence": 0.85,
                "language": language,
                "slots": {"amount": float(amount)},
                "missing_slots": []
            }

        # Fallback to UNKNOWN
        return {
            "intent": AgentIntent.UNKNOWN,
            "confidence": 0.20,
            "language": language,
            "slots": {},
            "missing_slots": []
        }
