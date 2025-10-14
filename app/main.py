"""Main FastAPI application for Oneshot Copilot."""
import asyncio
import logging
from fastapi import FastAPI
from app.api import ingest, vlm_callback, procedure
from app.config import VERBOSE_LOGGING

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

# Initialize logging
setup_logging()
logger = logging.getLogger(__name__)

# Log application startup
logger.info("Initializing Oneshot Copilot application")

# Create FastAPI application
app = FastAPI(
    title="Oneshot Copilot",
    description="A copilot that helps users complete procedures step-by-step using computer vision",
    version="1.0.0"
)
logger.info("FastAPI application created: Oneshot Copilot v1.0.0")

# Include routers
logger.debug("Registering API routers...")
app.include_router(procedure.router, prefix="/api", tags=["Procedure Control"])
logger.debug("Registered Procedure Control router at /api")
app.include_router(ingest.router, prefix="/api", tags=["Frame Ingestion"])
logger.debug("Registered Frame Ingestion router at /api")
app.include_router(vlm_callback.router, prefix="/api", tags=["VLM Callback"])
logger.debug("Registered VLM Callback router at /api")
logger.info("All API routers registered successfully with /api prefix")


# Background task for timeout checking
_tick_task = None

async def tick_all_users():
    """Background task that periodically checks for timeouts."""
    logger.info("Starting background tick task for timeout checking")
    while True:
        try:
            # Get all active users from the state machine
            from app.api.procedure import machine
            if machine._users:
                for username in list(machine._users.keys()):
                    try:
                        machine.tick(username)
                    except Exception as e:
                        logger.error(f"Error in tick for user {username}: {str(e)}", exc_info=True)
            
            # Check every 100ms for responsive timeout detection
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in tick_all_users background task: {str(e)}", exc_info=True)
            await asyncio.sleep(1.0)

@app.on_event("startup")
async def startup_event():
    """Log startup event and start background tasks."""
    global _tick_task
    logger.info("=" * 60)
    logger.info("APPLICATION STARTUP COMPLETE")
    logger.info("Starting background timeout checker...")
    _tick_task = asyncio.create_task(tick_all_users())
    logger.info("Background timeout checker started")
    logger.info("Oneshot Copilot is ready to accept requests")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Log shutdown event and cancel background tasks."""
    global _tick_task
    logger.info("=" * 60)
    logger.info("APPLICATION SHUTDOWN")
    if _tick_task:
        logger.info("Cancelling background timeout checker...")
        _tick_task.cancel()
        try:
            await _tick_task
        except asyncio.CancelledError:
            logger.info("Background timeout checker cancelled")
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
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    logger.debug("Health check endpoint accessed")
    return {"status": "healthy"}