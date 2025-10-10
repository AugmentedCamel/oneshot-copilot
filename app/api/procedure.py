"""Procedure control API endpoints."""
from fastapi import APIRouter, HTTPException
from typing import Dict
from app.config import settings
from app.core.statemachine import UserStateMachine
from app.core.callbacks import on_step_sync, on_progress_sync, post_to_vlm_sync
from app.models.procedure import load_procedure

router = APIRouter()

# Create shared state machine instance (singleton)
machine = UserStateMachine(
    on_step=on_step_sync,
    on_progress_step=on_progress_sync,
    post_to_vlm=post_to_vlm_sync,
    max_frames_per_user=settings.MAX_FRAMES_PER_USER
)


@router.post("/start_procedure")
async def start_procedure(
    username: str,
    procedure_file: str = "app/data/procedures/pizza_custom.json"
) -> Dict:
    """
    Start a new procedure for a user.
    
    Args:
        username: Username
        procedure_file: Path to procedure JSON file
        
    Returns:
        Success response
    """
    try:
        proc = load_procedure(procedure_file)
        machine.start_procedure(username, proc)
        return {"ok": True, "procedure_id": proc.id}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Procedure file not found: {procedure_file}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start procedure: {str(e)}")


@router.get("/status")
async def status(username: str) -> Dict:
    """
    Get current status for a user.
    
    Args:
        username: Username
        
    Returns:
        Status object with state, current step, etc.
    """
    return machine.status(username)


@router.post("/pause")
async def pause(username: str) -> Dict:
    """
    Pause active procedure for a user.
    
    Args:
        username: Username
        
    Returns:
        Success response
    """
    machine.pause(username)
    return {"ok": True}


@router.post("/resume")
async def resume(username: str) -> Dict:
    """
    Resume paused procedure for a user.
    
    Args:
        username: Username
        
    Returns:
        Success response
    """
    machine.resume(username)
    return {"ok": True}


@router.post("/abort")
async def abort(username: str) -> Dict:
    """
    Abort active procedure for a user.
    
    Args:
        username: Username
        
    Returns:
        Success response
    """
    machine.abort(username)
    return {"ok": True}