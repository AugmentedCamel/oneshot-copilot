import asyncio
import logging
from app.domain.entities import Source, Job, Event, EventType, Frame
from app.core.event_bus import event_bus
from app.services.ingest_service import ingest_service
from app.services.job_orchestrator import job_orchestrator
from app.services.model_runtime import model_runtime
from app.domain.interfaces import ModelPlugin
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify")

# Mock Model Plugin
class MockModelPlugin(ModelPlugin):
    def load(self, config: Dict[str, Any]) -> None:
        logger.info("MockModelPlugin loaded")

    async def infer(self, frame: Frame, context: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"MockModelPlugin infer called for frame {frame.id}")
        return {"detected": "pizza", "confidence": 0.99}

async def main():
    logger.info("Starting verification...")

    # 1. Register Mock Model
    model_runtime.register_plugin_class("mock-model", MockModelPlugin)
    model_runtime.load_model("pizza-detector", "mock-model", {})

    # 2. Register Source
    source = Source(id="src_test", name="Test Camera", type="camera", ingest_type="mock")
    ingest_service.register_source(source)

    # 3. Register Job
    job = Job(
        id="job_pizza_check",
        name="Pizza Quality Check",
        source_id="src_test",
        pipeline=[
            {"type": "model", "name": "pizza-detector"}
        ],
        outputs=[]
    )
    job_orchestrator.register_job(job)

    # 4. Subscribe to events to verify flow
    received_events = []
    
    async def on_event(event: Event):
        logger.info(f"Received event: {event.type}")
        received_events.append(event.type)

    event_bus.subscribe_all(on_event)

    # 5. Ingest Frame via Service (simulating API call)
    logger.info("Ingesting frame...")
    await ingest_service.ingest_frame("src_test", b"fake_image_data")

    # Wait for processing
    await asyncio.sleep(1)

    # 6. Verify
    assert EventType.FRAME_CREATED in received_events, "Frame created event missing"
    assert EventType.MODEL_INFERENCE in received_events, "Model inference event missing"
    
    logger.info("Verification SUCCESS! All expected events received.")

if __name__ == "__main__":
    asyncio.run(main())
