"""
LangGraph Agent State Definition for T2T DRIVE.
Defines the conversational state passed between nodes in the LangGraph workflow.
"""

from typing import Dict, Any, List, Optional
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    """
    State schema for the T2T DRIVE conversational agent graph.
    """
    session_id: str
    driver_id: str
    language: str  # "tanglish", "tamil", "english"
    user_message: str
    
    # NLU parsing outputs
    intent: str
    confidence: float
    slots: Dict[str, Any]
    missing_slots: List[str]
    
    # Financial workflow tracking
    active_pending_action: Optional[Dict[str, Any]]
    execution_result: Optional[Dict[str, Any]]
    
    # Natural Language Output
    response_message: str
    response_voice_text: str
    next_step: str
    error: Optional[str]
