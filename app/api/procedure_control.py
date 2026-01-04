"""Procedure Control API endpoints.

Provides manual control over procedure progression for testing purposes.
Currently implemented for NodeGraph procedures only.

NOTE: When implementing new procedure strategies, add control support by
implementing: set_auto_progress, force_next, force_prev, get_control_status.
See DESIGN.md for the control interface specification.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.config import settings

router = APIRouter()


class AutoProgressRequest(BaseModel):
    username: str
    enabled: bool


class ControlRequest(BaseModel):
    username: str


@router.post("/nodegraph/control/auto_progress")
async def toggle_auto_progress(request: AutoProgressRequest):
    """Toggle AI-driven auto progression on/off for a user's session.
    
    When disabled, AI predictions are still processed but don't trigger
    step transitions. Use force_next/force_prev for manual control.
    """
    if settings.PROCEDURE_STRATEGY != "nodegraph":
        raise HTTPException(
            status_code=400, 
            detail="Node graph strategy is not enabled"
        )
    
    from app.services.nodegraph_service import get_nodegraph_service
    service = get_nodegraph_service()
    
    success = service.set_auto_progress(request.username, request.enabled)
    if not success:
        raise HTTPException(status_code=404, detail="No active session for user")
    
    return {
        "status": "updated",
        "username": request.username,
        "auto_progress_enabled": request.enabled
    }


@router.post("/nodegraph/control/next")
async def force_next_step(request: ControlRequest):
    """Force advance to the next node (follows on_success transition).
    
    Records the current node in history for prev navigation.
    Returns 400 if already at a terminal node with no next transition.
    """
    if settings.PROCEDURE_STRATEGY != "nodegraph":
        raise HTTPException(
            status_code=400, 
            detail="Node graph strategy is not enabled"
        )
    
    from app.services.nodegraph_service import get_nodegraph_service
    service = get_nodegraph_service()
    
    result = await service.force_next_node(request.username)
    if result is None:
        raise HTTPException(
            status_code=400, 
            detail="No active session, no current node, or no next transition available"
        )
    
    return {
        "status": "advanced",
        "current_node": result
    }


@router.post("/nodegraph/control/prev")
async def force_prev_step(request: ControlRequest):
    """Return to the previous node from history.
    
    Uses visited_nodes history to determine the previous node.
    Returns 400 if at the start with no history.
    """
    if settings.PROCEDURE_STRATEGY != "nodegraph":
        raise HTTPException(
            status_code=400, 
            detail="Node graph strategy is not enabled"
        )
    
    from app.services.nodegraph_service import get_nodegraph_service
    service = get_nodegraph_service()
    
    result = await service.force_prev_node(request.username)
    if result is None:
        raise HTTPException(
            status_code=400, 
            detail="No active session or no history to go back to"
        )
    
    return {
        "status": "reverted",
        "current_node": result
    }


@router.get("/nodegraph/control/status")
async def get_control_status(username: str):
    """Get the current control state for a user's session.
    
    Returns auto_progress status, current node, and navigation capabilities.
    """
    if settings.PROCEDURE_STRATEGY != "nodegraph":
        raise HTTPException(
            status_code=400, 
            detail="Node graph strategy is not enabled"
        )
    
    from app.services.nodegraph_service import get_nodegraph_service
    service = get_nodegraph_service()
    
    result = service.get_control_status(username)
    if result is None:
        raise HTTPException(status_code=404, detail="No active session for user")
    
    return result
