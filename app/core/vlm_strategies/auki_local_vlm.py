"""Auki Local VLM Strategy implementation using WebSocket."""
import json
import logging
import asyncio
import websockets
from typing import Dict, Optional, Tuple
from time import perf_counter
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from app.core.vlm_strategies.base import VLMStrategy

logger = logging.getLogger(__name__)


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


# ============================================================================
# SINGLETON WEBSOCKET CONNECTION
# A single persistent WebSocket connection for all VLM requests to enable
# connection reuse and eliminate per-request connection overhead.
# ============================================================================
_websocket_connection: Optional[websockets.WebSocketServerProtocol] = None
_websocket_url: Optional[str] = None
_websocket_lock = asyncio.Lock()
# Serialize send/recv operations on the shared WebSocket to prevent concurrent recv errors
_websocket_operation_lock = asyncio.Lock()


async def get_websocket_connection(ws_url: str) -> websockets.WebSocketServerProtocol:
    """
    Get the singleton WebSocket connection instance.

    Returns:
        The initialized websockets.WebSocketServerProtocol singleton

    Raises:
        Exception: If connection fails
    """
    global _websocket_connection, _websocket_url

    async with _websocket_lock:
        logger.debug(f"[WEBSOCKET_CLIENT] *** get_websocket_connection called *** - ws_url={ws_url}, existing_connection={_websocket_connection is not None}, existing_url={_websocket_url}")
        
        # If we have a connection to a different URL, close it first
        if _websocket_connection is not None and _websocket_url != ws_url:
            logger.info(f"[WEBSOCKET_CLIENT] URL changed, closing existing connection (old_url={_websocket_url}, new_url={ws_url})")
            try:
                await _websocket_connection.close()
            except Exception as e:
                logger.warning(f"[WEBSOCKET_CLIENT] Error closing old connection: {e}")
            _websocket_connection = None
            _websocket_url = None

        # If no connection exists, create one
        if _websocket_connection is None:
            logger.info(f"[WEBSOCKET_CLIENT] *** CREATING NEW CONNECTION *** - url={ws_url}")
            try:
                _websocket_connection = await websockets.connect(ws_url)
                _websocket_url = ws_url
                logger.info(f"[WEBSOCKET_CLIENT] *** NEW CONNECTION ESTABLISHED *** - connection_id={id(_websocket_connection)}")
            except Exception as e:
                logger.error(f"[WEBSOCKET_CLIENT] WebSocket connection failed: {e}")
                raise

        # Check if connection is still alive
        logger.debug(f"[WEBSOCKET_CLIENT] *** REUSING EXISTING CONNECTION *** - connection_id={id(_websocket_connection)}, checking health...")
        try:
            # Simple ping to check connection health
            await _websocket_connection.ping()
            logger.debug(f"[WEBSOCKET_CLIENT] *** CONNECTION HEALTH CHECK PASSED *** - connection_id={id(_websocket_connection)}")
        except Exception as e:
            logger.warning(f"[WEBSOCKET_CLIENT] Connection health check failed, reconnecting: {e}")
            try:
                if _websocket_connection:
                    await _websocket_connection.close()
            except Exception:
                pass

            _websocket_connection = await websockets.connect(ws_url)
            _websocket_url = ws_url
            logger.info(f"[WEBSOCKET_CLIENT] *** RECONNECTED AFTER HEALTH CHECK FAILURE *** - url={ws_url}, connection_id={id(_websocket_connection)}")

        logger.debug(f"[WEBSOCKET_CLIENT] *** RETURNING CONNECTION *** - connection_id={id(_websocket_connection)}")
        return _websocket_connection


async def close_websocket_connection() -> None:
    """
    Close and cleanup the singleton WebSocket connection.

    Should be called once during application shutdown.
    """
    global _websocket_connection, _websocket_url

    async with _websocket_lock:
        if _websocket_connection is not None:
            logger.info("[WEBSOCKET_CLIENT] Closing WebSocket connection...")
            try:
                await _websocket_connection.close()
            except Exception as e:
                logger.warning(f"[WEBSOCKET_CLIENT] Error closing WebSocket: {e}")
            _websocket_connection = None
            _websocket_url = None
            logger.info("[WEBSOCKET_CLIENT] WebSocket connection closed")


