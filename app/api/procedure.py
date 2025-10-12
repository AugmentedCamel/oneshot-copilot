"""Procedure control API endpoints."""
import json
import logging
import os
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


@router.get("/procedure")
async def get_procedure_status(username: str) -> Dict:
    """
    Get current procedure status with steps for a user.
    
    Args:
        username: Username (query parameter)
        
    Returns:
        JSON with username, id, name, version, and steps with status
        
    Raises:
        404: User has no active procedure
        
    Special case:
        If username="dummy", returns the debug dummy.json file for frontend testing.
        This file can be manually edited and changes are reflected immediately (no caching).
    """
    # Add diagnostic logging
    logger.info(f"[GET_PROCEDURE_STATUS] ========== ENDPOINT HIT ==========")
    logger.info(f"[GET_PROCEDURE_STATUS] Received username: '{username}' (type: {type(username).__name__})")
    logger.info(f"[GET_PROCEDURE_STATUS] Is 'dummy'? {username == 'dummy'}")
    
    # DEBUG ENDPOINT: Return dummy.json file for testing
    if username == "dummy":
        logger.info("[GET_PROCEDURE_STATUS] DEBUG endpoint accessed - returning dummy.json")
        dummy_file_path = "app/data/user_status/dummy.json"
        
        try:
            # Read file on every request (no caching) for immediate testing
            if not os.path.exists(dummy_file_path):
                logger.error(f"[GET_PROCEDURE_STATUS] DEBUG file not found: {dummy_file_path}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Debug file not found: {dummy_file_path}. Please create it first."
                )
            
            with open(dummy_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Remove the _comment field from response if present
            if '_comment' in data:
                del data['_comment']
            
            logger.info(f"[GET_PROCEDURE_STATUS] DEBUG Success - returned dummy.json with {len(data.get('steps', []))} steps")
            return data
            
        except json.JSONDecodeError as e:
            logger.error(f"[GET_PROCEDURE_STATUS] DEBUG Invalid JSON in {dummy_file_path}: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Invalid JSON in debug file: {str(e)}"
            )
        except Exception as e:
            logger.error(f"[GET_PROCEDURE_STATUS] DEBUG Failed to read {dummy_file_path}: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to read debug file: {str(e)}"
            )
    
    # Normal behavior for non-debug users
    logger.info(f"[GET_PROCEDURE_STATUS] Request received - username={username}")
    status_data = machine.get_procedure_status(username)
    
    if not status_data:
        logger.warning(f"[GET_PROCEDURE_STATUS] No active procedure - username={username}")
        raise HTTPException(status_code=404, detail=f"No active procedure for user: {username}")
    
    logger.info(f"[GET_PROCEDURE_STATUS] Success - username={username}, procedure={status_data.get('id')}")
    return status_data