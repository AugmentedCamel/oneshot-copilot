"""In-memory storage for frame bytes."""
from typing import Dict, Optional


# Global frame storage: frame_id -> bytes
_frame_store: Dict[str, bytes] = {}


def store_frame(frame_id: str, frame_bytes: bytes) -> None:
    """Store frame bytes by frame_id."""
    _frame_store[frame_id] = frame_bytes


def get_frame(frame_id: str) -> Optional[bytes]:
    """Retrieve frame bytes by frame_id."""
    return _frame_store.get(frame_id)


def clear_frame(frame_id: str) -> None:
    """Remove frame from storage."""
    _frame_store.pop(frame_id, None)


def get_store_size() -> int:
    """Get number of frames in storage."""
    return len(_frame_store)