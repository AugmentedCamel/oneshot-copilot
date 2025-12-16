"""Node Graph AI Client.

Synchronous client for the AI service's step node detection endpoint.
Sends frames and receives prediction vectors.
"""
import logging
import json
from typing import Dict, List

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def dispatch_to_nodegraph_ai(
    frame_bytes: bytes,
    user_id: str,
    frame_id: str,
    procedure_id: str,
    target_classes: List[str]
) -> Dict[str, float]:
    """Send a frame to the AI service for node detection.
    
    This is a SYNCHRONOUS call - we wait for the prediction vector.
    
    Args:
        frame_bytes: JPEG image data
        user_id: User identifier
        frame_id: Unique frame identifier
        procedure_id: Active procedure ID
        target_classes: Classes to check for (e.g., ["door_fully_open", "error_blocked"])
        
    Returns:
        Dict mapping class names to confidence scores (0.0-1.0)
        e.g., {"door_fully_open": 0.92, "error_blocked": 0.01}
    """
    url = f"{settings.AI_NODE_URL}/stepnodedetection"
    
    logger.debug(
        f"[NODEGRAPH_AI] Sending request to {url} for user {user_id}, "
        f"frame {frame_id}, classes={target_classes}"
    )
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Build multipart form data
            files = {
                "file": ("frame.jpg", frame_bytes, "image/jpeg")
            }
            data = {
                "user_id": user_id,
                "frame_id": frame_id,
                "procedure_id": procedure_id,
                "target_classes": json.dumps(target_classes)
            }
            
            response = await client.post(url, files=files, data=data)
            response.raise_for_status()
            
            result = response.json()
            predictions = result.get("predictions", {})
            
            logger.debug(
                f"[NODEGRAPH_AI] Received predictions for {user_id}: {predictions}"
            )
            
            return predictions
            
    except httpx.ConnectError as e:
        logger.error(f"[NODEGRAPH_AI] Connection failed: {e}")
        raise RuntimeError(f"AI service connection failed: {e}")
    except httpx.TimeoutException as e:
        logger.error(f"[NODEGRAPH_AI] Request timed out: {e}")
        raise RuntimeError(f"AI service timeout: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(f"[NODEGRAPH_AI] HTTP error: {e.response.status_code}")
        raise RuntimeError(f"AI service error: {e.response.status_code}")
    except Exception as e:
        logger.error(f"[NODEGRAPH_AI] Unexpected error: {e}")
        raise RuntimeError(f"AI service error: {e}")
