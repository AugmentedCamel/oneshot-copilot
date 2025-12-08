import logging
import httpx
from typing import Dict, Any
from app.domain.interfaces import FeedbackAdapter
from app.config import settings

logger = logging.getLogger(__name__)

class HttpFeedbackAdapter(FeedbackAdapter):
    def __init__(self, base_url: str):
        self.base_url = base_url

    async def send(self, message: Dict[str, Any]) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(self.base_url, json=message)
            logger.info(f"Sent feedback to {self.base_url}: {message}")
        except Exception as e:
            logger.error(f"Failed to send feedback to {self.base_url}: {e}")

class MockCaptureAdapter:
    def __init__(self, source_id: str):
        self.source_id = source_id

    async def start(self):
        logger.info(f"Started capture for {self.source_id}")

    async def stop(self):
        logger.info(f"Stopped capture for {self.source_id}")
