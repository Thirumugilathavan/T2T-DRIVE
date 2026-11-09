"""
Contextual Trip Natural Language Understanding (NLU) Module for T2T DRIVE.
Distinguishes casual in-cabin conversation, hypothetical remarks, and general questions
from actionable trip events (Destination Change, Additional Stop, Fare Change, Payment).
Supports Tamil, Tanglish, and English.
"""

import re
from decimal import Decimal
from typing import Dict, Any, Optional, Tuple, List
from app.models.financial import quantize_money
from app.agent.nlu import parse_numeric_amount as extract_amount_multilingual


class TripUtteranceType:
    GENERAL_CONVERSATION = "GENERAL_CONVERSATION"
    GENERAL_QUESTION = "GENERAL_QUESTION"
    HYPOTHETICAL = "HYPOTHETICAL"
    POSSIBLE_ADD_STOP = "POSSIBLE_ADD_STOP"
    POSSIBLE_DESTINATION_CHANGE = "POSSIBLE_DESTINATION_CHANGE"
    POSSIBLE_FARE_CHANGE = "POSSIBLE_FARE_CHANGE"
    POSSIBLE_PAYMENT_STATEMENT = "POSSIBLE_PAYMENT_STATEMENT"
    ACTIONABLE_DESTINATION_CHANGE = "ACTIONABLE_DESTINATION_CHANGE"
    ACTIONABLE_ADD_STOP = "ACTIONABLE_ADD_STOP"
    ACTIONABLE_FARE_CHANGE = "ACTIONABLE_FARE_CHANGE"


