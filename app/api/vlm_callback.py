"""VLM callback API endpoint."""
import logging
import time
from typing import Dict, Optional, Any, List
from fastapi import APIRouter, Request, HTTPException

from app.domain.models import (
    Decision, UserSession, UserState, ProcedureDef, StepDef, StepRuntime, 
    RuleRuntime
)
from app.models.rules import (
    RuleValidationResult, RuleDef, FailureBehavior, RuleType, RuleStatus
)
from app.domain.procedure_engine import ProcedureEngine
from app.services.status_service import load_user_status, save_user_status
from app.services.context_analysis import ContextAnalysisService
from app.services.rule_validation import RuleValidationService

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize services
engine = ProcedureEngine()
context_analyzer = ContextAnalysisService()
rule_validator = RuleValidationService()

def _dict_to_rule_def(data: Dict) -> RuleDef:
    return RuleDef(
        rule_type=RuleType(data["rule_type"]),
        name=data["name"],
        enabled=data.get("enabled", True),
        failure_behavior=FailureBehavior(data.get("failure_behavior", "block")),
        params=data.get("params", {})
    )

def _dict_to_step_def(data: Dict) -> StepDef:
    return StepDef(
        id=data["id"],
        name=data["name"],
        positives=data.get("positives", []),
        negatives=data.get("negatives", []),
        timeout_s=data.get("timeout_s", 60),
        debounce_consecutive_yes=data.get("debounce_consecutive_yes", 2),
        bounding_questions=data.get("bounding_questions", []),
        debug=data.get("debug", False),
        rules=[_dict_to_rule_def(r) for r in data.get("rules", [])]
    )

def _dict_to_procedure_def(data: Dict) -> ProcedureDef:
    return ProcedureDef(
        id=data["id"],
        name=data["name"],
        version=data.get("version", 1),
        steps=[_dict_to_step_def(s) for s in data.get("steps", [])]
    )

def _dict_to_rule_result(data: Dict) -> RuleValidationResult:
    return RuleValidationResult(
        rule_name=data["rule_name"],
        rule_type=RuleType(data.get("rule_type", "custom")),
        status=RuleStatus(data["status"]),
        message=data.get("message", ""),
        details=data.get("details"),
        failure_behavior=FailureBehavior(data.get("failure_behavior", "block"))
    )

def _dict_to_rule_runtime(data: Dict) -> RuleRuntime:
    return RuleRuntime(
        results=[_dict_to_rule_result(r) for r in data.get("results", [])],
        last_validation_ms=data.get("last_validation_ms")
    )

def _dict_to_step_runtime(data: Dict) -> StepRuntime:
    rt = StepRuntime(
        id=data["id"],
        started_at_ms=data["started_at_ms"],
        timeout_at_ms=data["timeout_at_ms"],
        yes_consecutive=data.get("yes_consecutive", 0)
    )
    if data.get("rule_runtime"):
        rt.rule_runtime = _dict_to_rule_runtime(data["rule_runtime"])
    return rt

def reconstruct_session(data: Dict) -> UserSession:
    """Reconstruct UserSession from dictionary."""
    session = UserSession(
        username=data["username"],
        state=UserState(data.get("state", "IDLE")),
        current_index=data.get("current_index", 0),
        inflight=data.get("inflight", False),
        inflight_since_ms=data.get("inflight_since_ms"),
        inflight_frame_id=data.get("inflight_frame_id"),
        buffered_frame=data.get("buffered_frame"),
        last_frame_at_ms=data.get("last_frame_at_ms"),
        last_feedback_sent_ms=data.get("last_feedback_sent_ms")
    )
    
    if data.get("procedure"):
        session.procedure = _dict_to_procedure_def(data["procedure"])
        
    if data.get("step_rt"):
        session.step_rt = _dict_to_step_runtime(data["step_rt"])
        
    return session

