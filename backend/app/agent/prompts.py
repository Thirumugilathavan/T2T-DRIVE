"""
Multilingual Prompt Templates and Natural Language Generators for T2T DRIVE.
Generates localized UI display text and natural speech text (for TTS playback)
in Tanglish (Romanized Tamil), Tamil script, and English.
"""

from typing import Dict, Any, Optional, List
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
            "2. 'சர்வீஸ்க்கு 1200 செலவு ஆச்சு' (பராமரிப்பு செலவு)\n"
            "3. 'என் இன்சூரன்ஸ் எப்போ முடியும்?' (ஆவண காலாவதி)\n"
            "4. 'எனக்கு சலான் இருக்கா?' (அபராத விவரம்)\n"
            "5. 'அடுத்த சர்வீஸ் எப்போது?' (பராமரிப்பு அட்டவணை)\n"
            "6. 'இன்றைய கணக்கு' (தினசரி சுருக்கம்)"
        )
        voice = "நீங்கள் டீசல் மற்றும் சர்வீஸ் செலவு, இன்சூரன்ஸ் காலாவதி தேதி, அல்லது நிலுவை சலான்களைப் பற்றி கேட்கலாம்."
    elif language == "english":
        text = (
            "🤖 T2T DRIVE Voice Co-Pilot - Examples you can say:\n"
            "1. 'Filled diesel 400' (record fuel)\n"
            "2. 'Auto service cost 1200' (record maintenance)\n"
            "3. 'When does my insurance expire?' (document expiry)\n"
            "4. 'Do I have any unpaid challans?' (traffic fines)\n"
            "5. 'When is my next service?' (maintenance schedule)\n"
            "6. 'Show today's summary' (daily report)"
        )
        voice = "You can record expenses, check when your insurance expires, check unpaid challans, or ask for your daily summary."
    else:  # tanglish
        text = (
            "🤖 T2T DRIVE Voice Co-Pilot - Neenga ippadi solla mudiyum:\n"
            "1. 'Diesel 400 potten' (fuel selavu)\n"
            "2. 'Auto service ku 1200 selavu aachu' (maintenance)\n"
            "3. 'En insurance eppo expire aagum?' (document expiry)\n"
            "4. 'Enakku unpaid challan irukka?' (traffic fine)\n"
            "5. 'En auto ku service eppo?' (upcoming service)\n"
            "6. 'Inniku kanaku sollu' (daily summary)"
        )
        voice = "Neenga diesel selavu, auto service selavu, insurance expiry, challan nilavaram, illana inniku kanaku summary kekkalam."

    return {"text": text, "voice": voice}


def prompt_unknown(language: str = "tanglish") -> Dict[str, str]:
    """Handles unrecognized voice or text input."""
    if language == "tamil":
        text = "மன்னிக்கவும், எனக்கு புரியவில்லை. 'டீசல் 400' அல்லது 'இன்சூரன்ஸ் எப்போ முடியும்' என்று கூறவும். மேலும் அறிய 'உதவி' என்று கேட்கவும்."
        voice = "மன்னிக்கவும், எனக்கு புரியவில்லை. உதவி என்று சொன்னால் வழிகாட்டுகிறேன்."
    elif language == "english":
        text = "Sorry, I couldn't understand that. You can say 'Diesel 400', 'When does my insurance expire?', or 'Help' for guidance."
        voice = "Sorry, I didn't get that. Say help for instructions."
    else:  # tanglish
        text = "Puriyala nga. 'Diesel 400' or 'Insurance eppo expire' nu sollunga. Guidance theva pattal 'Help' nu sollunga."
        voice = "Puriyala nga. Help nu sonna guidance tharen."

    return {"text": text, "voice": voice}


# ============================================================================
# PHASE 5 PROMPTS (DOCUMENTS, CHALLANS, MAINTENANCE)
# ============================================================================

