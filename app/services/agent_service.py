import logging
import httpx
from app.domain.entities import Event, EventType
from app.core.event_bus import event_bus
from app.services.procedure_service import procedure_service
from app.config import settings

logger = logging.getLogger(__name__)

class AgentService:
    def __init__(self):
        self.memory_service_url = settings.MEMORY_SERVICE_URL
        event_bus.subscribe(EventType.QUESTION_ASKED, self._on_question_asked)
        logger.info("AgentService initialized and subscribed to QUESTION_ASKED")

    async def _on_question_asked(self, event: Event):
        """Handle incoming question events from the audio pipeline."""
        try:
            question_text = event.payload.get("question")
            source_id = event.source_id
            
            if not question_text:
                logger.warning("Received QUESTION_ASKED event without question text")
                return

            logger.info(f"Processing question: '{question_text}' from source {source_id}")

            # 1. Resolve User - check both services based on strategy
            username = None
            external_session_id = None
            procedure_name = None
            step_number = None
            step_name = None
            step_action = None

            # Check which strategy is active
            if settings.PROCEDURE_STRATEGY == "nodegraph":
                # Use NodeGraph service for session lookup
                from app.services.nodegraph_service import get_nodegraph_service
                nodegraph_svc = get_nodegraph_service()

                # Reverse lookup in nodegraph_service._user_sources
                for user, src in nodegraph_svc._user_sources.items():
                    if src == source_id:
                        username = user
                        break

                if username:
                    # Get session from nodegraph service
                    ng_session = nodegraph_svc.get_session(username)
                    if ng_session:
                        external_session_id = ng_session.external_session_id
                        procedure_name = ng_session.procedure.title if ng_session.procedure else None
                        node = ng_session.get_current_node()
                        if node:
                            step_name = node.ui.title
                            step_action = node.ui.instruction
                            # Step number is the position in visited_nodes + 1 (current)
                            step_number = len(ng_session.visited_nodes) + 1
                        logger.info(f"Found NodeGraph session {external_session_id} for user {username}")
            else:
                # Use legacy procedure service
                for user, src in procedure_service._user_sources.items():
                    if src == source_id:
                        username = user
                        break

                if username:
                    sessions = procedure_service._active_sessions.get(username)
                    if sessions:
                        session = sessions[0]
                        external_session_id = session.external_session_id
                        if session.procedure:
                            procedure_name = session.procedure.name
                            if 0 <= session.current_index < len(session.procedure.steps):
                                step = session.procedure.steps[session.current_index]
                                step_name = step.name
                                step_number = session.current_index + 1
                                # Legacy steps don't have an action field
                                step_action = None
                        logger.info(f"Found legacy session {external_session_id} for user {username}")
            
            if not username:
                # Fallback: use source_id as username
                logger.warning(f"Could not map source_id {source_id} to a username. Using source_id '{source_id}' as username.")
                username = source_id

            # Session already resolved above
            if not external_session_id:
                logger.info(f"No active session for user {username}. Sending ambient question.")

            # 3. Call Memory Service
            if external_session_id:
                # Session context was resolved above based on strategy
                payload = {
                    "query": question_text,
                    "username": username,
                    "session_id": external_session_id,
                    "procedure_name": procedure_name,
                    "step_number": step_number,
                    "step_name": step_name,
                    "step_action": step_action
                }
                await self.call_memory_agent(payload)
            else:
                logger.info(f"No active session for user {username}. Ambient questions are disabled. Ignoring.")

        except Exception as e:
            logger.error(f"Error in AgentService._on_question_asked: {e}", exc_info=True)

    async def call_memory_agent(self, payload: dict):
        """Call the Memory Service /agent/assist endpoint."""
        url = f"{self.memory_service_url}/agent/assist"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=30.0)
                response.raise_for_status()
                data = response.json()
                answer = data.get("answer") or data.get("result") or data
                logger.warning(f"Agent Answer: {answer}")
                
                # Send answer back to client via FeedbackService
                username = payload.get("username")
                if username and isinstance(answer, str):
                    from app.services.feedback_service import feedback_service
                    await feedback_service.send_agent_reply(username, answer)
                    
        except httpx.HTTPError as e:
            logger.error(f"Failed to call Memory Service: {e}")

agent_service = AgentService()
