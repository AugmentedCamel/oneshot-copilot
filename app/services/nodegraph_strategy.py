"""Node Graph Procedure Strategy.

This strategy loads node graph procedures from the Memory Service
and manages session state for state machine-based procedure execution.
"""
import logging
from typing import Any, Dict

from app.domain.interfaces import ProcedureStrategy
from app.domain.nodegraph_models import (
    NodeGraphProcedureDef, NodeGraphSession, nodegraph_from_json
)
from app.domain.nodegraph_engine import (
    NodeGraphTransitionEvent, NodeGraphCompletedEvent, 
    NodeGraphErrorEvent, NodeGraphDispatchNeeded
)
from app.services.memory_service_client import MemoryServiceClient

logger = logging.getLogger(__name__)


class NodeGraphProcedureStrategy(ProcedureStrategy):
    """Strategy for loading and managing node graph procedures.
    
    Uses the Memory Service's /knowledge-graph endpoint to fetch
    procedure definitions.
    """
    
    def __init__(self, memory_client: MemoryServiceClient):
        self.client = memory_client
    
    async def load_procedure(self, procedure_id: str) -> NodeGraphProcedureDef:
        """Load a node graph procedure from the Memory Service.
        
        Args:
            procedure_id: The procedure ID to load
            
        Returns:
            NodeGraphProcedureDef instance
        """
        logger.info(f"[NODEGRAPH_STRATEGY] Loading procedure {procedure_id} from Memory Service")
        
        try:
            response = await self.client.get_knowledge_graph(procedure_id)
            
            # The response has the procedure in the 'definition' field
            definition = response.get("definition", {})
            
            if not definition:
                raise ValueError(f"No definition found in knowledge graph response")
            
            procedure = nodegraph_from_json(definition)
            
            # Validate
            if not procedure.initial_node_id:
                raise ValueError("Procedure has no initial_node_id")
            if not procedure.nodes:
                raise ValueError("Procedure has no nodes")
            if procedure.initial_node_id not in procedure.nodes:
                raise ValueError(
                    f"initial_node_id '{procedure.initial_node_id}' not found in nodes"
                )
            
            logger.info(
                f"[NODEGRAPH_STRATEGY] Loaded procedure '{procedure.title}' "
                f"with {len(procedure.nodes)} nodes"
            )
            
            return procedure
            
        except Exception as e:
            logger.error(f"[NODEGRAPH_STRATEGY] Failed to load procedure: {e}")
            raise ValueError(f"Could not load knowledge graph {procedure_id}: {e}")
    
    async def initialize_session(
        self, 
        username: str, 
        procedure_id: str, 
        source_id: str
    ) -> str:
        """Initialize a session for the node graph procedure.
        
        Creates a session in the Memory Service and returns the session ID.
        """
        logger.info(f"[NODEGRAPH_STRATEGY] Initializing session for {username}")
        
        try:
            session_id = await self.client.create_session(
                username=username,
                procedure_id=procedure_id,
                source_id=source_id
            )
            logger.info(f"[NODEGRAPH_STRATEGY] Created session {session_id}")
            return session_id
        except Exception as e:
            logger.error(f"[NODEGRAPH_STRATEGY] Failed to create session: {e}")
            raise
    
    async def log_event(self, session_id: str, event: Any) -> None:
        """Log an event to the session.
        
        Filters and formats node graph specific events.
        """
        # Skip dispatch events
        if isinstance(event, NodeGraphDispatchNeeded):
            return
        
        # Format event content
        if isinstance(event, NodeGraphTransitionEvent):
            content = (
                f"event: NodeGraphTransition\n"
                f"procedure_id: {event.procedure_id}\n"
                f"from_node: {event.from_node}\n"
                f"to_node: {event.to_node}\n"
                f"reason: {event.reason}"
            )
        elif isinstance(event, NodeGraphCompletedEvent):
            content = (
                f"event: NodeGraphCompleted\n"
                f"procedure_id: {event.procedure_id}\n"
                f"final_node: {event.final_node}"
            )
        elif isinstance(event, NodeGraphErrorEvent):
            content = (
                f"event: NodeGraphError\n"
                f"procedure_id: {event.procedure_id}\n"
                f"node_id: {event.node_id}\n"
                f"error_class: {event.error_class}\n"
                f"message: {event.message}"
            )
        else:
            content = (
                f"event: {type(event).__name__}\n"
                f"{str(event)}"
            )
        
        try:
            await self.client.add_item_to_session(
                session_id=session_id,
                content=content,
                metadata={"type": type(event).__name__}
            )
        except Exception as e:
            logger.error(f"[NODEGRAPH_STRATEGY] Failed to log event: {e}")
    
    async def close_session(self, session_id: str) -> None:
        """Close the session in the Memory Service."""
        logger.info(f"[NODEGRAPH_STRATEGY] Closing session {session_id}")
        try:
            await self.client.close_session(session_id)
        except Exception as e:
            logger.error(f"[NODEGRAPH_STRATEGY] Failed to close session: {e}")
            raise