def prompt_document_expiry(
    doc_type: str,
    expiry_date: Optional[str],
    days_left: Optional[int],
    language: str = "tanglish"
) -> Dict[str, str]:
    """Generates localized response for document expiry queries."""
    if not expiry_date:
        if language == "tamil":
            return {
                "text": f"{doc_type} ஆவணத்தின் காலாவதி தேதி எதுவும் பதிவு செய்யப்படவில்லை.",
                "voice": f"{doc_type} காலாவதி தேதி பதிவு செய்யப்படவில்லை."
            }
        elif language == "english":
            return {
                "text": f"No expiry date recorded for your {doc_type}.",
                "voice": f"No expiry date recorded for your {doc_type}."
            }
        else:
            return {
                "text": f"Ungal {doc_type}-kku expiry date ethuvum pathivu seiyala.",
                "voice": f"Ungal {doc_type}-kku expiry date pathivu seiyala."
            }

    if days_left is not None and days_left < 0:
        abs_days = abs(days_left)
        if language == "tamil":
            return {
                "text": f"எச்சரிக்கை: உங்கள் {doc_type} {abs_days} நாட்களுக்கு முன் ({expiry_date}) காலாவதியானது. உடனடியாக புதுப்பிக்கவும்!",
                "voice": f"எச்சரிக்கை: உங்கள் {doc_type} {abs_days} நாட்களுக்கு முன்பே காலாவதியாகிவிட்டது."
            }
        elif language == "english":
            return {
                "text": f"Alert: Your {doc_type} expired {abs_days} days ago on {expiry_date}. Please renew immediately!",
                "voice": f"Alert: Your {doc_type} expired {abs_days} days ago on {expiry_date}."
            }
        else:
            return {
                "text": f"Alert: Ungal {doc_type} {abs_days} naalaiki munnadiye ({expiry_date}) expire aayiduchu. Udane renew pannunga!",
                "voice": f"Alert: Ungal {doc_type} {abs_days} naalaiki munnadiye expire aayiduchu."
            }
    elif days_left is not None and days_left == 0:
        if language == "tamil":
            return {
                "text": f"உங்கள் {doc_type} இன்றே ({expiry_date}) காலாவதியாகிறது!",
                "voice": f"உங்கள் {doc_type} இன்றே காலாவதியாகிறது."
            }
        elif language == "english":
            return {
                "text": f"Your {doc_type} expires today ({expiry_date})!",
                "voice": f"Your {doc_type} expires today."
            }
        else:
            return {
                "text": f"Ungal {doc_type} innike ({expiry_date}) expire aagudhu!",
                "voice": f"Ungal {doc_type} innike expire aagudhu."
            }
    else:
        days_str = f"({days_left} நாட்கள் உள்ளன)" if days_left is not None else ""
        if language == "tamil":
            return {
                "text": f"உங்கள் {doc_type} {expiry_date} அன்று காலாவதியாகும். {days_str}",
                "voice": f"உங்கள் {doc_type} {expiry_date} அன்று முடிவடையும்."
            }
        elif language == "english":
            return {
                "text": f"Your {doc_type} expires on {expiry_date} ({days_left} days remaining).",
                "voice": f"Your {doc_type} expires on {expiry_date}."
            }
        else:
            return {
                "text": f"Ungal {doc_type} {expiry_date} anru expire aagum. ({days_left} days balance irukku)",
                "voice": f"Ungal {doc_type} {expiry_date} anru expire aagum."
            }


def prompt_unpaid_challans(
    count: int,
    total_fine: Any,
    language: str = "tanglish"
) -> Dict[str, str]:
    """Generates localized response for unpaid challan queries."""
    tot_str = format_inr(total_fine)
    if count == 0:
        if language == "tamil":
            return {
                "text": "உங்களுக்கு எந்தவித நிலுவை சலான்களும் இல்லை. உங்கள் வாகனம் அனைத்தும் சரியாக உள்ளது!",
                "voice": "உங்களுக்கு எந்த நிலுவை சலான்களும் இல்லை. அனைத்தும் சரியாக உள்ளது."
            }
        elif language == "english":
            return {
                "text": "You have no unpaid challans. All clear!",
                "voice": "You have no unpaid challans. All clear!"
            }
        else:
            return {
                "text": "Ungalukku endha unpaid challan-um illa. All clear!",
                "voice": "Ungalukku endha unpaid challan-um illa. All clear!"
            }
    else:
        if language == "tamil":
            return {
                "text": f"உங்களுக்கு {count} நிலுவை சலான்(கள்) உள்ளன. மொத்த அபராதம்: ₹{tot_str}.",
                "voice": f"உங்களுக்கு {count} நிலுவை சலான்கள் உள்ளன. மொத்த அபராதம் ரூபாய் {tot_str}."
            }
        elif language == "english":
            return {
                "text": f"You have {count} unpaid challan(s) totaling ₹{tot_str}.",
                "voice": f"You have {count} unpaid challans totaling {tot_str} rupees."
            }
        else:
            return {
                "text": f"Ungalukku {count} unpaid challan(s) irukku. Total fine amount: ₹{tot_str}.",
                "voice": f"Ungalukku {count} unpaid challan irukku. Total fine roobai {tot_str}."
            }


