"""Node Graph AI Client.

Provides a singleton client with persistent connection pooling for the AI service.

Usage:
    client = get_nodegraph_client()
    await client.connect()  # Call once at startup
    
    # These reuse the same TCP connection pool:
    await client.ingest_frame_async(...)
    await client.poll_latest_result()
    await client.dispatch_to_nodegraph_ai(...)
    
    await client.disconnect()  # Call at shutdown
"""
import logging
import json
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx

from app.config import settings
from app.core.aspect_ratio import normalize_to_landscape_aspect_ratio

logger = logging.getLogger(__name__)


@dataclass
class StepNodeResult:
    """Result from polling /stepnode/result endpoint."""
    sequence_id: int
    timestamp: float
    predictions: Dict[str, float]
    inference_ms: Optional[int] = None
    procedure_id: Optional[str] = None


class NodeGraphClient:
    """Client for AI node with persistent connection pool.
    
    This client maintains a single httpx.AsyncClient with connection pooling,
    eliminating the ~300-700ms TCP handshake overhead per request.
    """
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self._client: Optional[httpx.AsyncClient] = None
    
    async def connect(self) -> None:
        """Initialize persistent client with connection pool."""
        if self._client is not None:
            logger.warning("[NODEGRAPH_CLIENT] Already connected")
            return
        
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(
                connect=2.0,    # Connection timeout
                read=5.0,       # Read timeout
                write=5.0,      # Write timeout
                pool=1.0,       # Pool wait timeout
            ),
            limits=httpx.Limits(
                max_connections=10,           # Total connections to pool
                max_keepalive_connections=5,  # Keep-alive connections
                keepalive_expiry=30.0,        # Keep connections alive 30s
            ),
        )
        logger.info(
            f"[NODEGRAPH_CLIENT] Connected to {self.base_url} with connection pool "
            f"(max_conn=10, keepalive=5, expiry=30s)"
        )
    
    async def disconnect(self) -> None:
        """Close the client and connection pool."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("[NODEGRAPH_CLIENT] Disconnected")
    
    async def _ensure_connected(self) -> httpx.AsyncClient:
        """Lazy initialization of client."""
        if self._client is None:
            await self.connect()
        return self._client
    
    # -------------------------------------------------------------------------
    # Async Mode: Non-blocking ingestion + polling
    # -------------------------------------------------------------------------
    
    async def ingest_frame_async(
        self,
        frame_bytes: bytes,
        procedure_id: str,
        user_id: str,
        target_classes: List[str],
        excluded_candidates: List[str] = None,
        candidate_scope: List[str] = None,
        callback_url: Optional[str] = None,
        session_id: Optional[str] = None,
        frame_id: Optional[str] = None
    ) -> bool:
        """Submit a frame for async processing (non-blocking).

        This calls POST /stepnode/ingest which returns 202 immediately.
        The AI node buffers the frame and processes it asynchronously.
        Results are delivered via callback to the specified callback_url.

        Args:
            frame_bytes: JPEG image bytes
            procedure_id: ID of the procedure being executed
            user_id: Username for tracking (sent as 'username' to AI node)
            target_classes: List of class names to detect
            excluded_candidates: Classes to exclude from detection
            candidate_scope: Limit detection to these candidates
            callback_url: URL where AI node should POST results
            session_id: Session ID for stale callback detection
            frame_id: Frame ID for chronological tracking

        Returns:
            True if frame was accepted (202), False otherwise
        """
        client = await self._ensure_connected()

        # ==============================================================
        # ASPECT RATIO NORMALIZATION: AI model trained on 16:9 landscape
        # See app/core/aspect_ratio.py for full documentation
        # ==============================================================
        frame_bytes = normalize_to_landscape_aspect_ratio(frame_bytes)

        logger.info(
            f"[NODEGRAPH_CLIENT] Ingesting frame async for {user_id}, "
            f"procedure={procedure_id}, classes={target_classes}, "
            f"callback_url={callback_url}, session_id={session_id}, frame_id={frame_id}"
        )

        try:
            files = {
                "file": ("frame.jpg", frame_bytes, "image/jpeg")
            }
            data = {
                "procedure_id": procedure_id,
                "target_classes": json.dumps(target_classes),
                "excluded_candidates": json.dumps(excluded_candidates or []),
                "candidate_scope": json.dumps(candidate_scope or [])
            }

            # Add callback and user tracking fields (new stepnode pipeline)
            if callback_url:
                data["callback_url"] = callback_url
            if user_id:
                data["username"] = user_id  # New field name for multi-user tracking
            if session_id:
                data["session_id"] = session_id
            if frame_id:
                data["frame_id"] = frame_id

            logger.debug(f"[NODEGRAPH_CLIENT] POST /stepnode/ingest data={data}")

            response = await client.post("/stepnode/ingest", files=files, data=data)

            if response.status_code == 202:
                logger.info(
                    f"[NODEGRAPH_CLIENT] Frame accepted for async processing "
                    f"(user={user_id}, procedure={procedure_id})"
                )
                return True
            else:
                logger.warning(
                    f"[NODEGRAPH_CLIENT] Unexpected status {response.status_code} from ingest: "
                    f"{response.text}"
                )
                return False

        except httpx.ConnectError as e:
            logger.error(f"[NODEGRAPH_CLIENT] Ingest connection failed: {e}")
            return False
        except httpx.TimeoutException as e:
            logger.error(f"[NODEGRAPH_CLIENT] Ingest timeout: {e}")
            return False
        except Exception as e:
            logger.error(f"[NODEGRAPH_CLIENT] Ingest error: {e}")
            return False
    
    async def poll_latest_result(self) -> Optional[StepNodeResult]:
        """Poll for the latest detection result.
        
        Calls GET /stepnode/result to fetch the most recent inference result.
        
        Returns:
            StepNodeResult if available, None if no result yet (404) or timeout (408)
        """
        client = await self._ensure_connected()
        
        try:
            response = await client.get("/stepnode/result")
            
            if response.status_code == 200:
                data = response.json()
                
                # Extract buffer metadata if available
                buffer_meta = data.get("_buffer_metadata", {})
                
                result = StepNodeResult(
                    sequence_id=data.get("sequence_id", 0),
                    timestamp=data.get("timestamp", 0.0),
                    predictions=data.get("predictions", {}),
                    inference_ms=buffer_meta.get("inference_ms"),
                    procedure_id=buffer_meta.get("procedure_id")
                )
                
                logger.debug(
                    f"[NODEGRAPH_CLIENT] Polled result seq={result.sequence_id}, "
                    f"predictions={result.predictions}"
                )
                return result
                
            elif response.status_code == 404:
                # No results available yet
                logger.debug("[NODEGRAPH_CLIENT] No results available yet (404)")
                return None
                
            elif response.status_code == 408:
                # Timeout waiting for new result
                logger.debug("[NODEGRAPH_CLIENT] Poll timeout (408)")
                return None
                
            else:
                logger.warning(f"[NODEGRAPH_CLIENT] Unexpected poll status: {response.status_code}")
                return None
                
        except httpx.ConnectError as e:
            logger.error(f"[NODEGRAPH_CLIENT] Poll connection failed: {e}")
            return None
        except httpx.TimeoutException as e:
            logger.debug(f"[NODEGRAPH_CLIENT] Poll request timeout: {e}")
            return None
        except Exception as e:
            logger.error(f"[NODEGRAPH_CLIENT] Poll error: {e}")
            return None
    
    # -------------------------------------------------------------------------
    # Sync Mode: Blocking request/response (for prompt builder compatibility)
    # -------------------------------------------------------------------------
    
    async def dispatch_to_nodegraph_ai(
        self,
        frame_bytes: bytes,
        user_id: str,
        frame_id: str,
        procedure_id: str,
        target_classes: List[str],
        excluded_candidates: List[str] = None,
        candidate_scope: List[str] = None
    ) -> Dict[str, float]:
        """Send a frame to the AI service for node detection.
        
        This is a SYNCHRONOUS call - we wait for the prediction vector.
        
        Returns:
            Dict mapping class names to confidence scores (0.0-1.0)
        """
        client = await self._ensure_connected()
        
        # ==============================================================
        # ASPECT RATIO NORMALIZATION: AI model trained on 16:9 landscape
        # See app/core/aspect_ratio.py for full documentation
        # ==============================================================
        frame_bytes = normalize_to_landscape_aspect_ratio(frame_bytes)
        
        logger.debug(
            f"[NODEGRAPH_CLIENT] Sending request for user {user_id}, "
            f"frame {frame_id}, classes={target_classes}"
        )
        
        try:
            files = {
                "file": ("frame.jpg", frame_bytes, "image/jpeg")
            }
            data = {
                "user_id": user_id,
                "frame_id": frame_id,
                "procedure_id": procedure_id,
                "target_classes": json.dumps(target_classes),
                "excluded_candidates": json.dumps(excluded_candidates or []),
                "candidate_scope": json.dumps(candidate_scope or [])
            }
            
            response = await client.post("/stepnodedetection", files=files, data=data)
            response.raise_for_status()
            
            result = response.json()
            predictions = result.get("predictions", {})
            
            logger.debug(
                f"[NODEGRAPH_CLIENT] Received predictions for {user_id}: {predictions}"
            )
            
            return predictions
            
        except httpx.ConnectError as e:
            logger.error(f"[NODEGRAPH_CLIENT] Connection failed: {e}")
            raise RuntimeError(f"AI service connection failed: {e}")
        except httpx.TimeoutException as e:
            logger.error(f"[NODEGRAPH_CLIENT] Request timed out: {e}")
            raise RuntimeError(f"AI service timeout: {e}")
        except httpx.HTTPStatusError as e:
            logger.error(f"[NODEGRAPH_CLIENT] HTTP error: {e.response.status_code}")
            raise RuntimeError(f"AI service error: {e.response.status_code}")
        except Exception as e:
            logger.error(f"[NODEGRAPH_CLIENT] Unexpected error: {e}")
            raise RuntimeError(f"AI service error: {e}")


# -----------------------------------------------------------------------------
# Singleton Instance
# -----------------------------------------------------------------------------

_nodegraph_client: Optional[NodeGraphClient] = None


def get_nodegraph_client() -> NodeGraphClient:
    """Get or create the singleton NodeGraphClient instance."""
    global _nodegraph_client
    if _nodegraph_client is None:
        _nodegraph_client = NodeGraphClient(settings.AI_NODE_URL)
    return _nodegraph_client


# -----------------------------------------------------------------------------
# Backward Compatibility: Module-level wrapper functions
# These delegate to the singleton client for code that imports functions directly
# -----------------------------------------------------------------------------

async def ingest_frame_async(
    frame_bytes: bytes,
    procedure_id: str,
    user_id: str,
    target_classes: List[str],
    excluded_candidates: List[str] = None,
    candidate_scope: List[str] = None,
    callback_url: Optional[str] = None,
    session_id: Optional[str] = None,
    frame_id: Optional[str] = None
) -> bool:
    """Backward-compatible wrapper for ingest_frame_async."""
    client = get_nodegraph_client()
    return await client.ingest_frame_async(
        frame_bytes=frame_bytes,
        procedure_id=procedure_id,
        user_id=user_id,
        target_classes=target_classes,
        excluded_candidates=excluded_candidates,
        candidate_scope=candidate_scope,
        callback_url=callback_url,
        session_id=session_id,
        frame_id=frame_id
    )


async def poll_latest_result() -> Optional[StepNodeResult]:
    """Backward-compatible wrapper for poll_latest_result."""
    client = get_nodegraph_client()
    return await client.poll_latest_result()


async def dispatch_to_nodegraph_ai(
    frame_bytes: bytes,
    user_id: str,
    frame_id: str,
    procedure_id: str,
    target_classes: List[str],
    excluded_candidates: List[str] = None,
    candidate_scope: List[str] = None
) -> Dict[str, float]:
    """Backward-compatible wrapper for dispatch_to_nodegraph_ai."""
    client = get_nodegraph_client()
    return await client.dispatch_to_nodegraph_ai(
        frame_bytes=frame_bytes,
        user_id=user_id,
        frame_id=frame_id,
        procedure_id=procedure_id,
        target_classes=target_classes,
        excluded_candidates=excluded_candidates,
        candidate_scope=candidate_scope
    )
