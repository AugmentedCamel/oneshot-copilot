"""Frame ingestion API endpoint."""
import logging
from fastapi import APIRouter, UploadFile, Form, File, HTTPException
from typing import Dict
from app.core.frame_store import store_frame
from app.api.procedure import machine

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/ingest")
async def ingest(
    username: str = Form(...),
    frame_id: str = Form(...),
    file: UploadFile = File(...)
) -> Dict:
    """
    Ingest a frame from the client.
    
    This endpoint:
    1. Receives multipart form data with username, frame_id, and image file
    2. Stores the frame bytes in memory
    3. Adds the frame to the user's buffer in the state machine
    4. State machine may dispatch to VLM if conditions are met
    
    Args:
        username: Username
        frame_id: Unique frame identifier
        file: Image file upload
        
    Returns:
        Success response
    """
    logger.info(f"[INGEST] Request received - username={username}, frame_id={frame_id}, filename={file.filename}")
    try:
        # Read and store frame bytes
        logger.debug(f"Reading frame bytes from uploaded file: {file.filename}")
        frame_bytes = await file.read()
        frame_size = len(frame_bytes)
        logger.debug(f"Frame bytes read: size={frame_size} bytes")
        
        logger.debug(f"Storing frame in memory: frame_id={frame_id}")
        store_frame(frame_id, frame_bytes)
        logger.debug(f"Frame stored successfully: frame_id={frame_id}")
        
        # Add frame to user's buffer (may trigger VLM dispatch)
        logger.debug(f"Adding frame to user buffer: username={username}, frame_id={frame_id}")
        machine.ingest_frame(username, frame_id)
        logger.info(f"[INGEST] Success - username={username}, frame_id={frame_id}, size={frame_size} bytes")
        
        return {
            "ok": True,
            "queued": True,
            "frame_id": frame_id,
            "username": username
        }
    except Exception as e:
        logger.error(f"[INGEST] Failed - username={username}, frame_id={frame_id}, error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to ingest frame: {str(e)}")