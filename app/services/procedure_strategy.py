import logging
import json
from typing import Any, Dict
from app.domain.interfaces import ProcedureStrategy
from app.models.procedure import load_procedure, procedure_from_json
from app.services.memory_service_client import MemoryServiceClient

logger = logging.getLogger(__name__)

class LocalFileProcedureStrategy(ProcedureStrategy):
    def load_procedure(self, procedure_id: str) -> Any:
        # Existing logic: procedure_id maps to filename
        filename = f"{procedure_id.split('@')[0]}.json"
        path = f"app/data/procedures/{filename}"
        try:
            return load_procedure(path)
        except FileNotFoundError:
            logger.error(f"Procedure file not found: {path}")
            raise ValueError(f"Procedure not found: {procedure_id}")

    def initialize_session(self, username: str, procedure_id: str, source_id: str) -> str:
        # Local strategy doesn't need external session initialization
        # We can return a dummy ID or just use the username/proc_id combination locally
        return f"local-{username}-{procedure_id}"

    def log_event(self, session_id: str, event: Any) -> None:
        # Local strategy might just log to console or file
        pass

    def close_session(self, session_id: str) -> None:
        pass


class MemoryBasedProcedureStrategy(ProcedureStrategy):
    def __init__(self, memory_client: MemoryServiceClient):
        self.client = memory_client

    def load_procedure(self, procedure_id: str) -> Any:
        logger.info(f"Loading procedure {procedure_id} from Memory Service")
        try:
            proc_json = self.client.get_procedure(procedure_id)
            return procedure_from_json(proc_json)
        except Exception as e:
            logger.error(f"Failed to load procedure from memory: {e}")
            raise ValueError(f"Could not load procedure {procedure_id} from memory service")

    def initialize_session(self, username: str, procedure_id: str, source_id: str) -> str:
        logger.info(f"Initializing memory session for {username}")
        return self.client.create_session(username, procedure_id, source_id)

    def log_event(self, session_id: str, event: Any) -> None:
        # Convert event to string or dict
        # For now, let's just log the string representation
        content = str(event)
        self.client.add_item_to_session(session_id, content, metadata={"type": type(event).__name__})

    def close_session(self, session_id: str) -> None:
        logger.info(f"Closing memory session {session_id}")
        self.client.close_session(session_id)