class AukiLocalVLMStrategy(VLMStrategy):
    """Strategy for Auki local VLM service using WebSocket."""
    
    def __init__(self, vlm_url: str):
        """
        Initialize Auki Local VLM strategy.
        
        Args:
            vlm_url: Base URL of the Auki local VLM service (e.g., http://localhost:8080)
        """
        self.vlm_url = vlm_url
        self.ws_url = self._convert_to_ws_url(vlm_url)
        logger.info(f"[AUKI_LOCAL] Initialized with WebSocket URL: {self.ws_url}")
    
    def _convert_to_ws_url(self, http_url: str) -> str:
        """
        Convert HTTP URL to WebSocket URL.

        Args:
            http_url: HTTP URL (e.g., http://localhost:8080)

        Returns:
            WebSocket URL (e.g., ws://localhost:8080/api/v1/ws?num_predict=6)
        """
        # Replace http:// or https:// with ws:// or wss://
        if http_url.startswith("https://"):
            ws_url = http_url.replace("https://", "wss://", 1)
        elif http_url.startswith("http://"):
            ws_url = http_url.replace("http://", "ws://", 1)
        else:
            # Assume it's already a ws:// URL or just a host:port
            ws_url = http_url if http_url.startswith("ws") else f"ws://{http_url}"

        # Ensure it ends with /api/v1/ws
        if not ws_url.endswith("/api/v1/ws"):
            ws_url = f"{ws_url.rstrip('/')}/api/v1/ws"

        # Append or merge num_predict=6 by default
        try:
            parsed = urlparse(ws_url)
            query_params = dict(parse_qsl(parsed.query))
            # Only set default if not already provided
            if "num_predict" not in query_params:
                query_params["num_predict"] = "4"
            new_query = urlencode(query_params)
            ws_url = urlunparse(parsed._replace(query=new_query))
        except Exception as e:
            logger.warning(f"[AUKI_LOCAL] Failed to attach num_predict param, falling back. error={e}")
            ws_url = f"{ws_url}&num_predict=6" if "?" in ws_url else f"{ws_url}?num_predict=6"

        return ws_url
    
    async def query(
        self,
        file_bytes: bytes,
        question: str,
        negatives: list[str],
        bounding_questions: list[str] = None,
        debug: bool = False
    ) -> Tuple[Dict, float, Optional[float]]:
        """
        Send WebSocket request to Auki Local VLM service.
        
        ⚠️ LIMITATION: Auki Local VLM does not support negative questions or bounding boxes via WebSocket.
        Only the positive question is sent; negatives and bounding_questions parameters are ignored.
        
        Args:
            file_bytes: Image file bytes
            question: The question to ask
            negatives: List of negative questions (IGNORED for Auki Local VLM)
            bounding_questions: List of items to detect bounding boxes for (IGNORED for Auki Local VLM)
            debug: Enable debug logging to file (IGNORED for Auki Local VLM WebSocket)
            
        Returns:
            Tuple of (response_json, total_time_ms, server_proc_ms)
        """
        if debug:
            logger.info("[AUKI_LOCAL] Debug mode requested but not implemented for WebSocket provider")
        if negatives:
            logger.warning(
                f"[AUKI_LOCAL] Auki Local VLM WebSocket does not support negative questions. "
                f"Ignoring {len(negatives)} negative question(s)."
            )
        
        if bounding_questions:
            logger.warning(
                f"[AUKI_LOCAL] Auki Local VLM WebSocket does not support bounding box detection. "
                f"Ignoring {len(bounding_questions)} bounding question(s)."
            )
        
        logger.info(f"[AUKI_LOCAL] Starting WebSocket connection - resolved_url={self.ws_url}")
        logger.debug(f"[AUKI_LOCAL] Request details - question={question}, file_size={len(file_bytes)} bytes")
        
        # [TIMING] Record overall start time
        request_start = perf_counter()
        
        try:
            # Get singleton WebSocket connection
            websocket = await get_websocket_connection(self.ws_url)

            # Serialize WebSocket send/recv to avoid concurrent recv on shared connection
            async with _websocket_operation_lock:
                # Send the prompt (question only - negatives not supported)
                logger.debug(f"[AUKI_LOCAL] Sending prompt: {question}")
                await websocket.send(question)
                logger.debug(f"[AUKI_LOCAL] Prompt sent")

                # Send the image as binary data
                await websocket.send(file_bytes)
                logger.debug(f"[AUKI_LOCAL] Image data sent ({len(file_bytes)} bytes)")

                # Receive JSON responses with response/done format
                # Only accumulate responses, don't send partial responses to statemachine
                full_response = ""
                message_count = 0
                timeout_seconds = 60.0  # Configurable timeout

                logger.info(f"[⏱️ TIMING] Waiting for complete WebSocket response...")

                try:
                    while True:
                        try:
                            # Receive message with timeout
                            message = await asyncio.wait_for(
                                websocket.recv(),
                                timeout=timeout_seconds
                            )
                            message_count += 1

                            # Parse JSON message
                            try:
                                data = json.loads(message)
                                logger.debug(f"[AUKI_LOCAL] Received JSON message {message_count}: {data}")

                                # Check if message has expected format
                                if isinstance(data, dict) and 'response' in data and 'done' in data:
                                    # Accumulate response text (streaming chunks)
                                    full_response += data['response']

                                    # Only when done=true, we have the complete final response
                                    if data['done']:
                                        logger.info(f"[AUKI_LOCAL] Complete response received - {message_count} messages, final length: {len(full_response)}")
                                        logger.debug(f"[AUKI_LOCAL] *** BREAKING FROM RECV LOOP - connection_id={id(websocket)} ***")
                                        break
                                else:
                                    logger.warning(f"[AUKI_LOCAL] Unexpected message format: {data}")

                            except json.JSONDecodeError as e:
                                logger.error(f"[AUKI_LOCAL] Failed to parse message as JSON: {message}, error: {e}")
                                # Continue waiting for more messages

                        except asyncio.TimeoutError:
                            logger.warning(f"[AUKI_LOCAL] Timeout waiting for response after {timeout_seconds}s")
                            logger.debug(f"[AUKI_LOCAL] *** BREAKING FROM RECV LOOP (TIMEOUT) - connection_id={id(websocket)} ***")
                            break

                    logger.debug(f"[AUKI_LOCAL] *** EXITED RECV LOOP *** - connection_id={id(websocket)}, connection_state={websocket.state if hasattr(websocket, 'state') else 'unknown'}")

                except websockets.exceptions.ConnectionClosed as e:
                    logger.info(f"[AUKI_LOCAL] *** CONNECTION CLOSED EXCEPTION *** - code={e.code if hasattr(e, 'code') else 'N/A'}, reason={e.reason if hasattr(e, 'reason') else 'N/A'}")

            # [TIMING] Record end time
            request_end = perf_counter()
            total_time_ms = (request_end - request_start) * 1000
            
            logger.info(f"[⏱️ TIMING] WebSocket response complete - duration={total_time_ms:.2f}ms, messages={message_count}")
            logger.info(f"[AUKI_LOCAL] Request successful - received {message_count} messages")
            logger.debug(f"[AUKI_LOCAL] Full response: {full_response[:200]}...")
            
            # Format response as expected by the system
            # callbacks.py expects "result" field, not "answer"
            response_json = {
                "result": full_response,
                "question": question,
                "message_count": message_count
            }
            
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
                neg_values = list(neg_block)
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
            logger.info(f"[AUKI_LOCAL_VLM] Final decision: {final_str} (positive={positive_is_yes}, any_negative_yes={any_negative_yes})")
            # === END NEGATIVE QUESTION DECISION LOGIC ===
            
            # Server processing time not directly available from WebSocket streaming
            # The total_time_ms includes connection, sending, and receiving time
            server_proc_ms = None
            
            logger.debug(f"[AUKI_LOCAL] *** RETURNING FROM QUERY - connection still in globals, should be reused next time ***")
            return response_json, total_time_ms, server_proc_ms
                
        except websockets.exceptions.WebSocketException as e:
            logger.error(f"[AUKI_LOCAL] WebSocket error - error={str(e)}")
            raise
        except asyncio.TimeoutError as e:
            logger.error(f"[AUKI_LOCAL] WebSocket timeout - error={str(e)}")
            raise
        except ConnectionError as e:
            logger.error(f"[AUKI_LOCAL] Connection error - error={str(e)}")
            raise
        except Exception as e:
            logger.error(f"[AUKI_LOCAL] Unexpected error - error={str(e)}", exc_info=True)
            raise
    
    @property
    def name(self) -> str:
        """Return the name of this VLM strategy."""
        return "Auki Local VLM (WebSocket)"