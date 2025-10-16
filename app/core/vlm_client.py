"""VLM client for multipart HTTP requests."""
import json
import logging
import httpx
from typing import Dict, Optional, Tuple
from time import perf_counter

logger = logging.getLogger(__name__)

# ============================================================================
# SINGLETON HTTP CLIENT
# A single persistent httpx.AsyncClient for all VLM requests to enable
# connection pooling and eliminate per-request connection overhead.
# ============================================================================
_http_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    """
    Get the singleton HTTP client instance.
    
    Returns:
        The initialized httpx.AsyncClient singleton
        
    Raises:
        RuntimeError: If client has not been initialized via init_http_client()
    """
    if _http_client is None:
        raise RuntimeError(
            "HTTP client not initialized. Call init_http_client() during startup."
        )
    return _http_client


async def init_http_client() -> None:
    """
    Initialize the singleton HTTP client with optimal settings for VLM requests.
    
    Configuration:
    - Timeout: 2.5 seconds (aligned with state machine VLM timeout)
    - Max connections: 20
    - Max keepalive connections: 10
    - Keepalive expiry: 60 seconds
    
    Should be called once during application startup.
    """
    global _http_client
    
    if _http_client is not None:
        logger.warning("HTTP client already initialized, skipping re-initialization")
        return
    
    from app.config import (
        HTTP_TIMEOUT,
        HTTP_MAX_CONNECTIONS,
        HTTP_MAX_KEEPALIVE_CONNECTIONS,
        HTTP_KEEPALIVE_EXPIRY
    )
    
    # Configure timeout
    timeout = httpx.Timeout(HTTP_TIMEOUT)
    
    # Configure connection pooling
    limits = httpx.Limits(
        max_connections=HTTP_MAX_CONNECTIONS,
        max_keepalive_connections=HTTP_MAX_KEEPALIVE_CONNECTIONS,
        keepalive_expiry=HTTP_KEEPALIVE_EXPIRY
    )
    
    _http_client = httpx.AsyncClient(timeout=timeout, limits=limits)
    
    logger.info(
        f"[HTTP_CLIENT] Singleton client initialized - "
        f"timeout={HTTP_TIMEOUT}s, "
        f"max_connections={HTTP_MAX_CONNECTIONS}, "
        f"max_keepalive={HTTP_MAX_KEEPALIVE_CONNECTIONS}, "
        f"keepalive_expiry={HTTP_KEEPALIVE_EXPIRY}s"
    )


async def close_http_client() -> None:
    """
    Close and cleanup the singleton HTTP client.
    
    Should be called once during application shutdown to properly
    release resources and close persistent connections.
    """
    global _http_client
    
    if _http_client is None:
        logger.debug("HTTP client not initialized, nothing to close")
        return
    
    logger.info("[HTTP_CLIENT] Closing singleton client...")
    await _http_client.aclose()
    _http_client = None
    logger.info("[HTTP_CLIENT] Singleton client closed successfully")


async def post_to_vlm_multipart(
    file_bytes: bytes,
    question: str,
    negatives: list[str],
    vlm_url: str
) -> Tuple[Dict, float, Optional[float]]:
    """
    Send multipart request to VLM /qa endpoint.
    
    Sends synchronous request to /qa endpoint:
    - file: image bytes with filename and content-type
    - question: first positive question from step
    - negative_questions: JSON stringified array of negatives (optional)
    
    Args:
        file_bytes: Image file bytes
        question: The question to ask (step.positives[0])
        negatives: List of negative questions (step.negatives)
        vlm_url: Base URL of VLM service
        
    Returns:
        Tuple of (response_json, http_post_ms, server_proc_ms)
        - response_json: Response JSON from VLM service containing the answer
        - http_post_ms: HTTP request duration in milliseconds
        - server_proc_ms: VLM server processing time in milliseconds (if available)
    """
    logger.info(f"[VLM_CLIENT] Sending request to VLM - url={vlm_url}/qa")
    logger.debug(f"[VLM_CLIENT] Request details - question={question}, negatives_count={len(negatives)}, file_size={len(file_bytes)} bytes")
    
    # Prepare form data for /qa endpoint
    data = {
        "question": question,
    }
    
    # Add negative questions if provided
    if negatives:
        data["negative_questions"] = json.dumps(negatives)
        logger.debug(f"[VLM_CLIENT] Form data prepared with negatives={negatives}")
    else:
        logger.debug(f"[VLM_CLIENT] Form data prepared without negatives")
    
    # Prepare file upload
    files = {
        "file": ("image.jpg", file_bytes, "image/jpeg")
    }
    logger.debug(f"[VLM_CLIENT] File prepared - filename=image.jpg, content_type=image/jpeg")
    
    # Send POST request to /qa endpoint using singleton client
    try:
        # Get singleton client
        client = get_http_client()
        
        # [TIMING] Record HTTP request start time
        request_start = perf_counter()
        logger.info(f"[⏱️ TIMING] Sending HTTP request to VLM - url={vlm_url}/qa")
        
        logger.debug(f"[VLM_CLIENT] Sending POST request to {vlm_url}/qa...")
        response = await client.post(
            f"{vlm_url}/qa",
            data=data,
            files=files
        )
        
        # [TIMING] Record HTTP response time
        request_end = perf_counter()
        http_post_ms = (request_end - request_start) * 1000  # Convert to ms
        
        logger.debug(f"[VLM_CLIENT] Response received - status_code={response.status_code}")
        logger.info(f"[⏱️ TIMING] HTTP response received - duration={http_post_ms:.2f}ms, status={response.status_code}")
        
        response.raise_for_status()
        response_json = response.json()
        
        # Extract server processing time from response headers if available
        server_proc_ms = None
        if 'X-Processing-Time' in response.headers:
            try:
                # Header might be in seconds or milliseconds, try to detect
                header_value = float(response.headers['X-Processing-Time'])
                # If value is very small (< 10), assume it's in seconds and convert to ms
                server_proc_ms = header_value * 1000 if header_value < 10 else header_value
                logger.debug(f"[VLM_CLIENT] Extracted server processing time: {server_proc_ms:.2f}ms")
            except (ValueError, TypeError) as e:
                logger.warning(f"[VLM_CLIENT] Failed to parse X-Processing-Time header: {e}")
        
        # Also check in response body if not in headers
        if server_proc_ms is None and isinstance(response_json, dict):
            # Check for common response field names
            for field in ['processing_time_ms', 'processing_time', 'duration_ms', 'duration']:
                if field in response_json:
                    try:
                        value = float(response_json[field])
                        server_proc_ms = value * 1000 if value < 10 else value
                        logger.debug(f"[VLM_CLIENT] Extracted server processing time from body.{field}: {server_proc_ms:.2f}ms")
                        break
                    except (ValueError, TypeError):
                        pass
        
        logger.info(f"[VLM_CLIENT] Request successful - status={response.status_code}")
        logger.debug(f"[VLM_CLIENT] Response data: {response_json}")
        
        return response_json, http_post_ms, server_proc_ms
    except httpx.HTTPStatusError as e:
        logger.error(f"[VLM_CLIENT] HTTP error - status={e.response.status_code}, message={str(e)}")
        raise
    except httpx.RequestError as e:
        logger.error(f"[VLM_CLIENT] Request failed - error={str(e)}")
        raise
    except Exception as e:
        logger.error(f"[VLM_CLIENT] Unexpected error - error={str(e)}", exc_info=True)
        raise