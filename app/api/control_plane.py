from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from app.domain.entities import Source, Job, FeedbackChannel
from app.services.ingest_service import ingest_service
from app.services.job_orchestrator import job_orchestrator
from app.services.feedback_service import feedback_service
from app.core.adapters import HttpFeedbackAdapter

router = APIRouter()

@router.post("/sources")
async def register_source(source: Source):
    ingest_service.register_source(source)
    return {"status": "registered", "source_id": source.id}

@router.post("/jobs")
async def register_job(job: Job):
    job_orchestrator.register_job(job)
    return {"status": "registered", "job_id": job.id}

@router.post("/feedback/channels")
async def register_feedback_channel(channel: FeedbackChannel):
    # For now, assume HTTP adapter for all dynamic channels or infer from config
    if channel.type == "http":
        url = channel.config.get("url")
        if not url:
            raise HTTPException(status_code=400, detail="URL required for http channel")
        adapter = HttpFeedbackAdapter(url)
        feedback_service.register_channel(channel, adapter)
    else:
        # TODO: Support other adapter types
        pass
    return {"status": "registered", "channel_id": channel.id}

@router.get("/health")
async def health_check():
    return {"status": "healthy", "components": ["ingest", "orchestrator", "feedback"]}

@router.get("/debug/status")
async def get_debug_status():
    """Get full server state for debugging."""
    try:
        from app.services.procedure_service import procedure_service
        from dataclasses import asdict
        
        sources = ingest_service.get_all_sources()
        proc_state = procedure_service.get_debug_state()
        
        return {
            "sources": [asdict(s) for s in sources],
            "procedures": proc_state,
            "jobs": [] # TODO: Add job orchestrator state if needed
        }
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@router.get("/status")
async def get_camera_status(camera_id: str):
    """
    Get the current status for a camera (user).
    This is polled by clients to update UI.
    
    Args:
        camera_id: The ID of the camera (username)
    """
    from app.services.status_service import get_active_status
    
    status = get_active_status(camera_id)
    
    if not status:
        # Return a default IDLE status if no active procedure found
        return {
            "username": camera_id,
            "state": "IDLE",
            "procedure": None,
            "step": None
        }
        
    return status
