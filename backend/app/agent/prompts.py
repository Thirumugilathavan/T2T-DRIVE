"""
Multilingual Prompt Templates and Natural Language Generators for T2T DRIVE.
Generates localized UI display text and natural speech text (for TTS playback)
in Tanglish (Romanized Tamil), Tamil script, and English.
"""

from typing import Dict, Any, Optional
from decimal import Decimal


def format_inr(val: Any) -> str:
    """Formats number with 2 decimals."""
    try:
        return f"{Decimal(str(val)):.2f}"
    except Exception:
        return str(val)


def prompt_proposal_confirmation(
    action_type: str,
    amount: Any,
    category: str,
    vehicle_id: str,
    language: str = "tanglish"
) -> Dict[str, str]:
    """Generates confirmation prompt asking the driver to confirm before executing financial write."""
    amt_str = format_inr(amount)
    cat_label = category.replace("_", " ").title()

    if language == "tamil":
        text = f"வாகனம் {vehicle_id}-க்கு ₹{amt_str} ({cat_label}) பதிவு செய்யவா? உறுதிப்படுத்த 'ஆம்' அல்லது 'வேண்டாம்' என்று கூறவும்."
        voice = f"வாகனம் {vehicle_id}-க்கு ரூபாய் {amt_str} {cat_label} பதிவு செய்யவா? ஆம் அல்லது வேண்டாம் என்று சொல்லுங்கள்."
    elif language == "english":
        text = f"Confirm recording ₹{amt_str} for {cat_label} on vehicle {vehicle_id}? Reply 'Confirm' or 'Cancel'."
        voice = f"Confirm recording {amt_str} rupees for {cat_label} on vehicle {vehicle_id}? Reply confirm or cancel."
    else:  # tanglish
        text = f"Vandi {vehicle_id}-kku ₹{amt_str} ({cat_label}) pathivu seiyava? 'Confirm' or 'Cancel' nu sollunga."
        voice = f"Vandi {vehicle_id}-kku roobai {amt_str} {cat_label} pathivu seiyava? Confirm or cancel nu sollunga."

    return {"text": text, "voice": voice}


def prompt_execution_success(
    action_type: str,
    amount: Any,
    category: str,
    vehicle_id: str,
    language: str = "tanglish"
) -> Dict[str, str]:
    """Generates confirmation success message after write is committed to the immutable ledger."""
    amt_str = format_inr(amount)
    cat_label = category.replace("_", " ").title()

    if language == "tamil":
        text = f"சரி! ₹{amt_str} ({cat_label}) வெற்றிகரமாக லெட்ஜரில் பதிவு செய்யப்பட்டது."
        voice = f"சரி! ரூபாய் {amt_str} {cat_label} வெற்றிகரமாக பதிவு செய்யப்பட்டது."
    elif language == "english":
        text = f"Done! Successfully recorded ₹{amt_str} for {cat_label} into the ledger."
        voice = f"Done! Successfully recorded {amt_str} rupees for {cat_label}."
    else:  # tanglish
        text = f"Sari! ₹{amt_str} ({cat_label}) ledger-il vetrikaramaga pathivu seiyappattadhu."
        voice = f"Sari! Roobai {amt_str} {cat_label} vetrikaramaga pathivu seiyappattadhu."

    return {"text": text, "voice": voice}


def prompt_cancellation_success(language: str = "tanglish") -> Dict[str, str]:
    """Generates response when user cancels a pending action."""
    if language == "tamil":
        text = "சரி, இந்த பதிவு ரத்து செய்யப்பட்டது. கணக்கில் எதுவும் மாறவில்லை."
        voice = "சரி, இந்த பதிவு ரத்து செய்யப்பட்டது."
    elif language == "english":
        text = "Action cancelled. No changes were made to your account."
        voice = "Action cancelled. No changes were made to your account."
    else:  # tanglish
        text = "Sari, indha action cancel seiyappattadhu. Kanakkil endha maatramum illa."
        voice = "Sari, indha action cancel seiyappattadhu."

    return {"text": text, "voice": voice}


