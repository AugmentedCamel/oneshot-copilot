"""Local VLM Strategy implementation."""
import json
import logging
import httpx
from typing import Dict, Optional, Tuple
from time import perf_counter
from datetime import datetime

from app.core.vlm_strategies.base import VLMStrategy
from app.config import VLM_DEBUG_LOG_FILE

logger = logging.getLogger(__name__)
vlm_response_logger = logging.getLogger("app.api.vlm_callback")


def _to_bool(val):
    """
    Normalize various value types to boolean.
    Accepts True/False, 'yes'/'no', 'y'/'n', 'true'/'false', '1'/'0'.
    Anything unrecognized -> False by default.
    """
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    s = str(val).strip().lower()
    if s in {"yes", "y", "true", "1"}:
        return True
    if s in {"no", "n", "false", "0"}:
        return False
    return False


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
        negatives: list[str],
        bounding_questions: list[str] = None,
        debug: bool = False
    ) -> Tuple[Dict, float, Optional[float]]:
        """
        Send multipart request to LOCAL VLM /analyze endpoint.
        
        Sends synchronous request to /analyze endpoint:
        - file: image bytes with filename and content-type
        - question: first positive question from step
        - negative_questions: JSON stringified array of negatives (optional)
        - bounding_questions: JSON stringified array of items to detect (optional)
        
        Args:
            file_bytes: Image file bytes
            question: The question to ask (step.positives[0])
            negatives: List of negative questions (step.negatives)
            bounding_questions: List of items to detect bounding boxes for (step.bounding_questions)
            debug: Enable debug logging to file (optional)
            
        Returns:
            Tuple of (response_json, http_post_ms, server_proc_ms)
        """
        if debug:
            logger.info(f"[LOCAL_VLM] DEBUG MODE ENABLED - responses will be logged to {VLM_DEBUG_LOG_FILE}")
        from app.core.vlm_client import get_http_client
        
        logger.info(f"[LOCAL_VLM] Sending request to VLM - url={self.vlm_url}/analyze")
        logger.debug(f"[LOCAL_VLM] Request details - question={question}, negatives_count={len(negatives)}, file_size={len(file_bytes)} bytes")
        
        # Prepare form data for /analyze endpoint
        data = {
            "question": question,
        }
        
        # Add negative questions if provided
        if negatives:
            data["negative_questions"] = json.dumps(negatives)
            logger.debug(f"[LOCAL_VLM] Form data prepared with negatives={negatives}")
            # Emit a minimal-log friendly line so we can verify negatives are being sent
            vlm_response_logger.info(f"[VLM_RESPONSE] [REQUEST] negatives_count={len(negatives)}")
        else:
            logger.debug(f"[LOCAL_VLM] Form data prepared without negatives")
            # Emit a minimal-log friendly line so we can verify no negatives are being sent
            vlm_response_logger.info(f"[VLM_RESPONSE] [REQUEST] negatives_count=0")
        
        # Add bounding questions if provided
        if bounding_questions:
            data["bounding_questions"] = json.dumps(bounding_questions)
            logger.debug(f"[LOCAL_VLM] Form data prepared with bounding_questions={bounding_questions}")
            vlm_response_logger.info(f"[VLM_RESPONSE] [REQUEST] bounding_questions_count={len(bounding_questions)}")
        else:
            logger.debug(f"[LOCAL_VLM] Form data prepared without bounding_questions")
            vlm_response_logger.info(f"[VLM_RESPONSE] [REQUEST] bounding_questions_count=0")
        
        # Prepare file upload
        files = {
            "file": ("image.jpg", file_bytes, "image/jpeg")
        }
        logger.debug(f"[LOCAL_VLM] File prepared - filename=image.jpg, content_type=image/jpeg")
        
        # Send POST request to /analyze endpoint using singleton client
        try:
            # Get singleton client
            client = get_http_client()
            
            # [TIMING] Record HTTP request start time
            request_start = perf_counter()
            logger.info(f"[⏱️ TIMING] Sending HTTP request to LOCAL VLM - url={self.vlm_url}/analyze")
            
            logger.debug(f"[LOCAL_VLM] Sending POST request to {self.vlm_url}/analyze...")
            response = await client.post(
                f"{self.vlm_url}/analyze",
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
            
            # === NEGATIVE QUESTION DECISION LOGIC ===
            # Extract positive result
            positive_raw = response_json.get("result") or response_json.get("answer", "")
            positive_is_yes = _to_bool(positive_raw)
            
            # Extract negatives (can be dict or list)
            neg_block = response_json.get("negative_results") or response_json.get("negatives")
            
            neg_values = []
            if isinstance(neg_block, dict):
                neg_values = list(neg_block.values())
            elif isinstance(neg_block, list):
                # Handle list of dictionaries (extract 'result' field) or simple values
                neg_values = [
                    item.get('result', item) if isinstance(item, dict) else item
                    for item in neg_block
                ]
            elif neg_block is None:
                neg_values = []
            else:
                # Unexpected shape: treat as a single value
                neg_values = [neg_block]
            
            # Any negative marked YES?
            any_negative_yes = any(_to_bool(v) for v in neg_values)
            
            # Final decision rule: YES only if positive YES AND no negatives YES
            final_yes = bool(positive_is_yes and not any_negative_yes)
            final_str = "YES" if final_yes else "NO"
            
            # Add final decision to response
            response_json["final"] = final_str
            
            # Log the decision
            logger.info(f"[LOCAL_VLM] Final decision: {final_str} (positive={positive_is_yes}, any_negative_yes={any_negative_yes})")
            # === END NEGATIVE QUESTION DECISION LOGIC ===
            
            # Log the VLM response content for debugging
            # Extract result field (could be "result", "answer", or other field names)
            result = response_json.get("result") or response_json.get("answer", "")
            if result:
                logger.debug(f"[LOCAL_VLM] Question asked: {question}")
                logger.debug(f"[LOCAL_VLM] VLM result: {result[:200]}{'...' if len(result) > 200 else ''}")
                vlm_response_logger.info(f"[VLM_RESPONSE] Positive: {question}: {result}")
            
            # Log negative question responses if present
            negative_results = response_json.get("negative_results") or response_json.get("negatives")
            if negative_results:
                logger.debug(f"[LOCAL_VLM] Negative questions included: {len(negatives)} question(s)")
                if isinstance(negative_results, dict):
                    for neg_q, neg_result in negative_results.items():
                        neg_preview = neg_result[:200] if isinstance(neg_result, str) else str(neg_result)[:200]
                        logger.debug(f"[LOCAL_VLM] Negative result for '{neg_q}': {neg_preview}{'...' if len(str(neg_result)) > 200 else ''}")
                        vlm_response_logger.info(f"[VLM_RESPONSE] Negative: {neg_q}: {neg_result}")
                elif isinstance(negative_results, list):
                    for idx, neg_result in enumerate(negative_results):
                        neg_preview = neg_result[:200] if isinstance(neg_result, str) else str(neg_result)[:200]
                        logger.debug(f"[LOCAL_VLM] Negative result {idx}: {neg_preview}{'...' if len(str(neg_result)) > 200 else ''}")
                        try:
                            neg_q_text = negatives[idx] if idx < len(negatives) else f"negative[{idx}]"
                        except Exception:
                            neg_q_text = f"negative[{idx}]"
                        vlm_response_logger.info(f"[VLM_RESPONSE] Negative: {neg_q_text}: {neg_result}")
            
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
            
            # Log successful response with key details
            result_preview = ""
            result = response_json.get("result") or response_json.get("answer", "")
            if result:
                result_preview = f", result_length={len(result)}"
            negative_count = ""
            negative_results = response_json.get("negative_results") or response_json.get("negatives")
            if negative_results:
                neg_len = len(negative_results) if isinstance(negative_results, (list, dict)) else 0
                negative_count = f", negative_results={neg_len}"
            
            logger.info(f"[LOCAL_VLM] Request successful - status={response.status_code}{result_preview}{negative_count}")
            logger.debug(f"[LOCAL_VLM] Raw response data: {response_json}")
            
            # [DEBUG] Write debug information to file if debug mode is enabled
            if debug:
                self._write_debug_log(
                    question=question,
                    negatives=negatives,
                    bounding_questions=bounding_questions,
                    response_json=response_json,
                    http_post_ms=http_post_ms,
                    server_proc_ms=server_proc_ms,
                    status_code=response.status_code
                )
            
            # Construct standardized response envelope
            envelope = {
                "data": {
                    "result": result,
                    "final": final_str,
                    "decision": final_str,  # Alias for compatibility
                    "bounding_boxes": response_json.get("bounding_results", []),
                    "metadata": {
                        "negative_results": negative_results,
                        "server_processing_time_ms": server_proc_ms
                    }
                },
                "raw": response_json
            }
            
            return envelope, http_post_ms, server_proc_ms
        except httpx.HTTPStatusError as e:
            logger.error(f"[LOCAL_VLM] HTTP error - status={e.response.status_code}, message={str(e)}")
            raise
        except httpx.RequestError as e:
            logger.error(f"[LOCAL_VLM] Request failed - error={str(e)}")
            raise
        except Exception as e:
            logger.error(f"[LOCAL_VLM] Unexpected error - error={str(e)}", exc_info=True)
            raise
    
    def _write_debug_log(
        self,
        question: str,
        negatives: list[str],
        bounding_questions: list[str],
        response_json: Dict,
        http_post_ms: float,
        server_proc_ms: Optional[float],
        status_code: int
    ) -> None:
        """
        Write debug information to log file.
        
        Args:
            question: The positive question asked
            negatives: List of negative questions
            bounding_questions: List of bounding box questions
            response_json: Raw VLM response JSON
            http_post_ms: HTTP request duration in milliseconds
            server_proc_ms: VLM server processing time in milliseconds (if available)
            status_code: HTTP status code
        """
        try:
            timestamp = datetime.utcnow().isoformat() + "Z"
            
            debug_entry = {
                "timestamp": timestamp,
                "request": {
                    "question": question,
                    "negative_questions": negatives,
                    "bounding_questions": bounding_questions if bounding_questions else []
                },
                "response": {
                    "status_code": status_code,
                    "raw_json": response_json,
                    "http_post_ms": http_post_ms,
                    "server_proc_ms": server_proc_ms
                }
            }
            
            # Append to debug log file
            with open(VLM_DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(debug_entry, indent=2))
                f.write("\n" + "="*80 + "\n")
            
            logger.info(f"[LOCAL_VLM] Debug entry written to {VLM_DEBUG_LOG_FILE}")
            
        except Exception as e:
            logger.error(f"[LOCAL_VLM] Failed to write debug log: {str(e)}", exc_info=True)
    
    @property
    def name(self) -> str:
        """Return the name of this VLM strategy."""
        return "Local VLM"