class TripEventClassifier:
    """
    Context-aware classifier preventing casual passenger conversations from
    inadvertently altering trip destinations, stops, or fares.
    """

    def __init__(self):
        # Known transit locations in Tamil Nadu (Salem, Chennai, Coimbatore, etc.)
        self.known_locations = [
            "new bus stand", "old bus stand", "bus stand", "railway station", "central station",
            "junction", "airport", "hospital", "petrol bunk", "bunk", "temple", "market", "bazaar",
            "periyar statue", "central", "egmore", "tambaram", "guindy", "koyambedu",
            "apollo pharmacy", "pharmacy", "atm", "lighthouse"
        ]

    def classify(self, text: str, current_destination: Optional[str] = None) -> Dict[str, Any]:
        """Classifies text and returns standardized actionability dictionary."""
        u_type, entities, conf = self.classify_utterance(text, current_destination)
        is_actionable = u_type in (
            TripUtteranceType.POSSIBLE_DESTINATION_CHANGE,
            TripUtteranceType.POSSIBLE_ADD_STOP,
            TripUtteranceType.POSSIBLE_FARE_CHANGE,
            TripUtteranceType.POSSIBLE_PAYMENT_STATEMENT,
            TripUtteranceType.ACTIONABLE_DESTINATION_CHANGE,
            TripUtteranceType.ACTIONABLE_ADD_STOP,
            TripUtteranceType.ACTIONABLE_FARE_CHANGE
        )
        return {
            "utterance_type": u_type,
            "entities": entities,
            "confidence": conf,
            "is_actionable": is_actionable
        }

    def classify_utterance(
        self,
        text: str,
        current_destination: Optional[str] = None
    ) -> Tuple[str, Dict[str, Any], float]:
        """
        Classifies an utterance into an utterance type with extracted parameters and confidence.
        Returns (utterance_type, extracted_entities, confidence).
        """
        if not text or not text.strip():
            return TripUtteranceType.GENERAL_CONVERSATION, {}, 0.0

        t = text.strip().lower()

        # 1. Check for Hypothetical / Counterfactual statements
        # "could have gone", "would have been", "irundhurukkalaam", "poyirukkalaam"
        hypothetical_patterns = [
            r"\bcould have\b", r"\bwould have\b", r"\bmight have\b",
            r"\bpoyirukalam\b", r"\bpoyirukkalaam\b", r"\birundhurukalam\b",
            r"\bif only\b", r"\bjust asking\b", r"\bsumma ketten\b"
        ]
        if any(re.search(pat, t) for pat in hypothetical_patterns):
            return TripUtteranceType.HYPOTHETICAL, {"raw_text": text}, 0.85

        # 2. Check for General Questions / Small Talk
        # "is the bus stand far?", "distance evvalavu?", "mazhai varuma?"
        general_q_patterns = [
            r"\bis it far\b", r"\bhow far\b", r"\bevvuravu neram\b", r"\bevvuravu thooram\b",
            r"\bhot today\b", r"\bcold today\b", r"\btraffic jasthi\b", r"\bmazhai\b",
            r"\btime enna\b", r"\bwhat is the time\b", r"\broad nalla irukka\b",
            r"\btheriyuma\b", r"\bpidikkuma\b", r"\btarutha\b", r"\bdid you\b", r"\bwho won\b",
            r"\?$"
        ]
        if any(re.search(pat, t) for pat in general_q_patterns) and not any(k in t for k in ("let's go", "change destination", "stop at", "niruthunga")):
            return TripUtteranceType.GENERAL_QUESTION, {"raw_text": text}, 0.80

        # 3. Check for Payment Statements
        # "I have already paid 200", "panam kuduthuten", "gpay panniten"
        payment_patterns = [
            r"\balready paid\b", r"\bjust paid\b", r"\bgpay pannit\b", r"\bphonepe pannit\b",
            r"\bupi pannit\b", r"\bpanam kuduthut\b", r"\bkuduthuten\b", r"\bsettle pannit\b"
        ]
        if any(re.search(pat, t) for pat in payment_patterns):
            amt = extract_amount_multilingual(text)
            return TripUtteranceType.POSSIBLE_PAYMENT_STATEMENT, {"amount": str(amt) if amt else None}, 0.82

        # 4. Check for Additional Stop Requests
        # "Can we stop at the petrol bunk?", "petrol bunk-la nirutha mudiyuma?", "oru nimisham niruthunga"
        stop_patterns = [
            r"\bcan we stop\b", r"\bplease stop at\b", r"\blet's stop at\b",
            r"\bnirutha mudiyuma\b", r"\bniruthunga\b", r"\bkonjam niruthunga\b",
            r"\bstop at\b", r"\bora nimisham stop\b", r"\bvazhila\b.*niruth"
        ]
        if any(re.search(pat, t) for pat in stop_patterns):
            stop_loc = self._extract_location(t)
            res_stop = stop_loc or "Requested Stop"
            return TripUtteranceType.POSSIBLE_ADD_STOP, {"stop": res_stop, "stop_name": res_stop}, 0.84

        # 5. Check for Destination Change Requests
        # "Actually let's go to the new bus stand instead", "railway station-ku polam", "destination mathunga"
        dest_patterns = [
            r"\blet'?s go to\b", r"\bgo to .* instead\b", r"\bchange destination to\b",
            r"\binstead of\b", r"\bmathitu .* polam\b", r"\bangaye polam\b",
            r"\bactually let'?s go\b", r"\bpolam\b", r"\bdestination maathunga\b",
            r"\bdestination mathunga\b", r"\bpoi drop pannunga\b", r"\bchange destination\b"
        ]
        if any(re.search(pat, t) for pat in dest_patterns) or ("instead" in t and any(loc in t for loc in self.known_locations)):
            new_dest = self._extract_location(t)
            if new_dest:
                conf = 0.88 if ("instead" in t or "change" in t or "destination" in t) else 0.72
                return TripUtteranceType.POSSIBLE_DESTINATION_CHANGE, {
                    "destination": new_dest,
                    "destination_location": new_dest
                }, conf

        # 6. Check for Fare Change Proposals
        # "The fare should be 250 rupees", "200 roobai tharen", "discount pannunga", "innum 50 roobai"
        fare_patterns = [
            r"\bfare should be\b", r"\bfare is\b", r"\broobai tharen\b", r"\brupees only\b",
            r"\b250 roobai\b", r"\bextra 50\b", r"\bextra 100\b", r"\bdiscount\b", r"\bjathi aachu\b",
            r"\bfare\s+\d+\b", r"\btharean\b", r"\btharen\b"
        ]
        if any(re.search(pat, t) for pat in fare_patterns) or (("fare" in t or "roobai" in t or "rupees" in t) and extract_amount_multilingual(text)):
            amt = extract_amount_multilingual(text)
            if amt:
                amt_str = f"{Decimal(str(amt)):.2f}"
                return TripUtteranceType.POSSIBLE_FARE_CHANGE, {
                    "agreed_fare": amt_str,
                    "fare": amt_str
                }, 0.85

        # Default: General in-cabin conversation
        return TripUtteranceType.GENERAL_CONVERSATION, {}, 0.90

    def _extract_location(self, text: str) -> Optional[str]:
        """Extracts recognizable transit landmark from text."""
        for loc in self.known_locations:
            if loc in text:
                return loc.title()
        # Fallback regex matching "to <location>"
        m = re.search(r"\bto\s+([a-zA-Z\s]{3,20})(?:\s+instead|\s+please|\s*$)", text)
        if m:
            candidate = m.group(1).strip()
            if candidate not in ("the", "a", "an", "here", "there"):
                return candidate.title()
        return None
