"""Main FastAPI application for Oneshot Copilot."""
import asyncio
import logging
from fastapi import FastAPI
from app.config import VERBOSE_LOGGING
from app.core.vlm_client import init_http_client, close_http_client
from app.core.vlm_strategies.auki_local_vlm import close_websocket_connection
from app.core.metrics import init_metrics_collector

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================
def setup_logging():
    """Configure logging based on VERBOSE_LOGGING flag."""
    if VERBOSE_LOGGING:
        # Enable detailed debug logging
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        logging.info("=" * 60)
        logging.info("VERBOSE LOGGING ENABLED")
        logging.info("=" * 60)
    else:
        # Minimal logging: only warnings and errors
        logging.basicConfig(
            level=logging.WARNING,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        # Configure a dedicated logger to allow only VLM response lines
        class OnlyVLMResponseFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                try:
                    msg = record.getMessage()
                except Exception:
                    return False
                return isinstance(msg, str) and msg.startswith("[VLM_RESPONSE]")

        vlm_logger = logging.getLogger("app.api.vlm_callback")
        vlm_logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', '%Y-%m-%d %H:%M:%S'))
        handler.addFilter(OnlyVLMResponseFilter())
        vlm_logger.handlers.clear()
        vlm_logger.addHandler(handler)
        vlm_logger.propagate = False

# Initialize logging
setup_logging()
logger = logging.getLogger(__name__)

# Log application startup
logger.info("Initializing Oneshot Copilot application")

# Create FastAPI application
app = FastAPI(
    title="Oneshot Copilot",
    description="A copilot that helps users complete procedures step-by-step using computer vision",
    version="2.0.0"
)
logger.info("FastAPI application created: Oneshot Copilot v2.0.0")

# Include routers
logger.debug("Registering API routers...")

# VLM Callback (Still needed for some VLM strategies)
from app.api import vlm_callback
app.include_router(vlm_callback.router, prefix="/api", tags=["VLM Callback"])
logger.debug("Registered VLM Callback router at /api")

# New Architecture Routers
from app.api import control_plane
app.include_router(control_plane.router, prefix="/api/v2", tags=["Control Plane"])
logger.debug("Registered Control Plane router at /api/v2")

# Manual Ingest (Debug)
from app.api import ingest_v2
app.include_router(ingest_v2.router, prefix="/api/v2", tags=["Debug Ingest"])
logger.debug("Registered Debug Ingest router at /api/v2")

logger.info("All API routers registered successfully")

# Initialize new services
from app.core.event_bus import event_bus
from app.services.ingest_service import ingest_service
from app.services.job_orchestrator import job_orchestrator
from app.services.model_runtime import model_runtime
from app.services.rule_engine import rule_engine
from app.services.feedback_service import feedback_service
logger.info("Initialized new architecture services (EventBus, Ingest, Orchestrator, Runtime, RuleEngine, Feedback)")


# Background task for stream ingestion
_stream_task = None
_stream_retry_event = asyncio.Event()

async def stream_ingestion_task():
    """
    Background task for RTSP/RTMP stream ingestion with automatic retry.
    Continuously attempts to connect to the stream with configurable retry intervals.
    """
    from app.config import settings
    
    if not settings.RTSP_STREAM_URL:
        logger.info("No RTSP stream configured (RTSP_STREAM_URL is empty), skipping stream ingestion")
        return
    
    retry_interval = 10  # Retry every 10 seconds if stream is unavailable
    logger.info(f"Stream ingestion task started - will check for stream every {retry_interval}s")
    logger.info(f"Target stream: {settings.RTSP_STREAM_URL}")
    logger.info(f"Stream username: {settings.STREAM_USERNAME}")
    
    while True:
        try:
            from app.services.stream_quality_filter import StreamQualityFilter
            
            logger.info(f"Attempting to connect to stream: {settings.RTSP_STREAM_URL}")
            
            # TODO: Refactor StreamQualityFilter to use IngestService directly
            # For now, we keep it but it might need updates to post to the new endpoint or call service directly
            # This part is still legacy-ish but kept for RTSP support until fully refactored
            filter_pipeline = StreamQualityFilter(
                input_rtsp_url=settings.RTSP_STREAM_URL,
                post_url=f"{settings.SELF_URL}/api/v2/ingest/frame", # Updated to new endpoint
                post_question="Analyze this frame", # Legacy param, ignored by new endpoint
                post_verify_ssl=False,
                min_frame_interval=0.0,
                low_latency_mode=True,
                post_timeout=30,
                blur_threshold=100.0,
                brightness_min=50.0,
                brightness_max=250.0,
                post_username=settings.STREAM_USERNAME # Used as source_id?
            )
            
            logger.info(f"Stream connection established, starting frame processing...")
            
            # Run in thread pool to avoid blocking the event loop
            await asyncio.to_thread(filter_pipeline.run)
            
            logger.warning(f"Stream disconnected, will retry in {retry_interval}s")
            
        except Exception as e:
            logger.error(f"Stream connection failed: {str(e)}")
            logger.info(f"Will retry connection in {retry_interval}s")
        
        # Wait for retry interval or until signaled to retry immediately
        try:
            await asyncio.wait_for(_stream_retry_event.wait(), timeout=retry_interval)
            _stream_retry_event.clear()
            logger.info("Received retry signal, attempting immediate reconnection...")
        except asyncio.TimeoutError:
            # Timeout is normal - time to retry
            logger.debug(f"Retry interval elapsed, attempting to reconnect...")

def trigger_stream_reconnect():
    """
    Signal the stream ingestion task to immediately attempt reconnection.
    Useful when you know a stream has become available.
    """
    global _stream_retry_event
    if _stream_retry_event:
        _stream_retry_event.set()
        logger.info("Stream reconnection triggered")

@app.on_event("startup")
async def startup_event():
    """Log startup event and start background tasks."""
    global _stream_task, _stream_retry_event
    logger.info("=" * 60)
    logger.info("APPLICATION STARTUP")
    
    # Initialize singleton HTTP client for VLM requests
    logger.info("Initializing HTTP client for VLM requests...")
    await init_http_client()
    logger.info("HTTP client initialized successfully")
    
    # Initialize metrics collector
    logger.info("Initializing metrics collector...")
    init_metrics_collector()
    logger.info("Metrics collector initialized successfully")
    
    # Initialize stream retry event
    _stream_retry_event = asyncio.Event()
    
    # Start stream ingestion task if configured
    logger.info("Starting stream ingestion task...")
    _stream_task = asyncio.create_task(stream_ingestion_task())
    logger.info("Stream ingestion task started (will check for stream periodically)")
    
    logger.info("Oneshot Copilot is ready to accept requests")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Log shutdown event and cancel background tasks."""
    global _stream_task
    logger.info("=" * 60)
    logger.info("APPLICATION SHUTDOWN")
    
    if _stream_task:
        logger.info("Cancelling stream ingestion task...")
        _stream_task.cancel()
        try:
            await _stream_task
        except asyncio.CancelledError:
            logger.info("Stream ingestion task cancelled")
    
    # Close singleton HTTP client
    logger.info("Closing HTTP client...")
    await close_http_client()
    logger.info("HTTP client closed successfully")

    # Close singleton WebSocket connection
    logger.info("Closing WebSocket connection...")
    await close_websocket_connection()
    logger.info("WebSocket connection closed successfully")
    
    logger.info("=" * 60)


@app.middleware("http")
async def log_requests(request, call_next):
    """Log all incoming requests for debugging."""
    logger.info(f"[REQUEST] {request.method} {request.url.path} - Query: {dict(request.query_params)}")
    response = await call_next(request)
    logger.info(f"[RESPONSE] Status: {response.status_code}")
    return response


@app.get("/")
async def root():
    """Root endpoint."""
    logger.debug("Root endpoint accessed")
    return {
        "name": "Oneshot Copilot",
        "version": "2.0.0",
        "status": "running"
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    logger.debug("Health check endpoint accessed")
    return {"status": "healthy"}