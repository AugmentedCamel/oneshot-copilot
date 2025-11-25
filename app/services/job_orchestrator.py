import logging
import asyncio
from typing import Dict, List, Any
from app.domain.entities import Job, Event, EventType, Frame
from app.core.event_bus import event_bus
from app.services.model_runtime import model_runtime
# from app.services.rule_engine import rule_engine # To be implemented

logger = logging.getLogger(__name__)

class JobOrchestrator:
    def __init__(self):
        self._jobs: Dict[str, Job] = {}
        # Subscribe to frame events
        event_bus.subscribe(EventType.FRAME_CREATED, self._on_frame_created)

    def register_job(self, job: Job):
        self._jobs[job.id] = job
        logger.info(f"Registered job: {job.name} ({job.id})")

    async def _on_frame_created(self, event: Event):
        frame: Frame = event.payload.get("frame")
        if not frame:
            return

        # Find jobs for this source
        relevant_jobs = [j for j in self._jobs.values() if j.source_id == frame.source_id and j.enabled]
        
        for job in relevant_jobs:
            asyncio.create_task(self._run_job_pipeline(job, frame))

    async def _run_job_pipeline(self, job: Job, frame: Frame):
        logger.debug(f"Running job {job.id} for frame {frame.id}")
        
        context = {"job_id": job.id, "source_id": frame.source_id}
        
        try:
            # 1. Run Pipeline Steps
            for step in job.pipeline:
                step_type = step.get("type")
                name = step.get("name")
                
                if step_type == "model":
                    # Execute model
                    result = await model_runtime.run(name, frame, context)
                    context[f"model_{name}"] = result
                    
                    # Emit inference event
                    await event_bus.publish(Event(
                        type=EventType.MODEL_INFERENCE,
                        job_id=job.id,
                        source_id=frame.source_id,
                        payload={"model": name, "result": result, "frame_id": frame.id}
                    ))
                    
                elif step_type == "rule":
                    # Execute rule (TODO: Integrate RuleEngine)
                    # result = await rule_engine.evaluate(name, context)
                    # context[f"rule_{name}"] = result
                    pass

            # 2. Process Outputs (Feedback/Logs) - handled by Rule Engine usually, 
            # or we can do simple mapping here if the job defines direct outputs
            # For now, we assume Rule Engine emits events that Feedback Service listens to.
            
        except Exception as e:
            logger.error(f"Error running job {job.id}: {e}", exc_info=True)
            await event_bus.publish(Event(
                type=EventType.ERROR,
                job_id=job.id,
                source_id=frame.source_id,
                payload={"error": str(e), "frame_id": frame.id}
            ))

# Global instance
job_orchestrator = JobOrchestrator()
