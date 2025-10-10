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
        
        # Parse body with new payload structure
        # DIAGNOSTIC: Log raw body content
        try:
            raw_body = await request.body()
            logger.info(f"[VLM_CALLBACK] *** RAW BODY *** - content={raw_body.decode('utf-8', errors='replace')}")
            logger.info(f"[VLM_CALLBACK] *** REQUEST HEADERS *** - content_type={request.headers.get('content-type')}, all_headers={dict(request.headers)}")
        except Exception as e:
            logger.error(f"[VLM_CALLBACK] Failed to read raw body - error={str(e)}")
        
        # Parse JSON body
        try:
            body = await request.json()
            logger.info(f"[VLM_CALLBACK] *** PARSED BODY *** - body={body}, type={type(body)}")
        except Exception as e:
            logger.error(f"[VLM_CALLBACK] Failed to parse JSON body - error={str(e)}")
            raise HTTPException(status_code=400, detail=f"Invalid JSON body: {str(e)}")
        
        # Extract data from new payload structure
        payload = body  # already parsed dict
        data = payload.get("data") or {}
        result = data.get("result")              # "yes"/"no" for the positive question
        neg_result = data.get("negative_result") # "yes"/"no" aggregated negatives
        
        logger.info(f"[VLM_CALLBACK] *** EXTRACTED FIELDS *** - result={result}, negative_result={neg_result}")
        
        # Validate at least one field exists
        if result is None and neg_result is None:
            logger.warning(f"[VLM_CALLBACK] Missing result fields in body")
            raise HTTPException(status_code=400, detail="Missing result fields: expected 'data.result' or 'data.negative_result'")
        
        # Use result as the decision (as per new payload structure)
        decision_str = result
        logger.info(f"[VLM_CALLBACK] *** DECISION SELECTED *** - decision={decision_str}")
        
        # Convert "yes"/"no" to Decision enum
        try:
            if decision_str is None:
                # If result is None, we should have neg_result, but we still need a decision
                # Default to NO if only neg_result is present
                logger.warning(f"[VLM_CALLBACK] Result is None, using default Decision.NO")
                decision = Decision.NO
            elif decision_str.lower() == "yes":
                decision = Decision.YES
                logger.debug(f"Decision parsed: yes -> YES")
            elif decision_str.lower() == "no":
                decision = Decision.NO
                logger.debug(f"Decision parsed: no -> NO")
            else:
                logger.error(f"[VLM_CALLBACK] Invalid decision value: {decision_str}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid decision value: {decision_str}. Expected: 'yes' or 'no'"
                )
        except AttributeError:
            logger.error(f"[VLM_CALLBACK] Decision value is not a string: {decision_str}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid decision type: expected string, got {type(decision_str)}"
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