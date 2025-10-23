"""Local VLM Strategy implementation."""
import json
import logging
import httpx
from typing import Dict, Optional, Tuple
from time import perf_counter

from app.core.vlm_strategies.base import VLMStrategy

logger = logging.getLogger(__name__)


class LocalVLMStrategy(VLMStrategy):
    """Strategy for local VLM service."""
    
    def __init__(self, vlm_url: str):
        """
        Initialize Local VLM strategy.
        
        Args:
            vlm_url: Base URL of the local VLM service
        """
        self.vlm_url = vlm_url
    
    async def query(
        self,
        file_bytes: bytes,
        question: str,
        negatives: list[str]
    ) -> Tuple[Dict, float, Optional[float]]:
        """
        Send multipart request to LOCAL VLM /qa endpoint.
        
        Sends synchronous request to /qa endpoint:
        - file: image bytes with filename and content-type
        - question: first positive question from step
        - negative_questions: JSON stringified array of negatives (optional)
        
        Args:
            file_bytes: Image file bytes
            question: The question to ask (step.positives[0])
            negatives: List of negative questions (step.negatives)
            
        Returns:
            Tuple of (response_json, http_post_ms, server_proc_ms)
        """
        from app.core.vlm_client import get_http_client
        
        logger.info(f"[LOCAL_VLM] Sending request to VLM - url={self.vlm_url}/qa")
        logger.debug(f"[LOCAL_VLM] Request details - question={question}, negatives_count={len(negatives)}, file_size={len(file_bytes)} bytes")
        
        # Prepare form data for /qa endpoint
        data = {
            "question": question,
        }
        
        # Add negative questions if provided
        if negatives:
            data["negative_questions"] = json.dumps(negatives)
            logger.debug(f"[LOCAL_VLM] Form data prepared with negatives={negatives}")
        else:
            logger.debug(f"[LOCAL_VLM] Form data prepared without negatives")
        
        # Prepare file upload
        files = {
            "file": ("image.jpg", file_bytes, "image/jpeg")
        }
        logger.debug(f"[LOCAL_VLM] File prepared - filename=image.jpg, content_type=image/jpeg")
        
        # Send POST request to /qa endpoint using singleton client
        try:
            # Get singleton client
            client = get_http_client()
            
            # [TIMING] Record HTTP request start time
            request_start = perf_counter()
            logger.info(f"[⏱️ TIMING] Sending HTTP request to LOCAL VLM - url={self.vlm_url}/qa")
            
            logger.debug(f"[LOCAL_VLM] Sending POST request to {self.vlm_url}/qa...")
            response = await client.post(
                f"{self.vlm_url}/qa",
                data=data,
                files=files
            )
            
            # [TIMING] Record HTTP response time
            request_end = perf_counter()
            http_post_ms = (request_end - request_start) * 1000  # Convert to ms
            
            logger.debug(f"[LOCAL_VLM] Response received - status_code={response.status_code}")
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
                    logger.debug(f"[LOCAL_VLM] Extracted server processing time: {server_proc_ms:.2f}ms")
                except (ValueError, TypeError) as e:
                    logger.warning(f"[LOCAL_VLM] Failed to parse X-Processing-Time header: {e}")
            
            # Also check in response body if not in headers
            if server_proc_ms is None and isinstance(response_json, dict):
                # Check for common response field names
                for field in ['processing_time_ms', 'processing_time', 'duration_ms', 'duration']:
                    if field in response_json:
                        try:
                            value = float(response_json[field])
                            server_proc_ms = value * 1000 if value < 10 else value
                            logger.debug(f"[LOCAL_VLM] Extracted server processing time from body.{field}: {server_proc_ms:.2f}ms")
                            break
                        except (ValueError, TypeError):
                            pass
            
            logger.info(f"[LOCAL_VLM] Request successful - status={response.status_code}")
            logger.debug(f"[LOCAL_VLM] Response data: {response_json}")
            
            return response_json, http_post_ms, server_proc_ms
        except httpx.HTTPStatusError as e:
            logger.error(f"[LOCAL_VLM] HTTP error - status={e.response.status_code}, message={str(e)}")
            raise
        except httpx.RequestError as e:
            logger.error(f"[LOCAL_VLM] Request failed - error={str(e)}")
            raise
        except Exception as e:
            logger.error(f"[LOCAL_VLM] Unexpected error - error={str(e)}", exc_info=True)
            raise
    
    @property
    def name(self) -> str:
        """Return the name of this VLM strategy."""
        return "Local VLM"