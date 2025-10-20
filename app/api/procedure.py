"""Procedure control API endpoints."""
import json
import logging
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from typing import Dict, Optional
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


def discover_procedures() -> Dict[str, str]:
    """
    Scan the procedures directory and create a mapping of procedure IDs to file paths.
    
    Returns:
        Dictionary mapping procedure_id to file path
    """
    procedures_dir = Path("app/data/procedures")
    id_to_path = {}
    
    if not procedures_dir.exists():
        logger.warning(f"Procedures directory does not exist: {procedures_dir}")
        return id_to_path
    
    for json_file in procedures_dir.glob("*.json"):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                procedure_id = data.get('id')
                if procedure_id:
                    id_to_path[procedure_id] = str(json_file)
                    logger.debug(f"Discovered procedure: {procedure_id} -> {json_file}")
        except Exception as e:
            logger.warning(f"Failed to read procedure file {json_file}: {str(e)}")
    
    logger.info(f"Discovered {len(id_to_path)} procedures")
    return id_to_path


@router.post("/start_procedure")
async def start_procedure(
    username: str,
    procedure_id: Optional[str] = None,
    procedure_file: Optional[str] = None
) -> Dict:
    """
    Start a new procedure for a user.
    
    Args:
        username: Username
        procedure_id: Procedure ID (e.g., 'pizza_custom@v1'). Takes precedence over procedure_file.
        procedure_file: Direct path to procedure JSON file (fallback if procedure_id not provided)
        
    Returns:
        Success response with procedure_id
        
    Examples:
        - Start by ID: POST /api/start_procedure?username=alice&procedure_id=pizza_custom@v1
        - Start by file: POST /api/start_procedure?username=alice&procedure_file=app/data/procedures/pizza_custom.json
    """
    logger.info(f"[START_PROCEDURE] Request received - username={username}, procedure_id={procedure_id}, procedure_file={procedure_file}")
    
    # Determine which file to load
    file_path = None
    
    if procedure_id:
        # Use procedure_id to find the file
        logger.debug(f"Looking up procedure by ID: {procedure_id}")
        procedures = discover_procedures()
        
        if procedure_id not in procedures:
            logger.error(f"[START_PROCEDURE] Failed - Procedure ID not found: {procedure_id}")
            available = ', '.join(procedures.keys()) if procedures else 'none'
            raise HTTPException(
                status_code=404,
                detail=f"Procedure ID '{procedure_id}' not found. Available procedures: {available}"
            )
        
        file_path = procedures[procedure_id]
        logger.debug(f"Resolved procedure ID '{procedure_id}' to file: {file_path}")
        
    elif procedure_file:
        # Use direct file path
        file_path = procedure_file
        logger.debug(f"Using direct file path: {file_path}")
        
    else:
        # No parameters provided - return error
        logger.error("[START_PROCEDURE] Failed - Neither procedure_id nor procedure_file provided")
        raise HTTPException(
            status_code=400,
            detail="Either 'procedure_id' or 'procedure_file' parameter must be provided"
        )
    
    # Load and start the procedure
    try:
        logger.debug(f"Loading procedure from file: {file_path}")
        proc = load_procedure(file_path)
        logger.debug(f"Procedure loaded: id={proc.id}, name={proc.name}, version={proc.version}, steps={len(proc.steps)}")
        
        logger.info(f"Starting procedure for user '{username}': {proc.id}")
        machine.start_procedure(username, proc)
        logger.info(f"[START_PROCEDURE] Success - username={username}, procedure_id={proc.id}")
        return {"ok": True, "procedure_id": proc.id}
        
    except FileNotFoundError:
        logger.error(f"[START_PROCEDURE] Failed - Procedure file not found: {file_path}")
        raise HTTPException(status_code=404, detail=f"Procedure file not found: {file_path}")
    except Exception as e:
        logger.error(f"[START_PROCEDURE] Failed - username={username}, error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start procedure: {str(e)}")


