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
    GET_SUMMARY = "GET_SUMMARY"
    CALCULATE_SETTLEMENT = "CALCULATE_SETTLEMENT"
    CONFIRM_ACTION = "CONFIRM_ACTION"
    CANCEL_ACTION = "CANCEL_ACTION"
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
    "summary", "total", "today", "balance", "earnings", "collection",
    "inniku kanaku", "inniku balance", "evvalavu sambadhichen", "kanaku sollu", "collection enna",
    "இன்றைய கணக்கு", "கணக்கு", "இருப்பு", "வருமானம் எவ்வளவு", "இன்றைய நிலை"
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
        
        # 1. Check for Confirmation / Cancellation first if there is a pending action awaiting confirmation
        if has_active_pending_action:
            for term in AFFIRMATIVE_TERMS:
                if term in lower:
                    return {
                        "intent": AgentIntent.CONFIRM_ACTION,
                        "confidence": 0.98,
                        "language": language,
                        "slots": {},
                        "missing_slots": []
                    }
            for term in NEGATIVE_TERMS:
                if term in lower:
                    return {
                        "intent": AgentIntent.CANCEL_ACTION,
                        "confidence": 0.98,
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
            "sambathithen", "sambathichen", "kedaichathu", "kidaithathu", "சம்பாதித்தேன்", "வந்தது"
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
