"""
Unit and benchmark tests for T2T DRIVE Continuous Listening & Conversational Privacy Engine.
Evaluates:
1. Intent filtering & non-actionable speech rejection (Tamil, Tanglish, English).
2. Actionable event classification (Destination Change, Additional Stop, Fare Change).
3. False alerts per hour metric (benchmark target: < 1 false alert / hr).
4. Memory-only ephemeral buffering with zero MongoDB persistence for ordinary talk.
5. Dual consent gate and immediate revocation teardown.
"""

import pytest
from decimal import Decimal
from typing import Dict, Any

from app.models.trip import TripState, ProposalType
from app.repositories.trip_repository import TripRepository
from app.services.passenger_access_service import PassengerAccessService
from app.services.trip_service import TripService
from app.services.continuous_listening_service import (
    ContinuousListeningService,
    ConsentRequiredError
)
from app.agent.trip_nlu import (
    TripEventClassifier,
    TripUtteranceType
)
from app.voice.streaming_adapter import MockStreamingSTTAdapter


@pytest.fixture
def listening_fixture(db):
    repo = TripRepository(db=db)
    access_svc = PassengerAccessService(
        repository=repo,
        secret_key="test-secure-secret-key-t2t-drive",
        base_url="http://localhost:5000",
        token_ttl_hours=24
    )
    trip_svc = TripService(repository=repo, passenger_access_service=access_svc)
    classifier = TripEventClassifier()
    adapter = MockStreamingSTTAdapter()
    listening_svc = ContinuousListeningService(
        trip_service=trip_svc,
        streaming_adapter=adapter,
        event_classifier=classifier
    )

    # Create active trip with initial agreement
    trip_dict, token, _, _ = trip_svc.create_trip(
        driver_id="DRV_LISTENING_01",
        vehicle_id="TN-01-AB-1234",
        pickup_location="Saidapet",
        destination_location="Chennai Central",
        proposed_fare=Decimal("250.00")
    )
    trip_svc.respond_to_initial_agreement(trip_dict["trip_id"], token, accepted=True)
    trip_svc.start_trip(trip_dict["trip_id"], "DRV_LISTENING_01")

    return {
        "repo": repo,
        "trip_svc": trip_svc,
        "listening_svc": listening_svc,
        "classifier": classifier,
        "trip_id": trip_dict["trip_id"],
        "token": token
    }


# ============================================================================
# 1. CASUAL CONVERSATION REJECTION TESTS (TAMIL, TANGLISH, ENGLISH)
# ============================================================================

CASUAL_CONVERSATIONS = [
    # Tamil casual sentences
    ("இன்னைக்கு ரொம்ப மழை பெய்யுது", TripUtteranceType.GENERAL_CONVERSATION),
    ("சென்னையில டிராஃபிக் எப்பவும் அதிகம்", TripUtteranceType.GENERAL_CONVERSATION),
    ("நேத்து சினிமா பார்த்தேன் நல்லா இருந்துச்சு", TripUtteranceType.GENERAL_CONVERSATION),
    ("உங்களுக்கு டீ பிடிக்குமா?", TripUtteranceType.GENERAL_QUESTION),
    ("வண்டி நல்ல மைலேஜ் தருதா?", TripUtteranceType.GENERAL_QUESTION),

    # Tanglish casual sentences
    ("Inniku weather romba nalla irukku bro", TripUtteranceType.GENERAL_CONVERSATION),
    ("Traffic romba slow-va irukku pa", TripUtteranceType.GENERAL_CONVERSATION),
    ("Cricket match score enna aachu nu theriyuma?", TripUtteranceType.GENERAL_QUESTION),
    ("Cinema release epdi irukku", TripUtteranceType.GENERAL_CONVERSATION),
    ("Enga oorla ippo thiruvizha nadakkuthu", TripUtteranceType.GENERAL_CONVERSATION),
    ("Appadi pona petrol theerum la?", TripUtteranceType.HYPOTHETICAL),

    # English casual sentences
    ("It looks like it might rain soon", TripUtteranceType.GENERAL_CONVERSATION),
    ("Traffic is always heavy on this bridge", TripUtteranceType.GENERAL_CONVERSATION),
    ("Did you catch the football game yesterday?", TripUtteranceType.GENERAL_QUESTION),
    ("I might buy an electric vehicle next year", TripUtteranceType.HYPOTHETICAL),
    ("The music on the radio is quite relaxing", TripUtteranceType.GENERAL_CONVERSATION),
]


@pytest.mark.parametrize("utterance,expected_type", CASUAL_CONVERSATIONS)
def test_casual_speech_rejection_no_false_alerts(listening_fixture, utterance, expected_type):
    classifier = listening_fixture["classifier"]
    res = classifier.classify(utterance)

    assert res["utterance_type"] in (
        TripUtteranceType.GENERAL_CONVERSATION,
        TripUtteranceType.GENERAL_QUESTION,
        TripUtteranceType.HYPOTHETICAL
    )
    assert res["is_actionable"] is False


# ============================================================================
# 2. ACTIONABLE TRIP EVENT CLASSIFICATION TESTS
# ============================================================================

