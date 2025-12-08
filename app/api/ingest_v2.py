"""Manual frame ingestion API endpoint for debugging."""
import logging
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Dict
from app.services.ingest_service import ingest_service

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/ingest/frame")
async def ingest_frame(
    source_id: str = Form(...),
    file: UploadFile = File(...)
) -> Dict:
    """
    Manually ingest a frame for a specific source.
    Useful for debugging without an active stream.
    
    Args:
        source_id: ID of the source to associate this frame with
        file: Image file to ingest
        
    Returns:
        Success response with frame ID
    """
    logger.info(f"[MANUAL_INGEST] Request received - source_id={source_id}, filename={file.filename}")
    
    try:
        # Read file bytes
        frame_bytes = await file.read()
        
        # Ingest via service
        frame_id = await ingest_service.ingest_frame(source_id, frame_bytes)
        
        logger.info(f"[MANUAL_INGEST] Success - frame_id={frame_id}")
        return {
            "ok": True,
            "frame_id": frame_id,
            "source_id": source_id,
            "message": "Frame ingested successfully"
        }
        
    except Exception as e:
        logger.error(f"[MANUAL_INGEST] Failed - source_id={source_id}, error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to ingest frame: {str(e)}")
