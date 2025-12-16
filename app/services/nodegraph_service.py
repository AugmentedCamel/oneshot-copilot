"""Node Graph Procedure Service.

Orchestrates node graph procedure execution, handling frame ingestion,
AI dispatch, and state transitions.
"""
import logging
import asyncio
import time
from typing import Dict, List, Optional

from app.domain.nodegraph_models import NodeGraphProcedureDef, NodeGraphSession
from app.domain.nodegraph_engine import (
    NodeGraphEngine, NodeGraphDispatchNeeded, 
    NodeGraphCompletedEvent, NodeGraphTransitionEvent, NodeGraphErrorEvent
)
from app.domain.events import StatusChanged
from app.domain.entities import Event, EventType, Frame
from app.services.nodegraph_strategy import NodeGraphProcedureStrategy
from app.services.memory_service_client import MemoryServiceClient
from app.services.ingest_service import ingest_service
from app.services.status_service import save_user_status
from app.core.event_bus import event_bus
from app.core.frame_store import get_frame
from app.core.nodegraph_client import dispatch_to_nodegraph_ai
from app.config import settings

logger = logging.getLogger(__name__)


class NodeGraphProcedureService:
    """Service for managing node graph procedure execution.
    
    Handles:
    - Session lifecycle (start, stop)
    - Frame ingestion and AI dispatch
    - State transitions based on AI predictions
    """
    
    def __init__(self):
        self._active_sessions: Dict[str, NodeGraphSession] = {}  # username -> session
        self._user_sources: Dict[str, str] = {}  # username -> source_id
        
        # Initialize engine and strategy
        self.engine = NodeGraphEngine()
        memory_client = MemoryServiceClient(settings.MEMORY_SERVICE_URL)
        self.strategy = NodeGraphProcedureStrategy(memory_client)
        
        # Subscribe to frame events
        event_bus.subscribe(EventType.FRAME_CREATED, self._on_frame_created)
        
        logger.info("[NODEGRAPH_SERVICE] Initialized NodeGraphProcedureService")
    
    async def start_procedure(
        self, 
        username: str, 
        procedure_id: str, 
        source_id: Optional[str] = None
    ) -> Dict:
        """Start a node graph procedure for a user.
        
        Args:
            username: The user starting the procedure
            procedure_id: The procedure ID to start
            source_id: Frame source ID (required for new sessions)
            
        Returns:
            Dict with status and session details
        """
        logger.info(f"[NODEGRAPH_SERVICE] Starting procedure {procedure_id} for {username}")
        
        # Resolve source ID
        if not source_id:
            source_id = self._user_sources.get(username)
            if not source_id:
                raise ValueError("Source ID is required for new session")
        
        # Validate source exists
        source = ingest_service.get_source(source_id)
        if not source:
            raise ValueError(f"Source not found: {source_id}")
        
        # Update user source mapping
        self._user_sources[username] = source_id
        
        # Stop any existing session for this user
        if username in self._active_sessions:
            await self.stop_procedure(username)
        
        # Load procedure from memory service
        try:
            procedure = await self.strategy.load_procedure(procedure_id)
        except Exception as e:
            logger.error(f"[NODEGRAPH_SERVICE] Failed to load procedure: {e}")
            raise ValueError(f"Invalid procedure: {e}")
        
        # Create session in memory service
        try:
            external_session_id = await self.strategy.initialize_session(
                username, procedure_id, source_id
            )
        except Exception as e:
            logger.warning(f"[NODEGRAPH_SERVICE] Failed to create external session: {e}")
            external_session_id = f"local-{username}-{procedure_id}"
        
        # Create local session
        session = NodeGraphSession(
            username=username,
            procedure=procedure,
            current_node_id=procedure.initial_node_id,
            external_session_id=external_session_id
        )
        
        # Start procedure in engine
        now_ms = int(time.time() * 1000)
        events = self.engine.start_procedure(session, now_ms)
        
        # Save session
        self._active_sessions[username] = session
        self._save_session_status(session)
        
        # Log events to strategy
        for event in events:
            await self.strategy.log_event(external_session_id, event)
        
        logger.info(
            f"[NODEGRAPH_SERVICE] Started {procedure.title} for {username} "
            f"at node {session.current_node_id}"
        )
        
        return {
            "status": "started",
            "procedure_id": procedure_id,
            "session_id": f"{username}_{procedure_id}",
            "external_session_id": external_session_id,
            "current_node": self.engine.get_current_ui(session)
        }
    
    async def stop_procedure(self, username: str) -> bool:
        """Stop the active procedure for a user."""
        if username not in self._active_sessions:
            return False
        
        session = self._active_sessions[username]
        
        # Close external session
        if session.external_session_id:
            try:
                await self.strategy.close_session(session.external_session_id)
            except Exception as e:
                logger.error(f"[NODEGRAPH_SERVICE] Failed to close session: {e}")
        
        # Remove from active sessions
        del self._active_sessions[username]
        
        logger.info(f"[NODEGRAPH_SERVICE] Stopped procedure for {username}")
        return True
    
    def get_session(self, username: str) -> Optional[NodeGraphSession]:
        """Get the active session for a user."""
        return self._active_sessions.get(username)
    
    async def _on_frame_created(self, event: Event) -> None:
        """Handle new frame ingestion."""
        frame: Frame = event.payload.get("frame")
        if not frame:
            return
        
        source_id = frame.source_id
        
        # Find users interested in this source
        target_users = [u for u, s in self._user_sources.items() if s == source_id]
        
        now_ms = int(time.time() * 1000)
        
        for username in target_users:
            if username in self._active_sessions:
                session = self._active_sessions[username]
                
                # Ingest frame
                events = self.engine.ingest_frame(session, frame.id, now_ms)
                
                # Process events
                for e in events:
                    if isinstance(e, NodeGraphDispatchNeeded):
                        # Handle AI dispatch synchronously
                        asyncio.create_task(self._handle_ai_dispatch(session, e))
    
    async def _handle_ai_dispatch(
        self, 
        session: NodeGraphSession, 
        event: NodeGraphDispatchNeeded
    ) -> None:
        """Execute AI dispatch and process predictions."""
        try:
            # Get frame bytes
            frame_bytes = get_frame(event.frame_id)
            if not frame_bytes:
                logger.error(f"[NODEGRAPH_SERVICE] Frame {event.frame_id} not found")
                session.inflight = False
                return
            
            logger.debug(
                f"[NODEGRAPH_SERVICE] Dispatching AI for {session.username}, "
                f"frame {event.frame_id}, classes={event.target_classes}"
            )
            
            # Call AI service (synchronous wait for response)
            predictions = await dispatch_to_nodegraph_ai(
                frame_bytes=frame_bytes,
                user_id=session.username,
                frame_id=event.frame_id,
                procedure_id=event.procedure_id,
                target_classes=event.target_classes
            )
            
            # Evaluate guards and get resulting events
            now_ms = int(time.time() * 1000)
            events = self.engine.evaluate_guards(session, predictions, now_ms)
            
            # Process events
            for e in events:
                # Log to strategy
                if session.external_session_id:
                    await self.strategy.log_event(session.external_session_id, e)
                
                if isinstance(e, NodeGraphCompletedEvent):
                    logger.info(
                        f"[NODEGRAPH_SERVICE] Procedure {e.procedure_id} "
                        f"completed for {session.username}"
                    )
                    # Close session
                    if session.external_session_id:
                        try:
                            await self.strategy.close_session(session.external_session_id)
                        except Exception as ex:
                            logger.error(f"Failed to close session: {ex}")
                    
                    # Remove from active
                    if session.username in self._active_sessions:
                        del self._active_sessions[session.username]
                
                elif isinstance(e, NodeGraphTransitionEvent):
                    logger.info(
                        f"[NODEGRAPH_SERVICE] Transition: {e.from_node} -> {e.to_node}"
                    )
                
                elif isinstance(e, NodeGraphErrorEvent):
                    logger.warning(
                        f"[NODEGRAPH_SERVICE] Error: {e.error_class} - {e.message}"
                    )
                    # TODO: Send feedback to user
            
            # Save session status
            self._save_session_status(session)
            
        except Exception as e:
            logger.error(f"[NODEGRAPH_SERVICE] AI dispatch failed: {e}", exc_info=True)
            session.inflight = False
    
    def _save_session_status(self, session: NodeGraphSession) -> None:
        """Save session status for persistence."""
        node = session.get_current_node()
        status_data = {
            "username": session.username,
            "id": session.procedure.procedure_id,  # Required by save_user_status
            "procedure_title": session.procedure.title,
            "current_node_id": session.current_node_id,
            "current_node_title": node.ui.title if node else "",
            "current_node_instruction": node.ui.instruction if node else "",
            "validation_buffer_size": len(session.validation_buffer),
            "action_timer_active": session.action_timer_start is not None,
            "external_session_id": session.external_session_id
        }
        save_user_status(session.username, status_data)
    
    def get_debug_state(self) -> Dict:
        """Return internal state for debugging."""
        sessions_data = {}
        for username, session in self._active_sessions.items():
            node = session.get_current_node()
            sessions_data[username] = {
                "procedure_id": session.procedure.procedure_id,
                "current_node_id": session.current_node_id,
                "current_node_title": node.ui.title if node else "",
                "validation_buffer": session.validation_buffer,
                "action_timer_start": session.action_timer_start,
                "inflight": session.inflight
            }
        
        return {
            "active_sessions": sessions_data,
            "user_sources": self._user_sources
        }


# Global instance (created lazily when nodegraph strategy is selected)
_nodegraph_service: Optional[NodeGraphProcedureService] = None


def get_nodegraph_service() -> NodeGraphProcedureService:
    """Get or create the global NodeGraphProcedureService instance."""
    global _nodegraph_service
    if _nodegraph_service is None:
        _nodegraph_service = NodeGraphProcedureService()
    return _nodegraph_service
