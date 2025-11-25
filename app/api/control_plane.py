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
