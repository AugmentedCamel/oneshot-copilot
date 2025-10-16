"""In-memory storage for frame bytes."""
import logging
import os
from typing import Dict, Optional
from time import perf_counter
from pathlib import Path

logger = logging.getLogger(__name__)

# Global frame storage: frame_id -> bytes
_frame_store: Dict[str, bytes] = {}


def store_frame(frame_id: str, frame_bytes: bytes) -> None:
    """Store frame bytes by frame_id and optionally save to disk."""
    start = perf_counter()
    size_kb = len(frame_bytes) / 1024
    logger.debug(f"[FRAME_STORE] Storing frame - frame_id={frame_id}, size={size_kb:.2f} KB")
    _frame_store[frame_id] = frame_bytes
    
    # Save to disk if enabled
    from app.config import settings, FRAMES_DIRECTORY
    if settings.SAVE_FRAMES_TO_DISK:
        try:
            # Create directory if it doesn't exist
            frames_dir = Path(FRAMES_DIRECTORY)
            frames_dir.mkdir(parents=True, exist_ok=True)
            
            # Save frame to disk with frame_id as filename
            frame_path = frames_dir / f"{frame_id}.jpg"
            with open(frame_path, 'wb') as f:
                f.write(frame_bytes)
            logger.info(f"[FRAME_STORE] Frame saved to disk - path={frame_path}")
        except Exception as e:
            logger.error(f"[FRAME_STORE] Failed to save frame to disk - frame_id={frame_id}, error={str(e)}")
    
    duration_ms = (perf_counter() - start) * 1000
    logger.debug(f"[FRAME_STORE] Frame stored - frame_id={frame_id}, total_frames={len(_frame_store)}, duration={duration_ms:.3f}ms")


def get_frame(frame_id: str) -> Optional[bytes]:
    """Retrieve frame bytes by frame_id."""
    start = perf_counter()
    logger.debug(f"[FRAME_STORE] Retrieving frame - frame_id={frame_id}")
    frame_bytes = _frame_store.get(frame_id)
    duration_ms = (perf_counter() - start) * 1000
    if frame_bytes:
        size_kb = len(frame_bytes) / 1024
        logger.info(f"[⏱️ TIMING] Frame retrieved - frame_id={frame_id}, size={size_kb:.2f} KB, duration={duration_ms:.3f}ms")
    else:
        logger.warning(f"[FRAME_STORE] Frame not found - frame_id={frame_id}, duration={duration_ms:.3f}ms")
    return frame_bytes


def clear_frame(frame_id: str) -> bool:
    """
    Remove frame from storage.
    
    Args:
        frame_id: Frame identifier to clear
        
    Returns:
        True if frame was found and cleared, False if already cleared
    """
    # Guard against redundant clear requests
    if frame_id not in _frame_store:
        logger.warning(f"[FRAME_STORE] Ignoring redundant clear request - frame_id={frame_id} not in store")
        return False
        
    logger.debug(f"[FRAME_STORE] Clearing frame - frame_id={frame_id}")
    removed = _frame_store.pop(frame_id, None)
    if removed:
        logger.info(f"[FRAME_STORE] ✓ Frame cleared - frame_id={frame_id}, remaining_frames={len(_frame_store)}")
        return True
    else:
        logger.warning(f"[FRAME_STORE] Frame not found for clearing - frame_id={frame_id}")
        return False


def get_store_size() -> int:
    """Get number of frames in storage."""
    size = len(_frame_store)
    logger.debug(f"[FRAME_STORE] Store size queried - total_frames={size}")
    return size