@router.get("/procedures")
async def list_procedures() -> Dict:
    """
    Get list of all available procedures.
    
    Returns:
        JSON with list of procedures containing id, name, version, and step count
        
    Example response:
    {
        "procedures": [
            {
                "id": "pizza_custom@v1",
                "name": "Make a Custom Pizza",
                "version": 1,
                "steps": 3
            },
            {
                "id": "candy_veg_detection@v1",
                "name": "Detect Candy and Vegetables Alternating",
                "version": 1,
                "steps": 7
            }
        ]
    }
    """
    logger.info("[LIST_PROCEDURES] Request received")
    procedures_dir = Path("app/data/procedures")
    procedures_list = []
    
    if not procedures_dir.exists():
        logger.warning(f"[LIST_PROCEDURES] Procedures directory does not exist: {procedures_dir}")
        return {"procedures": []}
    
    for json_file in sorted(procedures_dir.glob("*.json")):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                procedure_info = {
                    "id": data.get("id", "unknown"),
                    "name": data.get("name", "Unknown Procedure"),
                    "version": data.get("version", 1),
                    "steps": len(data.get("steps", []))
                }
                procedures_list.append(procedure_info)
                logger.debug(f"[LIST_PROCEDURES] Found procedure: {procedure_info['id']}")
                
        except Exception as e:
            logger.warning(f"[LIST_PROCEDURES] Failed to read procedure file {json_file}: {str(e)}")
    
    logger.info(f"[LIST_PROCEDURES] Success - returning {len(procedures_list)} procedures")
    return {"procedures": procedures_list}


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
        
    Special behavior for manual testing:
        This endpoint first checks if a user_status JSON file exists for the username.
        If found, it reads directly from the file (allowing manual edits for testing).
        Otherwise, it falls back to the state machine's in-memory state.
        
        Files can be edited manually at: app/data/user_status/{username}_{procedure_id}.json
    """
    logger.info(f"[GET_PROCEDURE_STATUS] Request received - username={username}")
    
    # First, check state machine for active procedure (prioritize running procedures)
    logger.info(f"[GET_PROCEDURE_STATUS] Checking state machine for active procedure - username={username}")
    status_data = machine.get_procedure_status(username)
    
    if status_data:
        # Found active procedure in state machine - return it
        logger.info(f"[GET_PROCEDURE_STATUS] Success - username={username}, procedure={status_data.get('id')} (from state machine)")
        return status_data
    
    # No active procedure in state machine - check for user_status JSON files for manual testing
    # This allows manual testing by editing JSON files directly when no procedure is running
    logger.info(f"[GET_PROCEDURE_STATUS] No active procedure in state machine, checking user_status files")
    status_dir = Path("app/data/user_status")
    
    if status_dir.exists():
        # Look for JSON files matching the username pattern
        # Try exact match first (e.g., dummy.json), then pattern match (e.g., Miak_pizza_custom@v1.json)
        user_files = []
        exact_match = status_dir / f"{username}.json"
        if exact_match.exists():
            user_files.append(exact_match)
        else:
            user_files = list(status_dir.glob(f"{username}_*.json"))
        
        if user_files:
            # Use the first matching file (most recent or only one)
            status_file = user_files[0]
            logger.info(f"[GET_PROCEDURE_STATUS] Found user status file: {status_file}")
            
            try:
                with open(status_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Remove the _comment field from response if present
                if '_comment' in data:
                    data_copy = data.copy()
                    del data_copy['_comment']
                    logger.info(f"[GET_PROCEDURE_STATUS] Success - returned file data for {username} with {len(data_copy.get('steps', []))} steps (from user_status file)")
                    return data_copy
                
                logger.info(f"[GET_PROCEDURE_STATUS] Success - returned file data for {username} with {len(data.get('steps', []))} steps (from user_status file)")
                return data
                
            except json.JSONDecodeError as e:
                logger.error(f"[GET_PROCEDURE_STATUS] Invalid JSON in {status_file}: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Invalid JSON in status file: {str(e)}"
                )
            except Exception as e:
                logger.error(f"[GET_PROCEDURE_STATUS] Failed to read {status_file}: {str(e)}")
                # Fall through to error
                logger.warning(f"[GET_PROCEDURE_STATUS] File read failed, no active procedure found")
    
    # No active procedure and no fallback file
    logger.warning(f"[GET_PROCEDURE_STATUS] No active procedure - username={username}")
    raise HTTPException(status_code=404, detail=f"No active procedure for user: {username}")


@router.post("/trigger_stream_reconnect")
async def trigger_stream_reconnect_endpoint() -> Dict:
    """
    Trigger an immediate reconnection attempt for the RTSP stream.
    Useful when you know a stream has just become available.
    
    Returns:
        Success response
    """
    logger.info("[STREAM] Reconnection trigger requested")
    try:
        # Import here to avoid circular dependency
        import app.main as main_module
        if hasattr(main_module, 'trigger_stream_reconnect'):
            main_module.trigger_stream_reconnect()
            logger.info("[STREAM] Reconnection signal sent")
            return {"ok": True, "message": "Stream reconnection triggered"}
        else:
            logger.warning("[STREAM] Stream reconnection function not available")
            return {"ok": False, "message": "Stream reconnection not available"}
    except Exception as e:
        logger.error(f"[STREAM] Failed to trigger reconnection: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to trigger reconnection: {str(e)}")
    return status_data