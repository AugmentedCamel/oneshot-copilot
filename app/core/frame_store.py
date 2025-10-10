"""In-memory storage for frame bytes."""
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Global frame storage: frame_id -> bytes
_frame_store: Dict[str, bytes] = {}


def store_frame(frame_id: str, frame_bytes: bytes) -> None:
    """Store frame bytes by frame_id."""
    size_kb = len(frame_bytes) / 1024
    logger.debug(f"[FRAME_STORE] Storing frame - frame_id={frame_id}, size={size_kb:.2f} KB")
    _frame_store[frame_id] = frame_bytes
    logger.debug(f"[FRAME_STORE] Frame stored - frame_id={frame_id}, total_frames={len(_frame_store)}")


def get_frame(frame_id: str) -> Optional[bytes]:
    """Retrieve frame bytes by frame_id."""
    logger.debug(f"[FRAME_STORE] Retrieving frame - frame_id={frame_id}")
    frame_bytes = _frame_store.get(frame_id)
    if frame_bytes:
        size_kb = len(frame_bytes) / 1024
        logger.debug(f"[FRAME_STORE] Frame retrieved - frame_id={frame_id}, size={size_kb:.2f} KB")
    else:
        logger.warning(f"[FRAME_STORE] Frame not found - frame_id={frame_id}")
    return frame_bytes


def clear_frame(frame_id: str) -> None:
    """Remove frame from storage."""
    logger.debug(f"[FRAME_STORE] Clearing frame - frame_id={frame_id}")
    removed = _frame_store.pop(frame_id, None)
    if removed:
        logger.debug(f"[FRAME_STORE] Frame cleared - frame_id={frame_id}, remaining_frames={len(_frame_store)}")
    else:
        logger.debug(f"[FRAME_STORE] Frame not found for clearing - frame_id={frame_id}")


def get_store_size() -> int:
    """Get number of frames in storage."""
    size = len(_frame_store)
    logger.debug(f"[FRAME_STORE] Store size queried - total_frames={size}")
    return size