def prompt_missing_slot(slot_name: str, category: str, language: str = "tanglish") -> Dict[str, str]:
    """Prompts the driver when a required slot (like amount) is missing."""
    cat_label = category.replace("_", " ").title()
    
    if language == "tamil":
        text = f"{cat_label} தொகை எவ்வளவு என்று கூறவும். (உதாரணம்: 400 அல்லது 'நானூறு')"
        voice = f"{cat_label} தொகை எவ்வளவு என்று சொல்லுங்கள்."
    elif language == "english":
        text = f"Please specify the amount for {cat_label} (e.g. 400 or ₹400)."
        voice = f"Please specify the amount for {cat_label}."
    else:  # tanglish
        text = f"Evvalavu roobai {cat_label} pottirukeenga? (Eg: 400 or 'naanooru')"
        voice = f"Evvalavu roobai {cat_label} pottirukeenga?"

    return {"text": text, "voice": voice}


def prompt_daily_summary(
    income: Any,
    expense: Any,
    owner_payment: Any,
    net_balance: Any,
    language: str = "tanglish"
) -> Dict[str, str]:
    """Generates daily summary report in driver's language."""
    inc = format_inr(income)
    exp = format_inr(expense)
    own = format_inr(owner_payment)
    net = format_inr(net_balance)

    if language == "tamil":
        text = f"📊 இன்றைய கணக்கு விவரம்:\n• மொத்த வருமானம்: ₹{inc}\n• இயக்கச் செலவுகள்: ₹{exp}\n• ஓனர் கட்டணம்: ₹{own}\n• கையில் நிகர இருப்பு: ₹{net}"
        voice = f"இன்றைய கணக்கு: வருமானம் ரூபாய் {inc}, செலவு ரூபாய் {exp}, ஓனர் கட்டணம் ரூபாய் {own}. கையில் மீதமுள்ள நிகர இருப்பு ரூபாய் {net}."
    elif language == "english":
        text = f"📊 Today's Summary:\n• Gross Income: ₹{inc}\n• Operating Expenses: ₹{exp}\n• Owner Payments: ₹{own}\n• Net Take-Home Balance: ₹{net}"
        voice = f"Today's summary: Income {inc} rupees, expenses {exp} rupees, owner payments {own} rupees. Net balance {net} rupees."
    else:  # tanglish
        text = f"📊 Inniku Kanaku:\n• Varumanam: ₹{inc}\n• Selavu: ₹{exp}\n• Owner Payment: ₹{own}\n• Kaila Meedhi Balance: ₹{net}"
        voice = f"Inniku kanaku: Varumanam roobai {inc}, selavu roobai {exp}, owner payment roobai {own}. Kaila meedhi balance roobai {net}."

    return {"text": text, "voice": voice}


def prompt_settlement_status(
    rent_expected: Any,
    owner_payment: Any,
    expenses_borne: Any,
    balance_due: Any,
    language: str = "tanglish"
) -> Dict[str, str]:
    """Generates settlement calculation status report."""
    rent = format_inr(rent_expected)
    paid = format_inr(owner_payment)
    exp = format_inr(expenses_borne)
    bal = format_inr(balance_due)

    if language == "tamil":
        text = f"📋 வாகன செட்டில்மென்ட் நிலை:\n• எதிர்பார்க்கப்படும் வாடகை: ₹{rent}\n• நீங்கள் செலுத்தியது: ₹{paid}\n• அங்கீகரிக்கப்பட்ட செலவுகள்: ₹{exp}\n• பாக்கி இருப்பு: ₹{bal}"
        voice = f"செட்டில்மென்ட் நிலை: வாடகை ரூபாய் {rent}, நீங்கள் செலுத்தியது ரூபாய் {paid}, அங்கீகரிக்கப்பட்ட செலவுகள் ரூபாய் {exp}. மீதமுள்ள பாக்கி ரூபாய் {bal}."
    elif language == "english":
        text = f"📋 Vehicle Settlement Status:\n• Expected Rent: ₹{rent}\n• Paid to Owner: ₹{paid}\n• Approved Expenses: ₹{exp}\n• Remaining Balance Due: ₹{bal}"
        voice = f"Settlement status: Expected rent {rent} rupees, paid to owner {paid} rupees. Remaining balance {bal} rupees."
    else:  # tanglish
        text = f"📋 Settlement Nilavaram:\n• Expected Rent: ₹{rent}\n• Neenga Kuduthathu: ₹{paid}\n• Anumathikkappatta Selavu: ₹{exp}\n• Meedhi Thara Vendiyadhu: ₹{bal}"
        voice = f"Settlement nilavaram: Rent roobai {rent}, neenga kuduthathu roobai {paid}. Meedhi thara vendiyathu roobai {bal}."

    return {"text": text, "voice": voice}


