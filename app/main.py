"""Main FastAPI application for Oneshot Copilot."""
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
app.include_router(procedure.router, tags=["Procedure Control"])
logger.debug("Registered Procedure Control router")
app.include_router(ingest.router, tags=["Frame Ingestion"])
logger.debug("Registered Frame Ingestion router")
app.include_router(vlm_callback.router, tags=["VLM Callback"])
logger.debug("Registered VLM Callback router")
logger.info("All API routers registered successfully")


@app.on_event("startup")
async def startup_event():
    """Log startup event."""
    logger.info("=" * 60)
    logger.info("APPLICATION STARTUP COMPLETE")
    logger.info("Oneshot Copilot is ready to accept requests")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Log shutdown event."""
    logger.info("=" * 60)
    logger.info("APPLICATION SHUTDOWN")
    logger.info("=" * 60)


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