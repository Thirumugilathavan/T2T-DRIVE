"""
Consent-Based Continuous Trip Intelligence Service for T2T DRIVE.
Enforces dual-party affirmative consent, in-memory ephemeral buffering,
automatic discarding of ordinary conversation, and immediate buffer wipe on consent revocation.
"""

import time
import logging
from typing import Dict, Any, Optional, List, Callable

from app.models.trip import Trip, TripState, ProposalType
from app.services.trip_service import TripService
from app.voice.streaming_adapter import StreamingSTTAdapterBase, MockStreamingSTTAdapter
from app.agent.trip_nlu import TripEventClassifier, TripUtteranceType

logger = logging.getLogger("t2t_drive.continuous_listening")


class ConsentRequiredError(Exception):
    pass


class ContinuousListeningService:
    """
    Orchestrates consent-governed continuous listening sessions for active trips.
    Enforces the privacy principle: ordinary conversation is discarded from memory;
    only mutually consented, validated trip change proposals are persisted.
    """

    def __init__(
        self,
        trip_service: TripService,
        streaming_adapter: Optional[StreamingSTTAdapterBase] = None,
        event_classifier: Optional[TripEventClassifier] = None
    ):
        self.trip_svc = trip_service
        self.streaming = streaming_adapter or MockStreamingSTTAdapter()
        self.classifier = event_classifier or TripEventClassifier()
        self.active_sessions: Dict[str, Dict[str, Any]] = {}

    def start_continuous_session(
        self,
        trip_id: str,
        language: str = "tanglish"
    ) -> Dict[str, Any]:
        """
        Starts a continuous listening session IF AND ONLY IF both driver
        and passenger have independently granted affirmative consent.
        """
        trip = self.trip_svc.get_trip(trip_id)
        if not trip:
            raise ValueError(f"Trip {trip_id} not found.")

        # Strict Consent Check: Both must be affirmative
        if not trip.consent.is_mutually_consented:
            raise ConsentRequiredError(
                "Continuous listening requires explicit, independent affirmative consent from both driver and passenger."
            )

        # Ensure trip is active
        if trip.state in (TripState.COMPLETED, TripState.CANCELLED):
            raise ValueError("Cannot start continuous listening on a completed or cancelled trip.")

        session_id = f"STREAM_{trip_id}"

        # Initialize session state in memory
        self.active_sessions[trip_id] = {
            "session_id": session_id,
            "trip_id": trip_id,
            "language": language,
            "started_at": time.time(),
            "discarded_conversations": 0,
            "detected_events": 0,
            "is_active": True
        }

        # Start streaming adapter with callback
        def _on_transcript(transcript: str, is_final: bool, confidence: float):
            self.process_in_memory_transcript(trip_id, transcript, is_final, confidence)

        def _on_error(err_msg: str):
            logger.warning("Continuous listening stream error for trip %s: %s", trip_id, err_msg)
            self.stop_continuous_session(trip_id, reason=err_msg)

        success = self.streaming.start_session(
            session_id=session_id,
            language=language,
            on_transcript=_on_transcript,
            on_error=_on_error
        )

        logger.info("Continuous listening session started for trip %s", trip_id)
        return {
            "trip_id": trip_id,
            "session_id": session_id,
            "is_active": success,
            "active": success,
            "listening_mode": "CONTINUOUS",
            "driver_consent": trip.consent.driver_consent,
            "passenger_consent": trip.consent.passenger_consent
        }

    def process_in_memory_transcript(
        self,
        trip_id: str,
        transcript: str,
        is_final: bool,
        stt_confidence: float
    ) -> Optional[Dict[str, Any]]:
        """
        Processes a short-lived speech transcript in memory.
        1. Classifies the utterance.
        2. Discards ordinary conversation, hypothetical remarks, or small talk immediately.
        3. Persists only structured proposals if a trip event is detected.
        """
        if not transcript or not transcript.strip():
            return None

        trip = self.trip_svc.get_trip(trip_id)
        if not trip:
            return None

        # Classify utterance contextually
        u_type, entities, conf = self.classifier.classify_utterance(
            text=transcript,
            current_destination=trip.destination_location
        )

        sess = self.active_sessions.get(trip_id)

        # Rule A: Ordinary conversation or small talk is DISCARDED immediately
        if u_type in (
            TripUtteranceType.GENERAL_CONVERSATION,
            TripUtteranceType.GENERAL_QUESTION,
            TripUtteranceType.HYPOTHETICAL
        ):
            if sess:
                sess["discarded_conversations"] += 1
            # Transcript is purposefully NOT saved to MongoDB
            return None

        # Rule B: Actionable Destination Change
        if u_type == TripUtteranceType.POSSIBLE_DESTINATION_CHANGE and conf >= 0.70:
            new_dest = entities.get("destination_location")
            if new_dest and new_dest.lower() != trip.destination_location.lower():
                try:
                    proposal = self.trip_svc.propose_change(
                        trip_id=trip_id,
                        proposal_type=ProposalType.DESTINATION_CHANGE,
                        proposed_by="AI_VOICE",
                        proposed_value={"destination_location": new_dest},
                        reason="Detected from in-cabin passenger statement"
                    )
                    if sess:
                        sess["detected_events"] += 1
                    return proposal.to_dict()
                except Exception as e:
                    logger.warning("Could not auto-create destination proposal: %s", e)

        # Rule C: Actionable Additional Stop
        elif u_type == TripUtteranceType.POSSIBLE_ADD_STOP and conf >= 0.70:
            stop_loc = entities.get("stop")
            if stop_loc:
                try:
                    proposal = self.trip_svc.propose_change(
                        trip_id=trip_id,
                        proposal_type=ProposalType.ADD_STOP,
                        proposed_by="AI_VOICE",
                        proposed_value={"stop": stop_loc},
                        reason="Detected from in-cabin passenger request"
                    )
                    if sess:
                        sess["detected_events"] += 1
                    return proposal.to_dict()
                except Exception as e:
                    logger.warning("Could not auto-create stop proposal: %s", e)

        # Rule D: Actionable Fare Change
        elif u_type == TripUtteranceType.POSSIBLE_FARE_CHANGE and conf >= 0.75:
            new_fare_str = entities.get("agreed_fare")
            if new_fare_str:
                try:
                    proposal = self.trip_svc.propose_change(
                        trip_id=trip_id,
                        proposal_type=ProposalType.FARE_CHANGE,
                        proposed_by="AI_VOICE",
                        proposed_value={"agreed_fare": new_fare_str},
                        reason="Detected fare discussion in cabin"
                    )
                    if sess:
                        sess["detected_events"] += 1
                    return proposal.to_dict()
                except Exception as e:
                    logger.warning("Could not auto-create fare proposal: %s", e)

        return None

    def stop_continuous_session(self, trip_id: str, reason: str = "STOPPED_BY_USER") -> bool:
        """
        Immediately halts continuous listening, tears down streaming sessions,
        and clears all in-memory buffers.
        """
        if trip_id in self.active_sessions:
            sess = self.active_sessions[trip_id]
            sess["is_active"] = False
            self.streaming.stop_session(sess["session_id"])
            del self.active_sessions[trip_id]
            logger.info("Continuous listening stopped for trip %s (Reason: %s)", trip_id, reason)

        return True

    def is_listening_active(self, trip_id: str) -> bool:
        if trip_id not in self.active_sessions:
            return False
        # Verify trip state and mutual consent in repository
        trip = self.trip_svc.get_trip(trip_id)
        if not trip or trip.state in (TripState.COMPLETED, TripState.CANCELLED) or not trip.continuous_listening_enabled or not trip.consent.is_mutually_consented:
            self.stop_continuous_session(trip_id, reason="TRIP_CLOSED_OR_CONSENT_REVOKED")
            return False
        return self.active_sessions[trip_id]["is_active"]

    def get_session_status(self, trip_id: str) -> Dict[str, Any]:
        return {"active": self.is_listening_active(trip_id)}

    start_session = start_continuous_session
    stop_session = stop_continuous_session
