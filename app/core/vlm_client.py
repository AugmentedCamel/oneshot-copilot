"""VLM client for multipart HTTP requests."""
import json
import httpx
from typing import Dict


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
    # Prepare form data - exact format as JavaScript
    data = {
        "question": question,
        "negative_questions": json.dumps(negatives),
        "webhook_url": webhook_url,
    }
    
    # Prepare file upload - matches JavaScript fileBuffer format
    files = {
        "file": ("image.jpg", file_bytes, "image/jpeg")
    }
    
    # Send POST request to /analyze_async endpoint
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{vlm_url}/analyze_async",
            data=data,
            files=files
        )
        response.raise_for_status()
        return response.json()