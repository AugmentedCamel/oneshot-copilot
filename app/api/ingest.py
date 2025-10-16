"""Frame ingestion API endpoint."""
import logging
from fastapi import APIRouter, UploadFile, Form, File, HTTPException
from typing import Dict
from time import perf_counter, time
from app.core.frame_store import store_frame
from app.core.frame_queue import get_frame_queue, FrameQueueItem

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
    # [TIMING] Record API endpoint entry time
    api_start = perf_counter()
    logger.info(f"[⏱️ TIMING] Frame ingest API called - username={username}, frame_id={frame_id}")
    logger.info(f"[INGEST] Request received - username={username}, frame_id={frame_id}, filename={file.filename}")
    try:
        # [TIMING] Read and store frame bytes
        file_read_start = perf_counter()
        logger.debug(f"Reading frame bytes from uploaded file: {file.filename}")
        frame_bytes = await file.read()
        file_read_ms = (perf_counter() - file_read_start) * 1000
        frame_size = len(frame_bytes)
        logger.info(f"[⏱️ TIMING] File read completed - size={frame_size} bytes, duration={file_read_ms:.3f}ms")
        
        # [TIMING] Store frame in memory
        frame_store_start = perf_counter()
        logger.debug(f"Storing frame in memory: frame_id={frame_id}")
        store_frame(frame_id, frame_bytes)
        frame_store_ms = (perf_counter() - frame_store_start) * 1000
        logger.info(f"[⏱️ TIMING] Frame stored in memory - duration={frame_store_ms:.3f}ms")
        
        # [TIMING] Enqueue frame for async processing (instead of direct processing)
        enqueue_start = perf_counter()
        frame_queue = get_frame_queue()
        queue_item = FrameQueueItem(
            user_id=username,
            frame_data=frame_id,  # Store frame_id, actual bytes are in frame_store
            enqueue_time=time(),
            procedure_id=None  # Will be determined by state machine
        )
        
        enqueue_success = await frame_queue.enqueue(queue_item)
        enqueue_ms = (perf_counter() - enqueue_start) * 1000
        
        if enqueue_success:
            logger.info(f"[⏱️ TIMING] Frame enqueued - duration={enqueue_ms:.3f}ms")
            logger.info(f"[INGEST] Frame enqueued successfully - username={username}, frame_id={frame_id}")
        else:
            logger.error(f"[INGEST] Failed to enqueue frame - username={username}, frame_id={frame_id}")
        
        # [TIMING] Calculate API processing time with breakdown
        api_end = perf_counter()
        api_duration = (api_end - api_start) * 1000  # Convert to ms
        
        logger.info(f"[⏱️ TIMING] ========== INGEST API BREAKDOWN ==========")
        logger.info(f"[⏱️ TIMING] File Read:           {file_read_ms:7.3f}ms")
        logger.info(f"[⏱️ TIMING] Frame Store:         {frame_store_ms:7.3f}ms")
        logger.info(f"[⏱️ TIMING] Queue Enqueue:       {enqueue_ms:7.3f}ms")
        logger.info(f"[⏱️ TIMING] TOTAL INGEST API:    {api_duration:7.3f}ms")
        logger.info(f"[⏱️ TIMING] ===============================================")
        logger.info(f"[INGEST] Success - username={username}, frame_id={frame_id}, size={frame_size} bytes, queued={enqueue_success}")
        
        return {
            "ok": True,
            "queued": enqueue_success,
            "frame_id": frame_id,
            "username": username
        }
    except Exception as e:
        logger.error(f"[INGEST] Failed - username={username}, frame_id={frame_id}, error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to ingest frame: {str(e)}")