ACTIONABLE_UTTERANCES = [
    (
        "Bhai, destination maathunga Airport ku poganum",
        TripUtteranceType.POSSIBLE_DESTINATION_CHANGE,
        "destination",
        "Airport"
    ),
    (
        "Vazhila ATM la konjam niruthunga cash edukannum",
        TripUtteranceType.POSSIBLE_ADD_STOP,
        "stop",
        "ATM"
    ),
    (
        "Fare 300 tharean bro pothuma",
        TripUtteranceType.POSSIBLE_FARE_CHANGE,
        "agreed_fare",
        "300.00"
    ),
    (
        "Can we stop at Apollo Pharmacy on the way?",
        TripUtteranceType.POSSIBLE_ADD_STOP,
        "stop",
        "Apollo Pharmacy"
    ),
    (
        "Please change destination to Central Station",
        TripUtteranceType.POSSIBLE_DESTINATION_CHANGE,
        "destination",
        "Central Station"
    )
]


@pytest.mark.parametrize("utterance,expected_type,entity_key,expected_entity", ACTIONABLE_UTTERANCES)
def test_actionable_trip_event_detection(listening_fixture, utterance, expected_type, entity_key, expected_entity):
    classifier = listening_fixture["classifier"]
    res = classifier.classify(utterance)

    assert res["utterance_type"] == expected_type
    assert res["is_actionable"] is True
    assert res["confidence"] >= 0.70
    assert entity_key in res["entities"]


# ============================================================================
# 3. PRIVACY ENFORCEMENT: ZERO MONGO PERSISTENCE FOR CASUAL TALK
# ============================================================================

def test_privacy_enforcement_casual_conversation_never_persisted(listening_fixture):
    trip_id = listening_fixture["trip_id"]
    trip_svc = listening_fixture["trip_svc"]
    listening_svc = listening_fixture["listening_svc"]
    repo = listening_fixture["repo"]

    # Mutual consent
    trip_svc.update_continuous_listening_consent(trip_id, "DRIVER", True)
    trip_svc.update_continuous_listening_consent(trip_id, "PASSENGER", True)

    listening_svc.start_continuous_session(trip_id)

    # Process 10 casual utterances
    for utt, _ in CASUAL_CONVERSATIONS[:10]:
        res = listening_svc.process_in_memory_transcript(
            trip_id=trip_id,
            transcript=utt,
            is_final=True,
            stt_confidence=0.88
        )
        assert res is None  # Immediately discarded from memory!

    # Verify MongoDB: Absolutely 0 casual transcript events must exist in trip_events!
    events = repo.list_events_for_trip(trip_id)
    casual_events = [
        e for e in events
        if any(w in str(e.get("description", "")).lower() for w in ["rain", "mazhai", "weather", "cinema", "traffic"])
    ]
    assert len(casual_events) == 0


# ============================================================================
# 4. BENCHMARK: FALSE ALERTS PER HOUR METRIC
# ============================================================================

def test_benchmark_false_alerts_per_hour(listening_fixture):
    """
    Simulates a 1-hour in-cabin audio stream containing 60 casual background utterances.
    Calculates false alerts per simulated hour.
    Target: 0 false alerts per hour (strictly < 1.0 / hr).
    """
    classifier = listening_fixture["classifier"]
    
    # 60 casual utterances simulating 1 utterance per minute of background chat
    simulated_hour_utterances = (CASUAL_CONVERSATIONS * 4)[:60]
    false_alerts = 0

    for utt, _ in simulated_hour_utterances:
        res = classifier.classify(utt)
        if res["is_actionable"]:
            false_alerts += 1

    false_alerts_per_hour = float(false_alerts)
    assert false_alerts_per_hour == 0.0  # Zero false alerts!


# ============================================================================
# 5. DUAL CONSENT GATE & IMMEDIATE REVOCATION TEARDOWN
# ============================================================================

def test_dual_consent_gate_enforcement(listening_fixture):
    trip_id = listening_fixture["trip_id"]
    trip_svc = listening_fixture["trip_svc"]
    listening_svc = listening_fixture["listening_svc"]

    # Case A: Neither consented -> Must raise ConsentRequiredError
    with pytest.raises(ConsentRequiredError):
        listening_svc.start_continuous_session(trip_id)

    # Case B: Only driver consented -> Must raise ConsentRequiredError
    trip_svc.update_continuous_listening_consent(trip_id, "DRIVER", True)
    with pytest.raises(ConsentRequiredError):
        listening_svc.start_continuous_session(trip_id)

    # Case C: Both consented -> Starts cleanly
    trip_svc.update_continuous_listening_consent(trip_id, "PASSENGER", True)
    session = listening_svc.start_continuous_session(trip_id)
    assert session["is_active"] is True
    assert listening_svc.is_listening_active(trip_id) is True

    # Case D: Passenger revokes consent -> Stops immediately
    trip_svc.update_continuous_listening_consent(trip_id, "PASSENGER", False)
    assert listening_svc.is_listening_active(trip_id) is False
