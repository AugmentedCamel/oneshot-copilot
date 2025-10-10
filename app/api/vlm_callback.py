"""VLM callback API endpoint."""
import logging
from fastapi import APIRouter, Request, HTTPException
from typing import Dict
from app.models.state import Decision
from app.api.procedure import machine

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/vlm/callback")
async def vlm_callback(request: Request) -> Dict:
    """
    Receive VLM decision callback.
    
    This endpoint receives the VLM analysis result and passes it to the state machine.
    Query parameters contain context (user, frame_id, etc.) and the body contains the decision.
    
    Query params:
        - user: Username
        - procedure_id: Procedure ID
        - step_id: Step ID
        - frame_id: Frame ID
        - idem: Idempotency key
        
    Body:
        - decision: YES, NO, UNCERTAIN, or NOT_APPLICABLE
        
    Returns:
        Success response
    """
    logger.info(f"[VLM_CALLBACK] Request received from VLM service")
    try:
        # Extract query parameters
        params = dict(request.query_params)
        username = params.get("user")
        frame_id = params.get("frame_id")
        procedure_id = params.get("procedure_id")
        step_id = params.get("step_id")
        idem_key = params.get("idem")
        
        logger.debug(f"Query params - user={username}, frame_id={frame_id}, procedure_id={procedure_id}, step_id={step_id}, idem={idem_key}")
        
        if not username or not frame_id:
            logger.warning(f"[VLM_CALLBACK] Missing required parameters - user={username}, frame_id={frame_id}")
            raise HTTPException(
                status_code=400,
                detail="Missing required query parameters: user, frame_id"
            )
        
        # Parse body
        body = await request.json()
        decision_str = body.get("decision")
        logger.debug(f"Body - decision={decision_str}")
        
        if not decision_str:
            logger.warning(f"[VLM_CALLBACK] Missing decision in body")
            raise HTTPException(status_code=400, detail="Missing decision in body")
        
        # Convert to Decision enum
        try:
            decision = Decision(decision_str)
            logger.debug(f"Decision parsed successfully: {decision.value}")
        except ValueError:
            logger.error(f"[VLM_CALLBACK] Invalid decision value: {decision_str}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid decision value: {decision_str}"
            )
        
        # Pass to state machine
        logger.info(f"[VLM_CALLBACK] Processing decision - username={username}, frame_id={frame_id}, decision={decision.value}")
        machine.vlm_decision(username, frame_id, decision)
        logger.info(f"[VLM_CALLBACK] Success - username={username}, frame_id={frame_id}, decision={decision.value}")
        
        return {
            "ok": True,
            "username": username,
            "frame_id": frame_id,
            "decision": decision.value
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[VLM_CALLBACK] Failed to process callback - error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process VLM callback: {str(e)}")