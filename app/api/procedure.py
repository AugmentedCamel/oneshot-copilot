"""Procedure control API endpoints."""
import logging
from fastapi import APIRouter, HTTPException
from typing import Dict
from app.config import settings
from app.core.statemachine import UserStateMachine
from app.core.callbacks import on_step_sync, on_progress_sync, post_to_vlm_sync
from app.models.procedure import load_procedure

logger = logging.getLogger(__name__)
router = APIRouter()

# Create shared state machine instance (singleton)
logger.info("Initializing UserStateMachine...")
machine = UserStateMachine(
    on_step=on_step_sync,
    on_progress_step=on_progress_sync,
    post_to_vlm=post_to_vlm_sync,
    max_frames_per_user=settings.MAX_FRAMES_PER_USER
)
logger.info(f"UserStateMachine initialized with max_frames_per_user={settings.MAX_FRAMES_PER_USER}")


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
    logger.info(f"[START_PROCEDURE] Request received - username={username}, procedure_file={procedure_file}")
    try:
        logger.debug(f"Loading procedure from file: {procedure_file}")
        proc = load_procedure(procedure_file)
        logger.debug(f"Procedure loaded: id={proc.id}, name={proc.name}, version={proc.version}, steps={len(proc.steps)}")
        
        logger.info(f"Starting procedure for user '{username}': {proc.id}")
        machine.start_procedure(username, proc)
        logger.info(f"[START_PROCEDURE] Success - username={username}, procedure_id={proc.id}")
        return {"ok": True, "procedure_id": proc.id}
    except FileNotFoundError:
        logger.error(f"[START_PROCEDURE] Failed - Procedure file not found: {procedure_file}")
        raise HTTPException(status_code=404, detail=f"Procedure file not found: {procedure_file}")
    except Exception as e:
        logger.error(f"[START_PROCEDURE] Failed - username={username}, error: {str(e)}", exc_info=True)
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
    logger.debug(f"[STATUS] Request received - username={username}")
    status_data = machine.status(username)
    logger.debug(f"[STATUS] Response - username={username}, state={status_data.get('state')}, step_id={status_data.get('current_step_id')}")
    return status_data


@router.post("/pause")
async def pause(username: str) -> Dict:
    """
    Pause active procedure for a user.
    
    Args:
        username: Username
        
    Returns:
        Success response
    """
    logger.info(f"[PAUSE] Request received - username={username}")
    machine.pause(username)
    logger.info(f"[PAUSE] Success - username={username}")
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
    logger.info(f"[RESUME] Request received - username={username}")
    machine.resume(username)
    logger.info(f"[RESUME] Success - username={username}")
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
    logger.info(f"[ABORT] Request received - username={username}")
    machine.abort(username)
    logger.info(f"[ABORT] Success - username={username}")
    return {"ok": True}