"""VLM client for multipart HTTP requests."""
import json
import logging
import httpx
from typing import Dict

logger = logging.getLogger(__name__)


async def post_to_vlm_multipart(
    file_bytes: bytes,
    question: str,
    negatives: list[str],
    webhook_url: str,
    vlm_url: str
) -> Dict:
    """
    Send multipart request to VLM service.
    
    This matches the exact format from the JavaScript reference:
    - file: image bytes with filename and content-type
    - question: first positive question from step
    - negative_questions: JSON stringified array of negatives
    - webhook_url: callback URL with query parameters
    
    Args:
        file_bytes: Image file bytes
        question: The question to ask (step.positives[0])
        negatives: List of negative questions (step.negatives)
        webhook_url: Full webhook URL with query params
        vlm_url: Base URL of VLM service
        
    Returns:
        Response JSON from VLM service
    """
    logger.info(f"[VLM_CLIENT] Sending request to VLM - url={vlm_url}/analyze_async")
    logger.debug(f"[VLM_CLIENT] Request details - question={question}, negatives_count={len(negatives)}, file_size={len(file_bytes)} bytes")
    logger.debug(f"[VLM_CLIENT] Webhook URL: {webhook_url}")
    
    # Prepare form data - exact format as JavaScript
    data = {
        "question": question,
        "negative_questions": json.dumps(negatives),
        "webhook_url": webhook_url,
    }
    logger.debug(f"[VLM_CLIENT] Form data prepared - negatives={negatives}")
    
    # Prepare file upload - matches JavaScript fileBuffer format
    files = {
        "file": ("image.jpg", file_bytes, "image/jpeg")
    }
    logger.debug(f"[VLM_CLIENT] File prepared - filename=image.jpg, content_type=image/jpeg")
    
    # Send POST request to /analyze_async endpoint
    try:
        logger.debug(f"[VLM_CLIENT] Opening HTTP client connection...")
        async with httpx.AsyncClient(timeout=30.0) as client:
            logger.debug(f"[VLM_CLIENT] Sending POST request to {vlm_url}/analyze_async...")
            response = await client.post(
                f"{vlm_url}/analyze_async",
                data=data,
                files=files
            )
            logger.debug(f"[VLM_CLIENT] Response received - status_code={response.status_code}")
            response.raise_for_status()
            response_json = response.json()
            logger.info(f"[VLM_CLIENT] Request successful - status={response.status_code}")
            logger.debug(f"[VLM_CLIENT] Response data: {response_json}")
            return response_json
    except httpx.HTTPStatusError as e:
        logger.error(f"[VLM_CLIENT] HTTP error - status={e.response.status_code}, message={str(e)}")
        raise
    except httpx.RequestError as e:
        logger.error(f"[VLM_CLIENT] Request failed - error={str(e)}")
        raise
    except Exception as e:
        logger.error(f"[VLM_CLIENT] Unexpected error - error={str(e)}", exc_info=True)
        raise