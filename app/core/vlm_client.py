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
    vlm_url: str
) -> Dict:
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
        Response JSON from VLM service containing the answer
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
    
    # Send POST request to /qa endpoint (synchronous response)
    try:
        logger.debug(f"[VLM_CLIENT] Opening HTTP client connection...")
        async with httpx.AsyncClient(timeout=30.0) as client:
            logger.debug(f"[VLM_CLIENT] Sending POST request to {vlm_url}/qa...")
            response = await client.post(
                f"{vlm_url}/qa",
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