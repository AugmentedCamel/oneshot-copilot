"""AI Node client for async reasoning dispatch."""
import logging
import json
from typing import Dict, Optional, Any
from dataclasses import asdict

import httpx

from app.config import settings
from app.domain.models import ReasoningConfig
from app.core.vlm_client import get_http_client

logger = logging.getLogger(__name__)


async def dispatch_to_ai_node(
    frame_bytes: bytes,
    metadata: Dict[str, str],
    reasoning_config: ReasoningConfig
) -> bool:
    """
    Fire-and-forget dispatch to ai_node.
    
    Sends a frame along with reasoning configuration to the ai_node for async processing.
    Does NOT wait for the reasoning result - that comes via callback.
    
    Args:
        frame_bytes: The image frame as bytes
        metadata: Dict containing username, session_id, frame_id
        reasoning_config: The reasoning configuration for this step
        
    Returns:
        True if dispatch was accepted (202), False otherwise
    """
    try:
        client = get_http_client()
        
        # Serialize reasoning_config to dict
        step_context = asdict(reasoning_config)
        
        # Build multipart form data
        files = {
            "file": ("frame.jpg", frame_bytes, "image/jpeg")
        }
        data = {
            "step_context": json.dumps(step_context),
            "metadata": json.dumps(metadata)
        }
        
        url = f"{settings.AI_NODE_URL}/analyze"
        
        # === DEBUG: Log exactly what we're sending ===
        logger.info(f"[AI_NODE] ========== REQUEST DEBUG ==========")
        logger.info(f"[AI_NODE] URL: {url}")
        logger.info(f"[AI_NODE] File: name='frame.jpg', size={len(frame_bytes)} bytes, content_type='image/jpeg'")
        logger.info(f"[AI_NODE] Form field 'step_context': {data['step_context']}")
        logger.info(f"[AI_NODE] Form field 'metadata': {data['metadata']}")
        logger.info(f"[AI_NODE] ======================================")
        
        logger.debug(f"[AI_NODE] Dispatching to {url} for user {metadata.get('username')}")
        
        # Fire-and-forget: we only care about 202 Accepted
        response = await client.post(url, files=files, data=data)
        
        if response.status_code == 202:
            logger.info(f"[AI_NODE] Frame dispatched successfully for {metadata.get('username')}")
            return True
        else:
            logger.warning(f"[AI_NODE] Unexpected status code: {response.status_code}")
            return False
            
    except httpx.ConnectError as e:
        logger.error(f"[AI_NODE] Connection failed: {e}")
        return False
    except httpx.TimeoutException as e:
        logger.warning(f"[AI_NODE] Request timed out: {e}")
        return False
    except Exception as e:
        logger.error(f"[AI_NODE] Dispatch failed: {e}")
        return False


def is_reasoning_mode() -> bool:
    """Check if we're in async reasoning mode (vs legacy sync VLM)."""
    return settings.VLM_STRATEGY.lower() == "reasoning"
