"""Frame queue system for decoupling ingestion from VLM processing."""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
from time import time

logger = logging.getLogger(__name__)

# Module-level singleton
_frame_queue: Optional['FrameQueue'] = None


@dataclass
class FrameQueueItem:
    """
    A queued frame item containing metadata for async processing.
    
    Attributes:
        user_id: Username/user identifier
        frame_data: Frame identifier (we store actual bytes in frame_store)
        enqueue_time: Timestamp when frame was enqueued (for queue_wait_ms metric)
        procedure_id: Optional procedure identifier
    """
    user_id: str
    frame_data: str  # This is actually frame_id, not bytes (bytes are in frame_store)
    enqueue_time: float
    procedure_id: Optional[str] = None


class FrameQueue:
    """
    Bounded async queue for frame processing with drop-oldest semantics.
    
    When the queue is full, the oldest item is dropped and the new item is added.
    This ensures we always process the freshest frames.
    """
    
    def __init__(self, maxsize: int = 10):
        """
        Initialize the frame queue.
        
        Args:
            maxsize: Maximum queue size (default: 10)
        """
        self._queue: asyncio.Queue[FrameQueueItem] = asyncio.Queue(maxsize=maxsize)
        self._maxsize = maxsize
        self._stats = {
            'enqueued': 0,
            'dequeued': 0,
            'dropped': 0
        }
        logger.info(f"FrameQueue initialized with maxsize={maxsize}")
    
    async def enqueue(self, item: FrameQueueItem) -> bool:
        """
        Enqueue a frame item. If queue is full, drop oldest and add new.
        
        Args:
            item: Frame queue item to enqueue
            
        Returns:
            True if enqueued successfully, False if error occurred
        """
        try:
            # Try to add without blocking
            try:
                self._queue.put_nowait(item)
                self._stats['enqueued'] += 1
                logger.debug(f"Frame enqueued - user_id={item.user_id}, frame_id={item.frame_data}, queue_size={self._queue.qsize()}")
                return True
            except asyncio.QueueFull:
                # Queue is full, implement drop-oldest logic
                try:
                    # Remove oldest item (from front of queue)
                    dropped_item = self._queue.get_nowait()
                    self._stats['dropped'] += 1
                    logger.warning(
                        f"Queue full, dropped oldest frame - "
                        f"dropped_user={dropped_item.user_id}, "
                        f"dropped_frame={dropped_item.frame_data}, "
                        f"new_user={item.user_id}, "
                        f"new_frame={item.frame_data}"
                    )
                    
                    # Now add the new item
                    self._queue.put_nowait(item)
                    self._stats['enqueued'] += 1
                    logger.info(f"Frame enqueued after drop - user_id={item.user_id}, frame_id={item.frame_data}")
                    return True
                except Exception as e:
                    logger.error(f"Error in drop-oldest logic: {str(e)}", exc_info=True)
                    return False
        except Exception as e:
            logger.error(f"Error enqueueing frame - user_id={item.user_id}, frame_id={item.frame_data}, error: {str(e)}", exc_info=True)
            return False
    
    async def dequeue(self) -> Optional[FrameQueueItem]:
        """
        Dequeue a frame item. Blocks until an item is available.
        
        Returns:
            Frame queue item, or None if queue is being shut down
        """
        try:
            item = await self._queue.get()
            self._stats['dequeued'] += 1
            queue_wait_ms = (time() - item.enqueue_time) * 1000
            logger.debug(
                f"Frame dequeued - user_id={item.user_id}, "
                f"frame_id={item.frame_data}, "
                f"queue_wait={queue_wait_ms:.2f}ms, "
                f"remaining_in_queue={self._queue.qsize()}"
            )
            return item
        except asyncio.CancelledError:
            logger.info("Dequeue operation cancelled (shutdown)")
            return None
        except Exception as e:
            logger.error(f"Error dequeuing frame: {str(e)}", exc_info=True)
            return None
    
    def get_size(self) -> int:
        """
        Get current queue size.
        
        Returns:
            Number of items currently in queue
        """
        return self._queue.qsize()
    
    def get_stats(self) -> dict:
        """
        Get queue statistics.
        
        Returns:
            Dictionary with enqueued, dequeued, and dropped counts
        """
        return {
            **self._stats,
            'current_size': self.get_size(),
            'maxsize': self._maxsize
        }
    
    def log_stats(self):
        """Log current queue statistics."""
        stats = self.get_stats()
        logger.info(
            f"[QUEUE_STATS] "
            f"enqueued={stats['enqueued']}, "
            f"dequeued={stats['dequeued']}, "
            f"dropped={stats['dropped']}, "
            f"current_size={stats['current_size']}/{stats['maxsize']}"
        )


def get_frame_queue() -> FrameQueue:
    """
    Get the singleton frame queue instance.
    
    Returns:
        The global FrameQueue instance
        
    Raises:
        RuntimeError: If queue hasn't been initialized
    """
    if _frame_queue is None:
        raise RuntimeError("Frame queue not initialized. Call init_frame_queue() first.")
    return _frame_queue


def init_frame_queue(maxsize: int = 10) -> FrameQueue:
    """
    Initialize the singleton frame queue.
    
    Args:
        maxsize: Maximum queue size
        
    Returns:
        The initialized FrameQueue instance
    """
    global _frame_queue
    if _frame_queue is not None:
        logger.warning("Frame queue already initialized, returning existing instance")
        return _frame_queue
    
    _frame_queue = FrameQueue(maxsize=maxsize)
    logger.info(f"Frame queue singleton initialized with maxsize={maxsize}")
    return _frame_queue