def prompt_help(language: str = "tanglish") -> Dict[str, str]:
    """Generates helpful instructions."""
    if language == "tamil":
        text = (
            "🤖 T2T DRIVE குரல் உதவியாளர் - நீங்கள் இவ்வாறு கூறலாம்:\n"
            "1. 'டீசல் 400 போட்டேன்' (செலவு பதிவு செய்ய)\n"
            "2. 'சவாரி 1200 வந்தது' (வருமானம் பதிவு செய்ய)\n"
            "3. 'ஓனருக்கு 350 கொடுத்தேன்' (வாடகை பதிவு செய்ய)\n"
            "4. 'இன்றைய கணக்கு' (தினசரி சுருக்கம் பார்க்க)\n"
            "5. 'செட்டில்மென்ட் செய்' (வாடகை கணக்கு பார்க்க)"
        )
        voice = "நீங்கள் டீசல் செலவு, சவாரி வருமானம், ஓனர் வாடகை பதிவு செய்யலாம். அல்லது இன்றைய கணக்கு விவரங்களை கேட்கலாம்."
    elif language == "english":
        text = (
            "🤖 T2T DRIVE Voice Co-Pilot - Examples you can say:\n"
            "1. 'Filled diesel 400' (record expense)\n"
            "2. 'Trip fare 1200' (record income)\n"
            "3. 'Paid 350 to owner' (record owner rent)\n"
            "4. 'Show today's summary' (check daily earnings)\n"
            "5. 'Calculate settlement' (check vehicle settlement)"
        )
        voice = "You can record expenses, trip fares, owner rent, or ask for your daily summary and settlement status."
    else:  # tanglish
        text = (
            "🤖 T2T DRIVE Voice Co-Pilot - Neenga ippadi solla mudiyum:\n"
            "1. 'Diesel 400 potten' (selavu pathivu seiya)\n"
            "2. 'Savari 1200 aachu' (varumanam pathivu seiya)\n"
            "3. 'Ownerukku 350 kuduthen' (rent payment)\n"
            "4. 'Inniku kanaku sollu' (daily summary)\n"
            "5. 'Settlement panni kudu' (settlement status)"
        )
        voice = "Neenga diesel selavu, savari varumanam, owner rent pathivu seiyalaam. Illana inniku kanaku summary kekkalam."

    return {"text": text, "voice": voice}


def prompt_unknown(language: str = "tanglish") -> Dict[str, str]:
    """Handles unrecognized voice or text input."""
    if language == "tamil":
        text = "மன்னிக்கவும், எனக்கு புரியவில்லை. 'டீசல் 400' அல்லது 'இன்றைய கணக்கு' என்று கூறவும். மேலும் அறிய 'உதவி' என்று கேட்கவும்."
        voice = "மன்னிக்கவும், எனக்கு புரியவில்லை. உதவி என்று சொன்னால் வழிகாட்டுகிறேன்."
    elif language == "english":
        text = "Sorry, I couldn't understand that. You can say 'Diesel 400' or 'Show summary'. Say 'Help' for guidance."
        voice = "Sorry, I didn't get that. Say help for instructions."
    else:  # tanglish
        text = "Puriyala nga. 'Diesel 400' or 'Inniku kanaku' nu sollunga. Guidance theva pattal 'Help' nu sollunga."
        voice = "Puriyala nga. Help nu sonna guidance tharen."

    return {"text": text, "voice": voice}