def prompt_upcoming_service(
    service_type: Optional[str],
    next_date: Optional[str],
    next_km: Optional[int],
    language: str = "tanglish"
) -> Dict[str, str]:
    """Generates localized response for vehicle maintenance queries."""
    if not next_date and not next_km:
        if language == "tamil":
            return {
                "text": "உங்கள் வண்டிக்கு அடுத்த சர்வீஸ் தேதி எதுவும் திட்டமிடப்படவில்லை.",
                "voice": "உங்கள் வண்டிக்கு அடுத்த சர்வீஸ் தேதி எதுவும் திட்டமிடப்படவில்லை."
            }
        elif language == "english":
            return {
                "text": "No upcoming service scheduled for your vehicle.",
                "voice": "No upcoming service scheduled for your vehicle."
            }
        else:
            return {
                "text": "Ungal vandikku adutha service thethi schedule pannala.",
                "voice": "Ungal vandikku adutha service schedule pannala."
            }

    srv_desc = service_type or "General Service"
    date_part = f"on {next_date}" if next_date else ""
    km_part = f"at {next_km} km" if next_km else ""

    if language == "tamil":
        return {
            "text": f"உங்கள் வண்டிக்கான அடுத்த {srv_desc} சர்வீஸ்: {next_date or ''} {km_part}.",
            "voice": f"உங்கள் அடுத்த சர்வீஸ் {next_date or ''} திட்டமிடப்பட்டுள்ளது."
        }
    elif language == "english":
        return {
            "text": f"Your next scheduled {srv_desc} is due {date_part} {km_part}.",
            "voice": f"Your next scheduled {srv_desc} is due {date_part}."
        }
    else:
        return {
            "text": f"Ungal auto adutha {srv_desc} {next_date or ''} schedule pannirukkinga {km_part}.",
            "voice": f"Ungal adutha service {next_date or ''} anru schedule pannirukkinga."
        }


def prompt_documents_list(
    count: int,
    documents: list,
    language: str = "tanglish"
) -> Dict[str, str]:
    """Generates summary list of driver's active documents."""
    if count == 0:
        if language == "tamil":
            return {
                "text": "உங்களிடம் பதிவு செய்யப்பட்ட ஆவணங்கள் எதுவும் இல்லை.",
                "voice": "உங்களிடம் ஆவணங்கள் எதுவும் பதிவு செய்யப்படவில்லை."
            }
        elif language == "english":
            return {
                "text": "You have no documents registered in your vault.",
                "voice": "You have no documents registered in your vault."
            }
        else:
            return {
                "text": "Ungal vault-il documents ethuvum pathivu seiyala.",
                "voice": "Ungal vault-il documents ethuvum pathivu seiyala."
            }

    doc_names = [d.get("document_type", "Document") for d in documents[:4]]
    names_str = ", ".join(doc_names)

    if language == "tamil":
        return {
            "text": f"உங்களிடம் {count} ஆவணங்கள் பதிவு செய்யப்பட்டுள்ளன: {names_str}.",
            "voice": f"உங்களிடம் {count} ஆவணங்கள் உள்ளன."
        }
    elif language == "english":
        return {
            "text": f"You have {count} registered documents: {names_str}.",
            "voice": f"You have {count} registered documents."
        }
    else:
        return {
            "text": f"Ungalukku {count} documents pathivu seiyappattulladhu: {names_str}.",
            "voice": f"Ungalukku {count} documents pathivu seiyappattulladhu."
        }
