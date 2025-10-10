"""Callback functions for state machine events."""
import asyncio
import logging
import httpx
from typing import Dict, Optional
from app.config import settings
from app.core.vlm_client import post_to_vlm_multipart
from app.core.frame_store import get_frame

logger = logging.getLogger(__name__)


async def on_step_callback(username: str, procedure_id: str, step_id: int, step_name: str) -> None:
    """
    Notify client that user has entered a new step.
    
    Args:
        username: Username
        procedure_id: Procedure identifier
        step_id: Step ID
        step_name: Step name/title
    """
    logger.info(f"[CALLBACK] on_step - username={username}, procedure={procedure_id}, step_id={step_id}, step_name={step_name}")
    try:
        url = f"{settings.MENTRA_URL}/on_step"
        logger.debug(f"[CALLBACK] Sending on_step notification to {url}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                json={
                    "username": username,
                    "text": step_name
                }
            )
            logger.debug(f"[CALLBACK] on_step notification sent - status={response.status_code}")
    except Exception as e:
        logger.error(f"[CALLBACK] Failed to send on_step callback - username={username}, error={str(e)}", exc_info=True)


async def on_progress_callback(
    username: str,
    procedure_id: str,
    from_step: Optional[int],
    to_step: Optional[int]
) -> None:
    """
    Notify client of step progression.
    
    Args:
        username: Username
        procedure_id: Procedure identifier
        from_step: Previous step ID
        to_step: Next step ID (None if completed)
    """
    logger.info(f"[CALLBACK] on_progress - username={username}, procedure={procedure_id}, from_step={from_step}, to_step={to_step}")
    try:
        url = f"{settings.MENTRA_URL}/progress_step"
        logger.debug(f"[CALLBACK] Sending progress notification to {url}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                json={
                    "username": username,
                    "text": "progress",
                    "from_step": from_step,
                    "to_step": to_step
                }
            )
            logger.debug(f"[CALLBACK] progress notification sent - status={response.status_code}")
    except Exception as e:
        logger.error(f"[CALLBACK] Failed to send progress callback - username={username}, error={str(e)}", exc_info=True)


async def post_to_vlm_callback(
    frame_id: str,
    procedure_id: str,
    step_def: Dict,
    username: str,
    idem_key: str
) -> None:
    """
    Dispatch frame to VLM for analysis.
    
    Args:
        frame_id: Frame identifier
        procedure_id: Procedure identifier
        step_def: Step definition dict with positives, negatives, etc.
        username: Username
        idem_key: Idempotency key
    """
    logger.info(f"[CALLBACK] post_to_vlm - username={username}, frame_id={frame_id}, procedure={procedure_id}, step_id={step_def.get('id')}")
    try:
        # Retrieve frame bytes from storage
        logger.debug(f"[CALLBACK] Retrieving frame from storage - frame_id={frame_id}")
        frame_bytes = get_frame(frame_id)
        if not frame_bytes:
            logger.error(f"[CALLBACK] Frame not found in storage - frame_id={frame_id}")
            return
        logger.debug(f"[CALLBACK] Frame retrieved successfully - frame_id={frame_id}, size={len(frame_bytes)} bytes")
        
        # Build webhook URL with query parameters
        webhook_url = (
            f"{settings.SELF_URL}/vlm/callback"
            f"?user={username}"
            f"&procedure_id={procedure_id}"
            f"&step_id={step_def['id']}"
            f"&frame_id={frame_id}"
            f"&idem={idem_key}"
        )
        logger.debug(f"[CALLBACK] Webhook URL constructed: {webhook_url}")
        
        # Extract question and negatives from step definition
        question = step_def["positives"][0]
        negatives = step_def["negatives"]
        logger.debug(f"[CALLBACK] VLM request params - question={question}, negatives_count={len(negatives)}")
        
        # Send to VLM
        logger.info(f"[CALLBACK] Dispatching to VLM service - frame_id={frame_id}, vlm_url={settings.VLM_URL}")
        await post_to_vlm_multipart(
            file_bytes=frame_bytes,
            question=question,
            negatives=negatives,
            webhook_url=webhook_url,
            vlm_url=settings.VLM_URL
        )
        logger.info(f"[CALLBACK] VLM dispatch successful - frame_id={frame_id}")
    except Exception as e:
        logger.error(f"[CALLBACK] Failed to send frame to VLM - frame_id={frame_id}, username={username}, error={str(e)}", exc_info=True)


# Synchronous wrappers for callbacks (state machine uses sync callbacks)
def on_step_sync(username: str, procedure_id: str, step_id: int, step_name: str) -> None:
    """Synchronous wrapper for on_step_callback."""
    logger.debug(f"[CALLBACK] on_step_sync wrapper called - creating async task")
    asyncio.create_task(on_step_callback(username, procedure_id, step_id, step_name))


def on_progress_sync(username: str, procedure_id: str, from_step: Optional[int], to_step: Optional[int]) -> None:
    """Synchronous wrapper for on_progress_callback."""
    logger.debug(f"[CALLBACK] on_progress_sync wrapper called - creating async task")
    asyncio.create_task(on_progress_callback(username, procedure_id, from_step, to_step))


def post_to_vlm_sync(frame_id: str, procedure_id: str, step_def: Dict, username: str, idem_key: str) -> None:
    """Synchronous wrapper for post_to_vlm_callback."""
    logger.debug(f"[CALLBACK] post_to_vlm_sync wrapper called - creating async task")
    asyncio.create_task(post_to_vlm_callback(frame_id, procedure_id, step_def, username, idem_key))