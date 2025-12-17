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
        vlm_logger.addHandler(handler)
        vlm_logger.propagate = False

        # Explicitly enable INFO logging for procedure engine debugging
        proc_logger = logging.getLogger("app.domain.procedure_engine")
        proc_logger.setLevel(logging.INFO)

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

from app.api import procedure_v2
app.include_router(procedure_v2.router, prefix="/api/v2", tags=["Procedures"])
logger.debug("Registered Procedure router at /api/v2")

# Manual Ingest (Debug)
from app.api import ingest_v2
app.include_router(ingest_v2.router, prefix="/api/v2", tags=["Debug Ingest"])
logger.debug("Registered Debug Ingest router at /api/v2")

# Agent Assist
from app.api import agent
app.include_router(agent.router, prefix="/api/v2/agent", tags=["Agent Assist"])
logger.debug("Registered Agent Assist router at /api/v2/agent")

# Node Graph Procedures
from app.api import nodegraph_v2
app.include_router(nodegraph_v2.router, prefix="/api/v2/procedures", tags=["Node Graph Procedures"])
logger.debug("Registered Node Graph Procedures router at /api/v2/procedures")

# Data Harvester
from app.api import harvester
app.include_router(harvester.router, prefix="/api/v2", tags=["Data Harvester"])
logger.debug("Registered Data Harvester router at /api/v2")

logger.info("All API routers registered successfully")

# Initialize new services
from app.core.event_bus import event_bus
from app.services.ingest_service import ingest_service
from app.services.job_orchestrator import job_orchestrator
from app.services.model_runtime import model_runtime
from app.services.rule_engine import rule_engine
from app.services.feedback_service import feedback_service
from app.services.procedure_service import procedure_service
from app.services.agent_service import agent_service
from app.core.startup import run_startup_initialization, run_shutdown_cleanup

logger.info("Initialized new architecture services (EventBus, Ingest, Orchestrator, Runtime, RuleEngine, Feedback, Procedure)")


@app.on_event("startup")
async def startup_event():
    """Log startup event and start background tasks."""
    logger.info("=" * 60)
    
    # Initialize singleton HTTP client for VLM requests
    logger.info("Initializing HTTP client for VLM requests...")
    await init_http_client()
    logger.info("HTTP client initialized successfully")
    
    # Initialize metrics collector
    logger.info("Initializing metrics collector...")
    init_metrics_collector()
    logger.info("Metrics collector initialized successfully")
    
    # Run new architecture startup initialization
    await run_startup_initialization()
    
    logger.info("Oneshot Copilot is ready to accept requests")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Log shutdown event and cancel background tasks."""
    logger.info("=" * 60)
    logger.info("APPLICATION SHUTDOWN")
    
    # Run new architecture shutdown cleanup
    await run_shutdown_cleanup()
    
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