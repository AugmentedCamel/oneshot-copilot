"""VLM client for multipart HTTP requests."""
import logging
import httpx
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# SINGLETON HTTP CLIENT
# A single persistent httpx.AsyncClient for all VLM requests to enable
# connection pooling and eliminate per-request connection overhead.
# ============================================================================
_http_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    """
    Get the singleton HTTP client instance.
    
    Returns:
        The initialized httpx.AsyncClient singleton
        
    Raises:
        RuntimeError: If client has not been initialized via init_http_client()
    """
    if _http_client is None:
        raise RuntimeError(
            "HTTP client not initialized. Call init_http_client() during startup."
        )
    return _http_client


async def init_http_client() -> None:
    """
    Initialize the singleton HTTP client with optimal settings for VLM requests.
    
    Configuration:
    - Timeout: 2.5 seconds (aligned with state machine VLM timeout)
    - Max connections: 20
    - Max keepalive connections: 10
    - Keepalive expiry: 60 seconds
    
    Should be called once during application startup.
    """
    global _http_client
    
    if _http_client is not None:
        logger.warning("HTTP client already initialized, skipping re-initialization")
        return
    
    from app.config import (
        HTTP_TIMEOUT,
        HTTP_MAX_CONNECTIONS,
        HTTP_MAX_KEEPALIVE_CONNECTIONS,
        HTTP_KEEPALIVE_EXPIRY
    )
    
    # Configure timeout
    timeout = httpx.Timeout(HTTP_TIMEOUT)
    
    # Configure connection pooling
    limits = httpx.Limits(
        max_connections=HTTP_MAX_CONNECTIONS,
        max_keepalive_connections=HTTP_MAX_KEEPALIVE_CONNECTIONS,
        keepalive_expiry=HTTP_KEEPALIVE_EXPIRY
    )
    
    _http_client = httpx.AsyncClient(timeout=timeout, limits=limits)
    
    logger.info(
        f"[HTTP_CLIENT] Singleton client initialized - "
        f"timeout={HTTP_TIMEOUT}s, "
        f"max_connections={HTTP_MAX_CONNECTIONS}, "
        f"max_keepalive={HTTP_MAX_KEEPALIVE_CONNECTIONS}, "
        f"keepalive_expiry={HTTP_KEEPALIVE_EXPIRY}s"
    )


async def close_http_client() -> None:
    """
    Close and cleanup the singleton HTTP client.
    
    Should be called once during application shutdown to properly
    release resources and close persistent connections.
    """
    global _http_client
    
    if _http_client is None:
        logger.debug("HTTP client not initialized, nothing to close")
        return
    
    logger.info("[HTTP_CLIENT] Closing singleton client...")
    await _http_client.aclose()
    _http_client = None
    logger.info("[HTTP_CLIENT] Singleton client closed successfully")


# ============================================================================
# VLM STRATEGY FACTORY
# Factory function to get the appropriate VLM strategy based on configuration
# ============================================================================

def get_vlm_strategy():
    """
    Factory function to get the appropriate VLM strategy based on configuration.
    
    Returns:
        VLMStrategy instance configured from settings
        
    Raises:
        ValueError: If VLM_PROVIDER is not recognized
    """
    from app.config import settings
    from app.core.vlm_strategies import (
        LocalVLMStrategy,
        MoondreamVLMStrategy,
        AukiLocalVLMStrategy
    )
    
    provider = settings.VLM_PROVIDER.lower()
    
    if provider == "local":
        logger.info("[VLM_FACTORY] Creating Local VLM strategy")
        return LocalVLMStrategy(vlm_url=settings.VLM_URL)
    
    elif provider == "moondream":
        logger.info("[VLM_FACTORY] Creating Moondream AI strategy")
        return MoondreamVLMStrategy(api_key=settings.MOONDREAM_API_KEY)
    
    elif provider == "auki_local":
        logger.info("[VLM_FACTORY] Creating Auki Local VLM strategy")
        return AukiLocalVLMStrategy(vlm_url=settings.VLM_URL)
    
    else:
        raise ValueError(
            f"Unknown VLM_PROVIDER: '{settings.VLM_PROVIDER}'. "
            f"Supported values: 'local', 'moondream', 'auki_local'"
        )


async def post_to_vlm_multipart(
    file_bytes: bytes,
    question: str,
    negatives: list[str],
    vlm_url: str
) -> Tuple[Dict, float, Optional[float]]:
    """
    Send multipart request to VLM using the configured strategy.
    
    Routes to appropriate VLM implementation based on VLM_PROVIDER setting:
    - "local": Local VLM service (supports negative questions)
    - "moondream": Moondream AI cloud (ignores negative questions)
    - "auki_local": Auki Local VLM service (supports negative questions)
    
    Args:
        file_bytes: Image file bytes
        question: The positive question to ask
        negatives: List of negative questions (support depends on provider)
        vlm_url: Base URL (used by some strategies, ignored by others)
        
    Returns:
        Tuple of (response_json, http_post_ms, server_proc_ms)
    """
    strategy = get_vlm_strategy()
    logger.info(f"[VLM_CLIENT] Using strategy: {strategy.name}")
    logger.debug(f"[VLM_CLIENT] *** STRATEGY INSTANCE *** id={id(strategy)}, type={type(strategy).__name__}")
    
    return await strategy.query(
        file_bytes=file_bytes,
        question=question,
        negatives=negatives
    )