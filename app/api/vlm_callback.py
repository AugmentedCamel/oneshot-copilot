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


@router.get("/vlm/vla_callback/test")
async def vla_callback_test() -> Dict:
    """
    Test endpoint to verify VLA callback route is reachable.
    
    Usage: curl http://localhost:8000/api/vlm/vla_callback/test
    """
    print("[VLA_CALLBACK_TEST] Test endpoint hit!")
    logger.warning("[VLA_CALLBACK_TEST] Test endpoint hit!")
    return {
        "status": "ok",
        "message": "VLA callback endpoint is reachable",
        "endpoint": "/api/vlm/vla_callback"
    }

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
    Receive VLM decision callback (legacy endpoint).
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
        
        # Extract decision from legacy format
        data = payload.get("data") or {}
        decision_str = data.get("final") or data.get("result")
        decision = Decision.parse(decision_str)

        status_data = load_user_status(username, procedure_id)
        if not status_data:
            logger.warning(f"Session not found for user {username} procedure {procedure_id}")
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
        
        # Log events
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


@router.post("/vlm/reasoning_callback")
async def reasoning_callback(request: Request) -> Dict:
    """
    Receive reasoning decision callback from ai_node.
    
    Expected payload schema:
    {
        "username": "...",
        "status": "IN_PROGRESS" | "COMPLETE" | "MISTAKE" | "IRRELEVANT",
        "confidence": 0.95,
        "reasoning": "The butter is golden brown...",
        "tts_message": "You seem to be done! The butter looks perfect."
    }
    """
    logger.info(f"[REASONING_CALLBACK] Request received from ai_node")
    try:
        # Parse body
        try:
            payload = await request.json()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON body: {str(e)}")
        
        username = payload.get("username")
        status = payload.get("status")
        confidence = payload.get("confidence", 0.0)
        reasoning = payload.get("reasoning", "")
        tts_message = payload.get("tts_message")
        
        if not username:
            raise HTTPException(status_code=400, detail="Missing required field: username")
        
        if not status:
            raise HTTPException(status_code=400, detail="Missing required field: status")
        
        logger.info(f"[REASONING_CALLBACK] Processing for {username}: status={status}, confidence={confidence}")
        
        # Get active session from procedure_service (in-memory)
        from app.services.procedure_service import procedure_service
        
        sessions = procedure_service._active_sessions.get(username, [])
        if not sessions:
            logger.warning(f"[REASONING_CALLBACK] No active session for user {username}")
            return {"ok": False, "error": "No active session for user"}
        
        # Use the first active session (typically there's only one)
        session = sessions[0]
        
        # Map status to Decision
        status_upper = status.upper()
        decision_map = {
            "COMPLETE": Decision.YES,
            "IN_PROGRESS": Decision.NO,
            "MISTAKE": Decision.NO,
            "IRRELEVANT": Decision.NOT_APPLICABLE
        }
        decision = decision_map.get(status_upper, Decision.NO)
        
        logger.info(f"[REASONING_CALLBACK] Mapped status '{status}' to decision '{decision.value}'")
        
        # Construct minimal vlm_response for compatibility
        vlm_response = {
            "status": status,
            "confidence": confidence,
            "reasoning": reasoning,
            "data": {
                "final": decision.value
            }
        }
        
        # Handle state machine update
        now_ms = int(time.time() * 1000)
        events = engine.handle_vlm_decision(
            session=session,
            frame_id=None,  # Reasoning callbacks are not tied to a specific frame (batched)
            decision=decision,
            vlm_response=vlm_response,
            rule_validator=rule_validator,
            context_analyzer=context_analyzer,
            now_ms=now_ms
        )
        
        # Log events
        for event in events:
            logger.info(f"[REASONING_CALLBACK] Event: {event}")
        
        # Handle TTS feedback (already batched by ai_node, safe to speak)
        if tts_message:
            try:
                from app.services.feedback_service import feedback_service
                await feedback_service.send_agent_reply(username, tts_message)
                logger.info(f"[REASONING_CALLBACK] Sent TTS message to {username}: {tts_message[:50]}...")
            except Exception as e:
                logger.error(f"[REASONING_CALLBACK] Failed to send TTS: {e}")
        
        return {
            "ok": True,
            "username": username,
            "status": status,
            "decision": decision.value,
            "events_count": len(events)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[REASONING_CALLBACK] Failed to process callback - error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process reasoning callback: {str(e)}")


@router.post("/vlm/vla_callback")
async def vla_callback(request: Request) -> Dict:
    """
    Receive VLA (Vision-Language-Action) prediction callback from AI Node.

    This endpoint receives raw stepnode predictions for each frame in the batch.
    Called once per frame in chronological order (batch_index 0, 1, 2, ...).

    Expected payload schema (from AI Node stepnode batching):
    {
        "predictions": {"open_door": 0.85, "closed_door": 0.15},
        "all_probabilities": {"open_door": 0.85, "closed_door": 0.15, "class_irrelevant": 0.0},
        "sequence_id": 142,
        "timings": {"forward_pass_ms": 18.2, "total_ms": 25.3},
        "_buffer_metadata": {
            "procedure_id": "dishwasher_salt_v1",
            "username": "chef_mike",
            "session_id": "abc-123-def",
            "frame_id": "frame_001",
            "batch_index": 0,
            "batch_size": 8,
            "inference_ms": 202.4,
            "per_image_ms": 25.3,
            "processed_at": "2026-01-05T10:23:45.123Z"
        }
    }
    """
    # ========== DEBUG: Always visible logging ==========
    print(f"\n{'='*60}")
    print(f"[VLA_CALLBACK] ===== CALLBACK RECEIVED =====")
    print(f"{'='*60}")
    logger.warning(f"[VLA_CALLBACK] ===== Request received from AI Node =====")

    try:
        # Parse body
        try:
            payload = await request.json()
            print(f"[VLA_CALLBACK] Payload keys: {list(payload.keys())}")
            logger.warning(f"[VLA_CALLBACK] Payload keys: {list(payload.keys())}")
        except Exception as e:
            print(f"[VLA_CALLBACK] ERROR: Invalid JSON body: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid JSON body: {str(e)}")

        # Extract predictions (the core data)
        predictions = payload.get("predictions", {})
        all_probabilities = payload.get("all_probabilities", {})
        sequence_id = payload.get("sequence_id", 0)
        timings = payload.get("timings", {})

        # Extract buffer metadata (contains user context)
        metadata = payload.get("_buffer_metadata", {})
        print(f"[VLA_CALLBACK] Metadata: {metadata}")
        logger.warning(f"[VLA_CALLBACK] Metadata: {metadata}")
        
        # Support both 'username' (new) and 'user_id' (legacy) for backwards compatibility
        username = metadata.get("username") or metadata.get("user_id")
        session_id = metadata.get("session_id")
        frame_id = metadata.get("frame_id")
        procedure_id = metadata.get("procedure_id")
        batch_index = metadata.get("batch_index", 0)
        batch_size = metadata.get("batch_size", 1)

        if not predictions:
            raise HTTPException(status_code=400, detail="Missing required field: predictions")

        if not username:
            raise HTTPException(status_code=400, detail="Missing required field: _buffer_metadata.username")

        logger.info(
            f"[VLA_CALLBACK] Frame {batch_index + 1}/{batch_size} for {username}: "
            f"seq={sequence_id}, frame_id={frame_id}, predictions={predictions}"
        )
        
        # Delegate to NodeGraph service with raw predictions
        from app.services.nodegraph_service import get_nodegraph_service

        service = get_nodegraph_service()
        result = await service.handle_ai_callback_predictions(
            username=username,
            session_id=session_id,
            predictions=predictions,
            sequence_id=sequence_id,
            batch_index=batch_index,
            batch_size=batch_size,
            frame_id=frame_id
        )

        if result.get("processed"):
            logger.info(f"[VLA_CALLBACK] Processed frame {batch_index + 1}/{batch_size} for {username}")
        else:
            reason = result.get("reason", "unknown")
            logger.warning(f"[VLA_CALLBACK] Not processed for {username}: {reason}")

        return {"status": "acknowledged", **result}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[VLA_CALLBACK] Failed to process callback - error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process VLA callback: {str(e)}")