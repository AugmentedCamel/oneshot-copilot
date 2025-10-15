"""Callback functions for state machine events."""
import asyncio
import logging
import httpx
from typing import Dict, Optional
from time import perf_counter
from app.config import settings
from app.core.vlm_client import post_to_vlm_multipart
from app.core.frame_store import get_frame, clear_frame
from app.models.state import Decision

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
    Dispatch frame to VLM for synchronous analysis via /qa endpoint.
    
    Args:
        frame_id: Frame identifier
        procedure_id: Procedure identifier
        step_def: Step definition dict with positives, negatives, etc.
        username: Username
        idem_key: Idempotency key
    """
    # [TIMING] Record callback start time
    callback_start = perf_counter()
    logger.info(f"[⏱️ TIMING] VLM callback started - username={username}, frame_id={frame_id}")
    logger.info(f"[CALLBACK] *** ASYNC TASK STARTED *** post_to_vlm - username={username}, frame_id={frame_id}, procedure={procedure_id}, step_id={step_def.get('id')}")
    try:
        # Import state machine here to avoid circular import
        from app.api.procedure import machine
        
        # Retrieve frame bytes from storage
        logger.debug(f"[CALLBACK] Retrieving frame from storage - frame_id={frame_id}")
        from app.core.frame_store import get_store_size
        logger.info(f"[CALLBACK] *** FRAME STORE STATE *** - username={username}, frame_id={frame_id}, store_size={get_store_size()}")
        frame_bytes = get_frame(frame_id)
        if not frame_bytes:
            logger.error(f"[CALLBACK] *** CRITICAL: Frame not found in storage *** - username={username}, frame_id={frame_id}, store_size={get_store_size()}")
            logger.error(f"[CALLBACK] This likely means the frame was already processed and cleared, but still exists in user's buffer")
            # Mark inflight as False so system can continue
            machine_user = machine._users.get(username)
            if machine_user:
                logger.info(f"[CALLBACK] Clearing inflight flag for user - username={username}")
                machine_user.inflight = False
                machine_user.inflight_since_ms = None
                machine_user.inflight_frame_id = None
            return
        logger.debug(f"[CALLBACK] Frame retrieved successfully - frame_id={frame_id}, size={len(frame_bytes)} bytes")
        
        # Extract question and negatives from step definition
        question = step_def["positives"][0]
        negatives = step_def["negatives"]
        logger.info(f"[CALLBACK] VLM request params - question='{question}', negatives={negatives}")
        
        # Send to VLM /qa endpoint (synchronous response)
        logger.info(f"[CALLBACK] *** SENDING TO VLM /qa *** - frame_id={frame_id}, vlm_url={settings.VLM_URL}")
        response_json = await post_to_vlm_multipart(
            file_bytes=frame_bytes,
            question=question,
            negatives=negatives,
            vlm_url=settings.VLM_URL
        )
        logger.info(f"[CALLBACK] *** VLM RESPONSE RECEIVED *** - frame_id={frame_id}")
        logger.info(f"[CALLBACK] *** RAW RESPONSE *** - response_json={response_json}, type={type(response_json)}")
        logger.debug(f"[CALLBACK] Response data: {response_json}")
        
        # Parse the response structure - handle both nested and flat formats
        # Try nested format first: {"data": {"result": "yes"}}
        data = response_json.get("data") if isinstance(response_json, dict) else None
        if data and isinstance(data, dict):
            result = data.get("result")
            neg_result = data.get("negative_result")
            logger.info(f"[CALLBACK] *** USING NESTED FORMAT *** - data={data}")
        else:
            # Fall back to flat format: {"result": "yes"}
            result = response_json.get("result") if isinstance(response_json, dict) else None
            neg_result = response_json.get("negative_result") if isinstance(response_json, dict) else None
            logger.info(f"[CALLBACK] *** USING FLAT FORMAT *** - result={result}, neg_result={neg_result}")
        
        logger.info(f"[CALLBACK] *** EXTRACTED FIELDS *** - result={result}, negative_result={neg_result}, result_type={type(result)}")
        
        # Convert "yes"/"no" to Decision enum with robust string handling
        if result is None:
            logger.warning(f"[CALLBACK] Result is None, using default Decision.NO")
            decision = Decision.NO
        elif isinstance(result, str):
            result_clean = result.lower().strip()
            if result_clean in ("yes", "true", "1"):
                decision = Decision.YES
                logger.info(f"[CALLBACK] ✓ Decision parsed: '{result}' -> YES")
            elif result_clean in ("no", "false", "0"):
                decision = Decision.NO
                logger.info(f"[CALLBACK] Decision parsed: '{result}' -> NO")
            else:
                logger.error(f"[CALLBACK] Unexpected VLM result: '{result}', defaulting to NO")
                decision = Decision.NO
        else:
            logger.error(f"[CALLBACK] Invalid decision type: {type(result)}, value={result}, defaulting to NO")
            decision = Decision.NO
        
        # Pass decision to state machine
        logger.info(f"[CALLBACK] Processing decision - username={username}, frame_id={frame_id}, decision={decision.value}")
        machine.vlm_decision(username, frame_id, decision)
        
        # [TIMING] Calculate total callback duration
        callback_end = perf_counter()
        callback_duration = (callback_end - callback_start) * 1000  # Convert to ms
        logger.info(f"[⏱️ TIMING] VLM callback completed - username={username}, frame_id={frame_id}, total_duration={callback_duration:.2f}ms")
        logger.info(f"[CALLBACK] *** VLM PROCESSING COMPLETED *** - frame_id={frame_id}, decision={decision.value}")
        
        # Clear frame from storage after successful processing
        clear_frame(frame_id)
        logger.debug(f"[CALLBACK] Frame cleared from storage - frame_id={frame_id}")
        
    except Exception as e:
        # [TIMING] Log duration even on error
        callback_end = perf_counter()
        callback_duration = (callback_end - callback_start) * 1000
        logger.error(f"[⏱️ TIMING] VLM callback failed - username={username}, frame_id={frame_id}, duration={callback_duration:.2f}ms")
        logger.error(f"[CALLBACK] *** CRITICAL ERROR *** Failed to process VLM response - frame_id={frame_id}, username={username}, error={str(e)}", exc_info=True)


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
    logger.debug(f"[CALLBACK] Task context - frame_id={frame_id}, username={username}, procedure={procedure_id}, step={step_def.get('id')}")
    try:
        task = asyncio.create_task(post_to_vlm_callback(frame_id, procedure_id, step_def, username, idem_key))
        logger.debug(f"[CALLBACK] Async task created successfully - task={task}")
    except Exception as e:
        logger.error(f"[CALLBACK] CRITICAL: Failed to create async task - frame_id={frame_id}, error={str(e)}", exc_info=True)