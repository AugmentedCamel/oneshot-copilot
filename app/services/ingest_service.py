import logging
import time
import uuid
from typing import Dict, Optional
from app.domain.entities import Source, Frame, Event, EventType
from app.core.event_bus import event_bus
from app.core.frame_store import store_frame  # Assuming we reuse existing frame store logic or adapt it

logger = logging.getLogger(__name__)

class IngestService:
    def __init__(self):
        self._sources: Dict[str, Source] = {}

    def register_source(self, source: Source):
        self._sources[source.id] = source
        logger.info(f"Registered source: {source.name} ({source.id})")

    def get_source(self, source_id: str) -> Optional[Source]:
        return self._sources.get(source_id)

    async def ingest_frame(self, source_id: str, frame_data: bytes, metadata: Dict = None):
        if source_id not in self._sources:
            logger.warning(f"Ingest received frame for unknown source: {source_id}")
            return

        frame_id = str(uuid.uuid4())
        timestamp = int(time.time() * 1000)
        
        # Save frame using existing store or new mechanism
        # For now, reusing the idea of saving to disk/memory and passing ID
        # In a real implementation, we might pass bytes directly or use shared memory
        # Here we assume save_frame returns a path or we just use the ID if it stores in memory
        # Adapting to existing frame_store.py which uses a dict or file
        # Let's assume we just pass the ID and the data is stored
        
        # TODO: Refactor frame_store to be more robust or use a proper Frame object
        # For now, we'll use the existing save_frame helper if available or mock it
        # save_frame(frame_id, frame_data) 
        
        # Create Frame entity
        frame = Frame(
            id=frame_id,
            source_id=source_id,
            timestamp_ms=timestamp,
            data=frame_data,
            metadata=metadata or {}
        )

        # Emit event
        event = Event(
            type=EventType.FRAME_CREATED,
            job_id=None, # Ingest doesn't know about jobs yet
            source_id=source_id,
            payload={"frame": frame}
        )
        
        await event_bus.publish(event)
        logger.debug(f"Ingested frame {frame_id} from source {source_id}")

# Global instance
ingest_service = IngestService()
