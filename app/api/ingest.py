"""Frame ingestion API endpoint."""
from fastapi import APIRouter, UploadFile, Form, File, HTTPException
from typing import Dict
from app.core.frame_store import store_frame
from app.api.procedure import machine

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
    try:
        # Read and store frame bytes
        frame_bytes = await file.read()
        store_frame(frame_id, frame_bytes)
        
        # Add frame to user's buffer (may trigger VLM dispatch)
        machine.ingest_frame(username, frame_id)
        
        return {
            "ok": True,
            "queued": True,
            "frame_id": frame_id,
            "username": username
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to ingest frame: {str(e)}")