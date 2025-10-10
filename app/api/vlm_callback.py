"""VLM callback API endpoint."""
from fastapi import APIRouter, Request, HTTPException
from typing import Dict
from app.models.state import Decision
from app.api.procedure import machine

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
    try:
        # Extract query parameters
        params = dict(request.query_params)
        username = params.get("user")
        frame_id = params.get("frame_id")
        
        if not username or not frame_id:
            raise HTTPException(
                status_code=400,
                detail="Missing required query parameters: user, frame_id"
            )
        
        # Parse body
        body = await request.json()
        decision_str = body.get("decision")
        
        if not decision_str:
            raise HTTPException(status_code=400, detail="Missing decision in body")
        
        # Convert to Decision enum
        try:
            decision = Decision(decision_str)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid decision value: {decision_str}"
            )
        
        # Pass to state machine
        machine.vlm_decision(username, frame_id, decision)
        
        return {
            "ok": True,
            "username": username,
            "frame_id": frame_id,
            "decision": decision.value
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process VLM callback: {str(e)}")