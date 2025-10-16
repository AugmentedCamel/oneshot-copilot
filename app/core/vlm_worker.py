"""VLM worker task for processing frames from the async queue."""
import asyncio
import logging
from typing import Optional, Dict
from time import time

logger = logging.getLogger(__name__)

# Module-level worker task reference
_worker_task: Optional[asyncio.Task] = None
_worker_running: bool = False

# Module-level dict to store queue wait times by frame_id for metrics collection
# This allows the callback to access queue timing information
_frame_queue_timings: Dict[str, float] = {}


async def vlm_worker_loop():
    """
    Main worker loop that continuously processes frames from the queue.
    
    This worker:
    - Dequeues frames from the frame queue
    - Passes them to the state machine for processing
    - Handles errors gracefully without crashing
    - Logs processing times and queue metrics
    """
    from app.core.frame_queue import get_frame_queue
    from app.api.procedure import machine
    
    global _worker_running
    _worker_running = True
    
    logger.info("[WORKER] VLM worker loop started")
    
    frame_queue = get_frame_queue()
    
    while _worker_running:
        try:
            # Dequeue next frame (blocks until available)
            item = await frame_queue.dequeue()
            
            if item is None:
                # Queue is shutting down or error occurred
                logger.debug("[WORKER] Received None from queue, continuing...")
                await asyncio.sleep(0.1)
                continue
            
            # Calculate queue wait time
            dequeue_time = time()
            queue_wait_ms = (dequeue_time - item.enqueue_time) * 1000
            
            # Store queue wait time for metrics collection in callback
            frame_id = item.frame_data
            _frame_queue_timings[frame_id] = queue_wait_ms
            
            logger.info(
                f"[WORKER] Processing frame - "
                f"user_id={item.user_id}, "
                f"frame_id={frame_id}, "
                f"queue_wait={queue_wait_ms:.2f}ms"
            )
            
            # Record processing start time
            process_start = time()
            
            try:
                # Pass frame to state machine for processing
                # The state machine will handle dispatching to VLM if appropriate
                # Note: VLM processing happens asynchronously in callback, metrics collected there
                machine.ingest_frame(item.user_id, frame_id)
                
                # Calculate processing time (just the state machine call, not VLM)
                process_duration_ms = (time() - process_start) * 1000
                
                logger.debug(
                    f"[WORKER] Frame handed to state machine - "
                    f"user_id={item.user_id}, "
                    f"frame_id={frame_id}, "
                    f"state_machine_duration={process_duration_ms:.2f}ms"
                )
                
            except Exception as e:
                # Log error but don't crash the worker
                logger.error(
                    f"[WORKER] Error processing frame - "
                    f"user_id={item.user_id}, "
                    f"frame_id={item.frame_data}, "
                    f"error: {str(e)}",
                    exc_info=True
                )
                # Small delay to prevent tight error loop
                await asyncio.sleep(0.1)
            
        except asyncio.CancelledError:
            # Worker is being shut down
            logger.info("[WORKER] Worker loop cancelled, shutting down...")
            break
            
        except Exception as e:
            # Catch-all for unexpected errors
            logger.error(
                f"[WORKER] Unexpected error in worker loop: {str(e)}",
                exc_info=True
            )
            # Small delay to prevent tight error loop
            await asyncio.sleep(0.5)
    
    _worker_running = False
    logger.info("[WORKER] VLM worker loop stopped")


async def start_vlm_worker():
    """
    Start the VLM worker background task.
    
    This creates and starts the worker task that will process frames
    from the queue until shutdown.
    """
    global _worker_task, _worker_running
    
    if _worker_task is not None:
        logger.warning("[WORKER] Worker already running, not starting another")
        return
    
    logger.info("[WORKER] Starting VLM worker task...")
    _worker_task = asyncio.create_task(vlm_worker_loop())
    logger.info("[WORKER] VLM worker task started successfully")


async def stop_vlm_worker():
    """
    Stop the VLM worker background task.
    
    This cancels the worker task and waits for it to complete gracefully.
    """
    global _worker_task, _worker_running
    
    if _worker_task is None:
        logger.info("[WORKER] No worker task to stop")
        return
    
    logger.info("[WORKER] Stopping VLM worker task...")
    _worker_running = False
    _worker_task.cancel()
    
    try:
        await _worker_task
    except asyncio.CancelledError:
        logger.info("[WORKER] Worker task cancelled successfully")
    except Exception as e:
        logger.error(f"[WORKER] Error stopping worker task: {str(e)}", exc_info=True)
    
    _worker_task = None
    logger.info("[WORKER] VLM worker task stopped")


def is_worker_running() -> bool:
    """
    Check if the worker is currently running.
    
    Returns:
        True if worker is running, False otherwise
    """
    return _worker_running