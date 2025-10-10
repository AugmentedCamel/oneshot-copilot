"""Main FastAPI application for Oneshot Copilot."""
from fastapi import FastAPI
from app.api import ingest, vlm_callback, procedure

# Create FastAPI application
app = FastAPI(
    title="Oneshot Copilot",
    description="A copilot that helps users complete procedures step-by-step using computer vision",
    version="1.0.0"
)

# Include routers
app.include_router(procedure.router, tags=["Procedure Control"])
app.include_router(ingest.router, tags=["Frame Ingestion"])
app.include_router(vlm_callback.router, tags=["VLM Callback"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Oneshot Copilot",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}