import logging
import json
import os
from typing import Any, Dict, List
from app.domain.interfaces import ProcedureStrategy
from app.domain.events import VLMResponseReceived, StepProgressed, ProcedureCompleted, VLMDispatchNeeded
from app.models.procedure import load_procedure, procedure_from_json
from app.services.memory_service_client import MemoryServiceClient

logger = logging.getLogger(__name__)

class LocalFileProcedureStrategy(ProcedureStrategy):
    async def load_procedure(self, procedure_id: str) -> Any:
        # Existing logic: procedure_id maps to filename
        filename = f"{procedure_id.split('@')[0]}.json"
        path = f"app/data/procedures/{filename}"
        try:
            return load_procedure(path)
        except FileNotFoundError:
            logger.error(f"Procedure file not found: {path}")
            raise ValueError(f"Procedure not found: {procedure_id}")

    async def initialize_session(self, username: str, procedure_id: str, source_id: str) -> str:
        # Local strategy doesn't need external session initialization
        # We can return a dummy ID or just use the username/proc_id combination locally
        return f"local-{username}-{procedure_id}"

    async def log_event(self, session_id: str, event: Any) -> None:
        # Local strategy might just log to console or file
        pass

    async def close_session(self, session_id: str) -> None:
        pass
    
    async def list_available_procedures(self) -> List[Dict[str, Any]]:
        """List all available local procedures by scanning the procedures directory."""
        procedures_dir = "app/data/procedures"
        result = []
        
        try:
            for filename in os.listdir(procedures_dir):
                if filename.endswith(".json"):
                    procedure_id = filename.replace(".json", "")
                    filepath = os.path.join(procedures_dir, filename)
                    try:
                        with open(filepath, "r") as f:
                            data = json.load(f)
                            title = data.get("title", procedure_id)
                            result.append({"procedure_id": procedure_id, "title": title})
                    except Exception as e:
                        logger.warning(f"Could not read procedure file {filename}: {e}")
        except FileNotFoundError:
            logger.warning(f"Procedures directory not found: {procedures_dir}")
        
        return result


class MemoryBasedProcedureStrategy(ProcedureStrategy):
    def __init__(self, memory_client: MemoryServiceClient):
        self.client = memory_client

    async def load_procedure(self, procedure_id: str) -> Any:
        logger.info(f"Loading procedure {procedure_id} from Memory Service")
        try:
            proc_json = await self.client.get_procedure(procedure_id)
            
            # Handle wrapped response from Memory Service
            if isinstance(proc_json, dict) and "definition" in proc_json:
                logger.debug(f"Unwrapping procedure definition for {procedure_id}")
                proc_json = proc_json["definition"]
            
            # === VALIDATION: Check if procedure has step_context fields ===
            steps = proc_json.get("steps", [])
            steps_with_context = sum(1 for s in steps if s.get("step_context"))
            total_steps = len(steps)
            
            if total_steps > 0 and steps_with_context == 0:
                error_msg = (
                    f"Procedure '{procedure_id}' from memory does not match the current procedure logic. "
                    f"The procedure is missing 'step_context' fields required for ai_node reasoning. "
                    f"Please start a different procedure file or re-upload this procedure with step_context/council configuration."
                )
                logger.error(f"[PROCEDURE_VALIDATION] {error_msg}")
                raise ValueError(error_msg)
            elif steps_with_context < total_steps:
                logger.warning(
                    f"[PROCEDURE_VALIDATION] Procedure '{procedure_id}' has partial step_context: "
                    f"{steps_with_context}/{total_steps} steps have council config"
                )
            else:
                logger.info(f"[PROCEDURE_VALIDATION] ✓ Procedure '{procedure_id}' has step_context on all {total_steps} steps")
                
            return procedure_from_json(proc_json)
        except Exception as e:
            logger.error(f"Failed to load procedure from memory: {e}")
            raise ValueError(f"Could not load procedure {procedure_id} from memory service: {e}")

    async def initialize_session(self, username: str, procedure_id: str, source_id: str) -> str:
        logger.info(f"Initializing memory session for {username}")
        return await self.client.create_session(username, procedure_id, source_id)

    async def log_event(self, session_id: str, event: Any) -> None:
        # Filter out VLMDispatchNeeded
        if isinstance(event, VLMDispatchNeeded):
            return

        # Convert event to string or dict
        if isinstance(event, VLMResponseReceived):
            content = (
                f"session_id: {event.session_id}\n"
                f"procedure_id: {event.procedure_id}\n"
                f"timestamp: {event.timestamp}\n"
                f"vlm_goal: {event.vlm_goal}\n"
                f"vlm_raw_answer: {event.vlm_raw_answer}\n"
                f"bounding boxes detected: {event.bounding_boxes_detected}\n"
                f"bounding box item: {event.bounding_box_items}\n"
                f"progress_decision: {event.progress_decision}"
            )
        elif isinstance(event, StepProgressed):
            content = (
                f"session_id: {session_id}\n"
                f"procedure_id: {event.procedure_id}\n"
                f"event: StepProgressed\n"
                f"from_step: {event.from_step}\n"
                f"to_step: {event.to_step}"
            )
        elif isinstance(event, ProcedureCompleted):
            content = (
                f"session_id: {session_id}\n"
                f"procedure_id: {event.procedure_id}\n"
                f"event: ProcedureCompleted\n"
                f"final_step: {event.final_step}"
            )
        else:
            # Default format for other events
            content = (
                f"session_id: {session_id}\n"
                f"event: {type(event).__name__}\n"
                f"{str(event)}"
            )
            
        await self.client.add_item_to_session(session_id, content, metadata={"type": type(event).__name__})

    async def close_session(self, session_id: str) -> None:
        logger.info(f"Closing memory session {session_id}")
        await self.client.close_session(session_id)
    
    async def list_available_procedures(self) -> List[Dict[str, Any]]:
        """List available procedures from the Memory Service."""
        # This strategy doesn't support the knowledge graph listing
        # Return empty list - clients should use nodegraph strategy for discovery
        logger.warning("MemoryBasedProcedureStrategy does not support listing procedures")
        return []
