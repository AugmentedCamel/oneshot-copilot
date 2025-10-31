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
from app.core.metrics import get_metrics_collector, TimingMetrics

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
    logger.info(f"[CALLBACK] *** ON_STEP TRIGGERED *** username={username}, procedure={procedure_id}, step_id={step_id}, step_name='{step_name}'")
    try:
        url = f"{settings.MENTRA_URL}/on_step"
        payload = {
            "username": username,
            "text": step_name
        }
        logger.info(f"[CALLBACK] Sending POST to {url}")
        logger.info(f"[CALLBACK] Payload: {payload}")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            logger.info(f"[CALLBACK] *** ON_STEP RESPONSE *** status={response.status_code}, body={response.text[:200]}")
            
            if response.status_code != 200:
                logger.warning(f"[CALLBACK] Non-200 response from on_step - status={response.status_code}, body={response.text}")
    except Exception as e:
        logger.error(f"[CALLBACK] *** ON_STEP FAILED *** username={username}, error={str(e)}", exc_info=True)


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
        
        # [TIMING] Retrieve frame bytes from storage
        frame_retrieve_start = perf_counter()
        logger.debug(f"[CALLBACK] Retrieving frame from storage - frame_id={frame_id}")
        from app.core.frame_store import get_store_size
        logger.info(f"[CALLBACK] *** FRAME STORE STATE *** - username={username}, frame_id={frame_id}, store_size={get_store_size()}")
        frame_bytes = get_frame(frame_id)
        frame_retrieve_ms = (perf_counter() - frame_retrieve_start) * 1000
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
        logger.info(f"[⏱️ TIMING] Frame retrieval completed - duration={frame_retrieve_ms:.3f}ms")
        
        # [TIMING] Extract question and negatives from step definition
        request_prep_start = perf_counter()
        question = step_def["positives"][0]
        negatives = step_def["negatives"]
        request_prep_ms = (perf_counter() - request_prep_start) * 1000
        logger.info(f"[CALLBACK] VLM request params - question='{question}', negatives={negatives}")
        logger.info(f"[⏱️ TIMING] Request preparation completed - duration={request_prep_ms:.3f}ms")
        
        # [TIMING] Send to VLM /qa endpoint (synchronous response)
        vlm_request_start = perf_counter()
        logger.info(f"[CALLBACK] *** SENDING TO VLM /qa *** - frame_id={frame_id}, vlm_url={settings.VLM_URL}")
        response_json, http_post_ms, server_proc_ms = await post_to_vlm_multipart(
            file_bytes=frame_bytes,
            question=question,
            negatives=negatives,
            vlm_url=settings.VLM_URL
        )
        vlm_request_ms = (perf_counter() - vlm_request_start) * 1000
        logger.info(f"[CALLBACK] *** VLM RESPONSE RECEIVED *** - frame_id={frame_id}, http_post_ms={http_post_ms:.2f}ms")
        logger.info(f"[⏱️ TIMING] Total VLM request time (including parsing) - duration={vlm_request_ms:.2f}ms")
        logger.info(f"[CALLBACK] *** RAW RESPONSE *** - response_json={response_json}, type={type(response_json)}")
        if server_proc_ms is not None:
            logger.info(f"[CALLBACK] Server processing time: {server_proc_ms:.2f}ms")
        logger.debug(f"[CALLBACK] Response data: {response_json}")
        
        # [TIMING] Parse the response structure - handle both nested and flat formats
        response_parse_start = perf_counter()
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
            # Remove surrounding brackets if present (VLM may return [yes] or [no])
            if result_clean.startswith('[') and result_clean.endswith(']'):
                result_clean = result_clean[1:-1].strip()
            
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
        
        response_parse_ms = (perf_counter() - response_parse_start) * 1000
        logger.info(f"[⏱️ TIMING] Response parsing completed - duration={response_parse_ms:.3f}ms")
        
        # [TIMING] Pass decision to state machine
        state_machine_start = perf_counter()
        logger.info(f"[CALLBACK] Processing decision - username={username}, frame_id={frame_id}, decision={decision.value}")
        machine.vlm_decision(username, frame_id, decision)
        state_machine_ms = (perf_counter() - state_machine_start) * 1000
        logger.info(f"[⏱️ TIMING] State machine decision processing - duration={state_machine_ms:.3f}ms")
        
        # [TIMING] Calculate total callback duration and breakdown
        callback_end = perf_counter()
        callback_duration = (callback_end - callback_start) * 1000  # Convert to ms
        
        # [TIMING] Log detailed breakdown
        logger.info(f"[⏱️ TIMING] ========== CALLBACK BREAKDOWN ==========")
        logger.info(f"[⏱️ TIMING] Frame Retrieval:      {frame_retrieve_ms:7.2f}ms")
        logger.info(f"[⏱️ TIMING] Request Preparation:  {request_prep_ms:7.2f}ms")
        logger.info(f"[⏱️ TIMING] HTTP POST (total):    {http_post_ms:7.2f}ms")
        if server_proc_ms is not None:
            logger.info(f"[⏱️ TIMING]   └─ VLM Processing:  {server_proc_ms:7.2f}ms")
            network_overhead = http_post_ms - server_proc_ms
            logger.info(f"[⏱️ TIMING]   └─ Network/Overhead:{network_overhead:7.2f}ms")
        logger.info(f"[⏱️ TIMING] Response Parsing:     {response_parse_ms:7.2f}ms")
        logger.info(f"[⏱️ TIMING] State Machine Update: {state_machine_ms:7.2f}ms")
        logger.info(f"[⏱️ TIMING] TOTAL CALLBACK:       {callback_duration:7.2f}ms")
        logger.info(f"[⏱️ TIMING] ==========================================")
        
        # [METRICS] Collect and record all timing metrics
        try:
            # Get queue wait time from vlm_worker module
            from app.core.vlm_worker import _frame_queue_timings
            queue_wait_ms = _frame_queue_timings.pop(frame_id, None)
            
            # Calculate total time
            total_ms = callback_duration
            
            # Create timing metrics object
            metrics = TimingMetrics(
                queue_wait_ms=queue_wait_ms,
                http_post_ms=http_post_ms,
                server_proc_ms=server_proc_ms,
                total_ms=total_ms
            )
            
            # Record and log metrics
            metrics_collector = get_metrics_collector()
            metrics_collector.record_timing(username, metrics)
            metrics_collector.log_metrics(metrics, username)
            
            logger.info(f"[⏱️ TIMING] VLM callback completed - username={username}, frame_id={frame_id}, total_duration={callback_duration:.2f}ms")
            
            # [TIMING] Calculate and log END-TO-END timing from ingestion to completion
            try:
                from app.api.procedure import machine
                machine_user = machine._users.get(username)
                if machine_user and machine_user.frame_ingest_time:
                    total_end_to_end = (callback_end - machine_user.frame_ingest_time) * 1000
                    
                    # Calculate component times
                    if queue_wait_ms and machine_user.vlm_dispatch_time:
                        ingest_to_dequeue = queue_wait_ms
                        dequeue_to_dispatch = (machine_user.vlm_dispatch_time - (machine_user.frame_ingest_time + queue_wait_ms / 1000)) * 1000
                        dispatch_to_response = http_post_ms if http_post_ms else 0
                        response_to_completion = callback_duration - (frame_retrieve_ms + request_prep_ms + http_post_ms + response_parse_ms + state_machine_ms)
                        
                        logger.info(f"[⏱️ TIMING] ========================================")
                        logger.info(f"[⏱️ TIMING] *** END-TO-END PIPELINE TIMING ***")
                        logger.info(f"[⏱️ TIMING] ========================================")
                        logger.info(f"[⏱️ TIMING] 1. Ingest → Queue Dequeue:  {ingest_to_dequeue:7.2f}ms (Queue Wait)")
                        logger.info(f"[⏱️ TIMING] 2. Dequeue → VLM Dispatch:   {dequeue_to_dispatch:7.2f}ms (State Machine)")
                        logger.info(f"[⏱️ TIMING] 3. VLM Dispatch → Response:  {dispatch_to_response:7.2f}ms (HTTP + VLM)")
                        if server_proc_ms:
                            logger.info(f"[⏱️ TIMING]    └─ VLM Processing:      {server_proc_ms:7.2f}ms")
                            logger.info(f"[⏱️ TIMING]    └─ Network Overhead:    {dispatch_to_response - server_proc_ms:7.2f}ms")
                        logger.info(f"[⏱️ TIMING] 4. Response → Completion:   {response_to_completion:7.2f}ms (Callback)")
                        logger.info(f"[⏱️ TIMING] ----------------------------------------")
                        logger.info(f"[⏱️ TIMING] TOTAL PIPELINE TIME:        {total_end_to_end:7.2f}ms")
                        logger.info(f"[⏱️ TIMING] ========================================")
                        
                        # Calculate overhead (non-VLM time)
                        vlm_time = server_proc_ms if server_proc_ms else dispatch_to_response
                        overhead_time = total_end_to_end - vlm_time
                        overhead_pct = (overhead_time / total_end_to_end * 100) if total_end_to_end > 0 else 0
                        logger.info(f"[⏱️ TIMING] VLM Processing Time:        {vlm_time:7.2f}ms ({vlm_time/total_end_to_end*100:.1f}%)")
                        logger.info(f"[⏱️ TIMING] Pipeline Overhead:          {overhead_time:7.2f}ms ({overhead_pct:.1f}%)")
                        logger.info(f"[⏱️ TIMING] ========================================")
            except Exception as e:
                logger.error(f"[TIMING] Failed to calculate end-to-end timing: {str(e)}", exc_info=True)
        except Exception as e:
            logger.error(f"[METRICS] Failed to collect/record metrics: {str(e)}", exc_info=True)
        
        logger.info(f"[CALLBACK] *** VLM PROCESSING COMPLETED *** - frame_id={frame_id}, decision={decision.value}")
        
        # [TIMING] Clear frame from storage after successful processing
        frame_clear_start = perf_counter()
        clear_frame(frame_id)
        frame_clear_ms = (perf_counter() - frame_clear_start) * 1000
        logger.info(f"[⏱️ TIMING] Frame cleared from storage - duration={frame_clear_ms:.3f}ms")
        
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