def session_to_dict(session: UserSession) -> Dict:
    """Convert UserSession to dictionary for storage."""
    # This is a simplified serialization. 
    # In a real app, we might use a library or have to_dict methods on models.
    # For now, we'll implement what's needed to match the reconstruction.
    
    data = {
        "username": session.username,
        "state": session.state.value,
        "current_index": session.current_index,
        "inflight": session.inflight,
        "inflight_since_ms": session.inflight_since_ms,
        "inflight_frame_id": session.inflight_frame_id,
        "buffered_frame": session.buffered_frame,
        "last_frame_at_ms": session.last_frame_at_ms,
        "last_feedback_sent_ms": session.last_feedback_sent_ms
    }
    
    if session.procedure:
        # We need to serialize the procedure definition
        # Assuming simple dict conversion for now
        # Ideally, we shouldn't duplicate procedure def in every session file, 
        # but for now we follow the existing pattern implied by reconstruct_session
        data["id"] = session.procedure.id  # Required for save_user_status
        data["procedure"] = {
            "id": session.procedure.id,
            "name": session.procedure.name,
            "version": session.procedure.version,
            "steps": [
                {
                    "id": s.id,
                    "name": s.name,
                    "status": "done" if session.state == UserState.COMPLETED else ("done" if i < session.current_index else ("in_progress" if i == session.current_index else "todo")),
                    "positives": s.positives,
                    "negatives": s.negatives,
                    "timeout_s": s.timeout_s,
                    "debounce_consecutive_yes": s.debounce_consecutive_yes,
                    "bounding_questions": s.bounding_questions,
                    "debug": s.debug,
                    "rules": [
                        {
                            "rule_type": r.rule_type.value,
                            "name": r.name,
                            "enabled": r.enabled,
                            "failure_behavior": r.failure_behavior.value,
                            "params": r.params
                        } for r in s.rules
                    ]
                } for i, s in enumerate(session.procedure.steps)
            ]
        }
        
    if session.step_rt:
        rt_data = {
            "id": session.step_rt.id,
            "started_at_ms": session.step_rt.started_at_ms,
            "timeout_at_ms": session.step_rt.timeout_at_ms,
            "yes_consecutive": session.step_rt.yes_consecutive
        }
        if session.step_rt.rule_runtime:
            rt_data["rule_runtime"] = {
                "last_validation_ms": session.step_rt.rule_runtime.last_validation_ms,
                "results": [
                    {
                        "rule_name": r.rule_name,
                        "rule_type": r.rule_type.value,
                        "status": r.status.value,
                        "message": r.message,
                        "details": r.details,
                        "failure_behavior": r.failure_behavior.value
                    } for r in session.step_rt.rule_runtime.results
                ]
            }
        data["step_rt"] = rt_data
        
    return data

@router.post("/vlm/callback")
async def vlm_callback(request: Request) -> Dict:
    """
    Receive VLM decision callback.
    """
    logger.info(f"[VLM_CALLBACK] Request received from VLM service")
    try:
        # Extract query parameters
        params = dict(request.query_params)
        username = params.get("user")
        frame_id = params.get("frame_id")
        procedure_id = params.get("procedure_id")
        
        if not username or not frame_id:
            raise HTTPException(
                status_code=400,
                detail="Missing required query parameters: user, frame_id"
            )
            
        # Parse body
        try:
            body = await request.json()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON body: {str(e)}")
            
        payload = body
        
        # Extract decision
        data = payload.get("data") or {}
        result = data.get("result")
        neg_result = data.get("negative_result")
        final = data.get("final")
        
        if not result and not neg_result and not final:
            # Fallback to response structure
            # Try to find any active procedure for this user?
            # For now, require procedure_id or fail if we can't load
            # But wait, if we don't have procedure_id, we can't load the file with the current naming scheme
            # Let's assume procedure_id is passed or we might need to look it up
            pass

        status_data = load_user_status(username, procedure_id)
        if not status_data:
            logger.warning(f"Session not found for user {username} procedure {procedure_id}")
            # If session not found, we can't process the state machine
            return {"ok": False, "error": "Session not found"}
            
        session = reconstruct_session(status_data)
        
        # Run Procedure Engine
        now_ms = int(time.time() * 1000)
        events = engine.handle_vlm_decision(
            session=session,
            frame_id=frame_id,
            decision=decision,
            vlm_response=payload,
            rule_validator=rule_validator,
            context_analyzer=context_analyzer,
            now_ms=now_ms
        )
        
        # Save updated session
        updated_status_data = session_to_dict(session)
        save_user_status(username, updated_status_data)
        
        # Log events (in a real system, we'd publish them to the event bus)
        for event in events:
            logger.info(f"[EVENT] {event}")
            
        return {
            "ok": True,
            "username": username,
            "frame_id": frame_id,
            "decision": decision.value,
            "events_count": len(events)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[VLM_CALLBACK] Failed to process callback - error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process VLM callback: {str(e)}")