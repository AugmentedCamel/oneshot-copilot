import logging
import httpx
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Default timeouts
DEFAULT_TIMEOUT = 5.0
LOGGING_TIMEOUT = 2.0  # Shorter timeout for non-critical logging

# Connection pool limits
MAX_CONNECTIONS = 20
MAX_KEEPALIVE_CONNECTIONS = 10


class MemoryServiceClient:
    """Client for Memory Service with connection pooling.

    Uses a reusable httpx.AsyncClient to avoid creating new TCP connections
    for every request. This significantly improves performance under load.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the shared httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(DEFAULT_TIMEOUT),
                limits=httpx.Limits(
                    max_connections=MAX_CONNECTIONS,
                    max_keepalive_connections=MAX_KEEPALIVE_CONNECTIONS
                )
            )
            logger.info("[MEMORY_CLIENT] Created new httpx client with connection pooling")
        return self._client

    async def close(self) -> None:
        """Close the httpx client (call on shutdown)."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.info("[MEMORY_CLIENT] Closed httpx client")

    async def list_knowledge_graphs(self) -> List[Dict[str, Any]]:
        """Fetch all available knowledge graph procedures.

        Returns:
            List of procedures with id, procedure_id, title, object_id
        """
        url = f"{self.base_url}/knowledge-graph/"
        try:
            client = await self._get_client()
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to list knowledge graphs: {e}")
            raise

    async def create_session(self, username: str, procedure_id: str, source_id: str) -> str:
        """Start a new session in Memory Service."""
        url = f"{self.base_url}/sessions/start"
        payload = {
            "username": username,
            "procedure_id": procedure_id,
            "source_id": source_id
        }
        try:
            client = await self._get_client()
            response = await client.post(url, json=payload)
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
            client = await self._get_client()
            response = await client.get(url)
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
            client = await self._get_client()
            # Use shorter timeout for logging - non-critical
            response = await client.post(url, json=payload, timeout=LOGGING_TIMEOUT)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to log item to session {session_id}: {e}")
            # Don't raise - logging failures shouldn't break main flow

    async def get_knowledge_graph(self, procedure_id: str) -> Dict[str, Any]:
        """Fetch knowledge graph procedure from Memory Service.

        Args:
            procedure_id: The procedure ID to fetch

        Returns:
            Knowledge graph response containing 'definition' with nodes
        """
        url = f"{self.base_url}/knowledge-graph/{procedure_id}"
        try:
            client = await self._get_client()
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch knowledge graph {procedure_id}: {e}")
            raise

    async def close_session(self, session_id: str) -> None:
        """Close the session."""
        url = f"{self.base_url}/sessions/{session_id}/close"
        try:
            client = await self._get_client()
            response = await client.post(url)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to close session {session_id}: {e}")
            raise
