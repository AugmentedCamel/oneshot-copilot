"""Moondream AI Cloud VLM Strategy implementation."""
import logging
import httpx
from typing import Dict, Optional, Tuple
from time import perf_counter

from app.core.vlm_strategies.base import VLMStrategy

logger = logging.getLogger(__name__)


class MoondreamVLMStrategy(VLMStrategy):
    """Strategy for Moondream AI cloud VLM service."""
    
    def __init__(self, api_key: str):
        """
        Initialize Moondream AI VLM strategy.
        
        Args:
            api_key: Moondream API key for authentication
        """
        self.api_key = api_key
        self.base_url = "https://api.moondream.ai"
    
    async def query(
        self,
        file_bytes: bytes,
        question: str,
        negatives: list[str],
        bounding_questions: list[str] = None,
        debug: bool = False
    ) -> Tuple[Dict, float, Optional[float]]:
        """
        Send request to Moondream AI cloud VLM service.
        
        API Documentation: https://docs.moondream.ai/api
        
        ⚠️ LIMITATION: Moondream AI cloud does not support negative questions or bounding boxes.
        Only the positive question is sent; negatives and bounding_questions parameters are ignored.
        
        Args:
            file_bytes: Image file bytes
            question: The positive question to ask
            negatives: List of negative questions (IGNORED for Moondream AI)
            bounding_questions: List of items to detect bounding boxes for (IGNORED for Moondream AI)
            debug: Enable debug logging to file (IGNORED for Moondream AI - use cloud provider logs)
            
        Returns:
            Tuple of (response_json, http_post_ms, server_proc_ms)
        """
        if debug:
            logger.info("[MOONDREAM] Debug mode requested but not implemented for cloud provider - check Moondream AI dashboard for logs")
        from app.core.vlm_client import get_http_client
        
        if negatives:
            logger.warning(
                f"[MOONDREAM] Moondream AI cloud does not support negative questions. "
                f"Ignoring {len(negatives)} negative question(s). "
                f"Only using positive question: '{question}'"
            )
        
        if bounding_questions:
            logger.warning(
                f"[MOONDREAM] Moondream AI cloud does not support bounding box detection. "
                f"Ignoring {len(bounding_questions)} bounding question(s). "
                f"Only using positive question: '{question}'"
            )
        
        logger.info(f"[MOONDREAM] Sending request to Moondream AI - url={self.base_url}")
        logger.debug(f"[MOONDREAM] Question: {question}")
        logger.debug(f"[MOONDREAM] Image size: {len(file_bytes)} bytes")
        
        # Prepare multipart form data for Moondream AI
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # Moondream uses multipart form with 'image' and 'question' fields
        files = {
            "image": ("image.jpg", file_bytes, "image/jpeg")
        }
        
        data = {
            "question": question
        }
        
        try:
            client = get_http_client()
            request_start = perf_counter()
            
            logger.info(f"[⏱️ TIMING] Sending HTTP request to Moondream AI")
            
            # Moondream AI endpoint for vision QA
            response = await client.post(
                f"{self.base_url}/v1/query",
                headers=headers,
                files=files,
                data=data
            )
            
            request_end = perf_counter()
            http_post_ms = (request_end - request_start) * 1000
            
            logger.info(
                f"[⏱️ TIMING] Moondream AI response - "
                f"duration={http_post_ms:.2f}ms, status={response.status_code}"
            )
            
            response.raise_for_status()
            response_json = response.json()
            
            logger.debug(f"[MOONDREAM] Raw response: {response_json}")
            
            # Extract answer from Moondream response
            # Moondream typically returns: {"answer": "text response"}
            answer_text = response_json.get("answer", "")
            
            # Normalize to expected format (YES/NO/UNCERTAIN)
            decision = self._normalize_response(answer_text)
            
            logger.info(f"[MOONDREAM] Request successful - decision={decision}")
            
            # Extract processing time if provided in response
            server_proc_ms = None
            if "processing_time" in response_json:
                try:
                    server_proc_ms = float(response_json["processing_time"]) * 1000
                except (ValueError, TypeError):
                    pass
            
            return {"decision": decision}, http_post_ms, server_proc_ms
            
        except httpx.HTTPStatusError as e:
            logger.error(
                f"[MOONDREAM] HTTP error - "
                f"status={e.response.status_code}, "
                f"response={e.response.text}"
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"[MOONDREAM] Request failed - error={str(e)}")
            raise
        except Exception as e:
            logger.error(f"[MOONDREAM] Unexpected error - error={str(e)}", exc_info=True)
            raise
    
    def _normalize_response(self, answer: str) -> str:
        """
        Normalize Moondream AI text response to YES/NO/UNCERTAIN format.
        
        Args:
            answer: Raw text answer from Moondream AI
            
        Returns:
            Normalized decision: "YES", "NO", or "UNCERTAIN"
        """
        if not answer:
            logger.warning("[MOONDREAM] Empty response, returning UNCERTAIN")
            return "UNCERTAIN"
        
        answer_lower = answer.lower().strip()
        
        # Check for affirmative responses
        affirmative_keywords = ["yes", "correct", "true", "affirmative", "indeed", "visible", "present"]
        if any(word in answer_lower for word in affirmative_keywords):
            logger.debug(f"[MOONDREAM] Detected affirmative in: '{answer}'")
            return "YES"
        
        # Check for negative responses
        negative_keywords = ["no", "not", "incorrect", "false", "negative", "absent", "missing"]
        if any(word in answer_lower for word in negative_keywords):
            logger.debug(f"[MOONDREAM] Detected negative in: '{answer}'")
            return "NO"
        
        # If answer is very short and matches exactly
        if answer_lower in ["yes", "y"]:
            return "YES"
        if answer_lower in ["no", "n"]:
            return "NO"
        
        # Default to uncertain for ambiguous responses
        logger.warning(
            f"[MOONDREAM] Unable to clearly parse response: '{answer}', "
            f"returning UNCERTAIN"
        )
        return "UNCERTAIN"
    
    @property
    def name(self) -> str:
        """Return the name of this VLM strategy."""
        return "Moondream AI"