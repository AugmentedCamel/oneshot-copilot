"""Callback functions for state machine events."""
import asyncio
import httpx
from typing import Dict, Optional
from app.config import settings
from app.core.vlm_client import post_to_vlm_multipart
from app.core.frame_store import get_frame


async def on_step_callback(username: str, procedure_id: str, step_id: int, step_name: str) -> None:
    """
    Notify client that user has entered a new step.
    
    Args:
        username: Username
        procedure_id: Procedure identifier
        step_id: Step ID
        step_name: Step name/title
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{settings.MENTRA_URL}/on_step",
                json={
                    "username": username,
                    "text": step_name
                }
            )
    except Exception as e:
        print(f"Failed to send on_step callback: {e}")


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
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{settings.MENTRA_URL}/progress_step",
                json={
                    "username": username,
                    "text": "progress",
                    "from_step": from_step,
                    "to_step": to_step
                }
            )
    except Exception as e:
        print(f"Failed to send progress callback: {e}")


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
    try:
        # Retrieve frame bytes from storage
        frame_bytes = get_frame(frame_id)
        if not frame_bytes:
            print(f"Frame {frame_id} not found in storage")
            return
        
        # Build webhook URL with query parameters
        webhook_url = (
            f"{settings.SELF_URL}/vlm/callback"
            f"?user={username}"
            f"&procedure_id={procedure_id}"
            f"&step_id={step_def['id']}"
            f"&frame_id={frame_id}"
            f"&idem={idem_key}"
        )
        
        # Extract question and negatives from step definition
        question = step_def["positives"][0]
        negatives = step_def["negatives"]
        
        # Send to VLM
        await post_to_vlm_multipart(
            file_bytes=frame_bytes,
            question=question,
            negatives=negatives,
            webhook_url=webhook_url,
            vlm_url=settings.VLM_URL
        )
    except Exception as e:
        print(f"Failed to send frame to VLM: {e}")


# Synchronous wrappers for callbacks (state machine uses sync callbacks)
def on_step_sync(username: str, procedure_id: str, step_id: int, step_name: str) -> None:
    """Synchronous wrapper for on_step_callback."""
    asyncio.create_task(on_step_callback(username, procedure_id, step_id, step_name))


def on_progress_sync(username: str, procedure_id: str, from_step: Optional[int], to_step: Optional[int]) -> None:
    """Synchronous wrapper for on_progress_callback."""
    asyncio.create_task(on_progress_callback(username, procedure_id, from_step, to_step))


def post_to_vlm_sync(frame_id: str, procedure_id: str, step_def: Dict, username: str, idem_key: str) -> None:
    """Synchronous wrapper for post_to_vlm_callback."""
    asyncio.create_task(post_to_vlm_callback(frame_id, procedure_id, step_def, username, idem_key))