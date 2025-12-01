import logging
import httpx
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class MemoryServiceClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')

    async def create_session(self, username: str, procedure_id: str, source_id: str) -> str:
        """Start a new session in Memory Service."""
        url = f"{self.base_url}/sessions/start"
        payload = {
            "username": username,
            "procedure_id": procedure_id,
            "source_id": source_id
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=5.0)
                response.raise_for_status()
                data = response.json()
                return data["session_id"]
        except Exception as e:
            logger.error(f"Failed to create memory session: {e}")
            raise

    async def get_procedure(self, procedure_id: str) -> Dict[str, Any]:
        """Fetch procedure definition from Memory Service (LTM)."""
        url = f"{self.base_url}/procedures/{procedure_id}" 
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=5.0)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch procedure {procedure_id}: {e}")
            raise

    async def add_item_to_session(self, session_id: str, content: str, metadata: Optional[Dict] = None) -> None:
        """Add an item to the STM session."""
        url = f"{self.base_url}/sessions/{session_id}/items"
        payload = {
            "content": content,
            "metadata": metadata or {}
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=2.0) # Short timeout for logging
                response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to log item to session {session_id}: {e}")
            # We might not want to raise here to avoid breaking the main flow just because logging failed
            
    async def close_session(self, session_id: str) -> None:
        """Close the session."""
        url = f"{self.base_url}/sessions/{session_id}/close"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, timeout=5.0)
                response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to close session {session_id}: {e}")
            raise
