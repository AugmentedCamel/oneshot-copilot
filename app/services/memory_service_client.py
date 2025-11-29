import logging
import httpx
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class MemoryServiceClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')

    def create_session(self, username: str, procedure_id: str, source_id: str) -> str:
        """Start a new session in Memory Service."""
        url = f"{self.base_url}/sessions/start"
        payload = {
            "username": username,
            "procedure_id": procedure_id,
            "source_id": source_id
        }
        try:
            response = httpx.post(url, json=payload, timeout=5.0)
            response.raise_for_status()
            data = response.json()
            return data["session_id"]
        except Exception as e:
            logger.error(f"Failed to create memory session: {e}")
            raise

    def get_procedure(self, procedure_id: str) -> Dict[str, Any]:
        """Fetch procedure definition from Memory Service (LTM)."""
        # Assuming there's an endpoint to get procedure by ID or we query LTM
        # Based on instructions, we might need to query LTM or fetch a resource.
        # For now, let's assume a direct endpoint or a specific query pattern.
        # If no direct endpoint exists, we might need to use /rag/long-term/query
        # But for "loading" a procedure, it should ideally be a direct fetch if known.
        
        # REVISIT: The instructions mention /resources/ingest and /rag/long-term/query.
        # They don't explicitly list "get resource by ID". 
        # However, for this task, I will assume we can fetch it or I'll implement a query.
        # Let's try a hypothetical /procedures/{id} or similar if it existed, 
        # but given the API list, maybe we rely on the procedure being in the codebase 
        # OR we fetch it from LTM.
        
        # The user said: "load the procedure now from memory service instead of from this repo".
        # This implies the procedure is stored there.
        # Let's assume there is an endpoint `GET /procedures/{id}` or we use `POST /rag/long-term/query`
        # to find it.
        # Let's assume a simple GET for now, if it fails we can adjust.
        # Actually, looking at the user request: "fetch the VLM procedure to load in".
        # I will assume `GET /procedures/{id}` exists or I will use a placeholder and ask/adjust.
        # Wait, the user provided API docs:
        # - POST /resources/ingest
        # - POST /rag/long-term/query
        # - POST /sessions/start
        # ...
        # It does NOT show a GET /procedures/{id}.
        # Maybe I should query LTM?
        # "load the procedure now from memory service"
        # I'll implement a method that tries to fetch it. 
        # Let's assume `GET /resources/{id}` or similar might work if "procedure_id" is a resource ID.
        # Or maybe `GET /procedures/{id}` is implied.
        # I will use `GET /procedures/{id}` for now and if it's 404, I'll have to ask or use RAG.
        
        url = f"{self.base_url}/procedures/{procedure_id}" 
        try:
            response = httpx.get(url, timeout=5.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch procedure {procedure_id}: {e}")
            raise

    def add_item_to_session(self, session_id: str, content: str, metadata: Optional[Dict] = None) -> None:
        """Add an item to the STM session."""
        url = f"{self.base_url}/sessions/{session_id}/items"
        payload = {
            "content": content,
            "metadata": metadata or {}
        }
        try:
            response = httpx.post(url, json=payload, timeout=2.0) # Short timeout for logging
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to log item to session {session_id}: {e}")
            # We might not want to raise here to avoid breaking the main flow just because logging failed
            
    def close_session(self, session_id: str) -> None:
        """Close the session."""
        url = f"{self.base_url}/sessions/{session_id}/close"
        try:
            response = httpx.post(url, timeout=5.0)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to close session {session_id}: {e}")
            raise
