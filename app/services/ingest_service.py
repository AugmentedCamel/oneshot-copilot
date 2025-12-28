import logging
import time
import uuid
from typing import Dict, Optional, List
from app.domain.entities import Source, Frame, Event, EventType
from app.core.event_bus import event_bus
from app.core.frame_store import store_frame  # Assuming we reuse existing frame store logic or adapt it

logger = logging.getLogger(__name__)

class IngestService:
    def __init__(self):
        self._sources: Dict[str, Source] = {}
        # Timing instrumentation
        self._frame_count = 0
        self._fps_start_time = time.time()
        self._last_ingest_time = 0.0

    def register_source(self, source: Source):
        self._sources[source.id] = source
        logger.info(f"Registered source: {source.name} ({source.id})")

    def get_source(self, source_id: str) -> Optional[Source]:
        return self._sources.get(source_id)

    def get_all_sources(self) -> List[Source]:
        return list(self._sources.values())

    async def ingest_frame(self, source_id: str, frame_data: bytes, metadata: Dict = None):
        if source_id not in self._sources:
            logger.warning(f"Ingest received frame for unknown source: {source_id}")
            return

        frame_id = str(uuid.uuid4())
        timestamp = int(time.time() * 1000)
        
        # Save frame using existing store
        store_frame(frame_id, frame_data) 
        
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
        
        # Timing instrumentation
        now = time.time()
        frame_interval_ms = (now - self._last_ingest_time) * 1000 if self._last_ingest_time > 0 else 0
        self._last_ingest_time = now
        self._frame_count += 1
        
        # Calculate actual FPS
        elapsed = now - self._fps_start_time
        actual_fps = self._frame_count / elapsed if elapsed > 0 else 0
        
        logger.info(
            f"[INGEST_SERVICE] Frame {frame_id[:8]}... ingested: "
            f"interval={frame_interval_ms:.0f}ms, fps={actual_fps:.1f}, "
            f"total_frames={self._frame_count}"
        )

# Global instance
ingest_service = IngestService()
