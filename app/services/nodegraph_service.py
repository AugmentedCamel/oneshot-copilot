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
from app.core.nodegraph_client import (
    dispatch_to_nodegraph_ai,
    ingest_frame_async,
    poll_latest_result,
    StepNodeResult
)
from app.config import settings

# Polling interval for async mode (5Hz = 200ms)
POLL_INTERVAL_SECONDS = 0.2

# Hard cap on frame ingestion rate (5 FPS = 200ms minimum between frames)
MIN_INGEST_INTERVAL_SECONDS = 0.2

# Max concurrent in-flight ingestion requests (backpressure limit)
MAX_CONCURRENT_INGESTS = 2

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
        self._polling_tasks: Dict[str, asyncio.Task] = {}  # username -> polling task
        self._last_sequence_ids: Dict[str, int] = {}  # username -> last processed seq_id
        self._last_ingest_time: Dict[str, float] = {}  # username -> last ingest timestamp (5 FPS throttle)
        self._ingest_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INGESTS)  # Backpressure limit
        
        # Timing instrumentation
        self._stats = {
            "frames_received": 0,
            "frames_dispatched": 0,
            "frames_throttled": 0,
            "frames_backpressured": 0,
            "total_http_time_ms": 0,
            "start_time": time.time()
        }
        self._last_frame_event_time = 0.0
        
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
        
        # Start polling loop for async result fetching
        self._last_sequence_ids[username] = -1
        polling_task = asyncio.create_task(self._polling_loop(username))
        self._polling_tasks[username] = polling_task
        logger.info(f"[NODEGRAPH_SERVICE] Started polling loop for {username}")
        
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
        
        # Cancel polling task - don't await to avoid blocking on in-flight HTTP requests
        if username in self._polling_tasks:
            task = self._polling_tasks[username]
            task.cancel()
            # Don't await the task - the HTTP request inside poll_latest_result 
            # may take up to 1s to complete, blocking this stop request.
            # The task cleanup will happen asynchronously.
            del self._polling_tasks[username]
            logger.info(f"[NODEGRAPH_SERVICE] Cancelled polling loop for {username}")
        
        # Clean up sequence tracking
        if username in self._last_sequence_ids:
            del self._last_sequence_ids[username]
        
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
    
    # ========================
    # Control API Methods
    # ========================
    
    def set_auto_progress(self, username: str, enabled: bool) -> bool:
        """Toggle AI-driven auto progression for a user's session.
        
        Args:
            username: The user whose session to modify
            enabled: Whether auto-progression should be enabled
            
        Returns:
            True if session was found and updated, False otherwise
        """
        session = self._active_sessions.get(username)
        if not session:
            return False
        
        session.auto_progress_enabled = enabled
        logger.info(f"[NODEGRAPH_SERVICE] Auto-progress {'enabled' if enabled else 'disabled'} for {username}")
        self._save_session_status(session)
        return True
    
    async def force_next_node(self, username: str) -> Optional[Dict]:
        """Force advance to the next node (on_success transition).
        
        Args:
            username: The user whose session to advance
            
        Returns:
            Dict with new node info, or None if no session/no next node
        """
        session = self._active_sessions.get(username)
        if not session:
            return None
        
        node = session.get_current_node()
        if not node:
            return None
        
        # Check if there's a next node
        if not node.transitions or not node.transitions.on_success:
            logger.warning(f"[NODEGRAPH_SERVICE] No on_success transition for node {node.id}")
            return None
        
        next_node_id = node.transitions.on_success
        
        # Record current node in history before transitioning
        session.visited_nodes.append(session.current_node_id)
        
        # Execute transition using engine
        now_ms = int(time.time() * 1000)
        events = self.engine._execute_transition(session, next_node_id, "manual_next", now_ms)
        
        # Process events
        await self._process_engine_events(session, events)
        
        logger.info(f"[NODEGRAPH_SERVICE] Forced next: {node.id} -> {next_node_id} for {username}")
        return self.engine.get_current_ui(session)
    
    async def force_prev_node(self, username: str) -> Optional[Dict]:
        """Return to the previous node from history.
        
        Args:
            username: The user whose session to revert
            
        Returns:
            Dict with new node info, or None if no session/no history
        """
        session = self._active_sessions.get(username)
        if not session:
            return None
        
        # Check if there's history to go back to
        if not session.visited_nodes:
            logger.warning(f"[NODEGRAPH_SERVICE] No history to go back to for {username}")
            return None
        
        # Pop the last visited node
        prev_node_id = session.visited_nodes.pop()
        current_node_id = session.current_node_id
        
        # Execute transition using engine
        now_ms = int(time.time() * 1000)
        events = self.engine._execute_transition(session, prev_node_id, "manual_prev", now_ms)
        
        # Process events
        await self._process_engine_events(session, events)
        
        logger.info(f"[NODEGRAPH_SERVICE] Forced prev: {current_node_id} -> {prev_node_id} for {username}")
        return self.engine.get_current_ui(session)
    
    def get_control_status(self, username: str) -> Optional[Dict]:
        """Get the current control state for a user's session.
        
        Args:
            username: The user to query
            
        Returns:
            Dict with control state, or None if no session
        """
        session = self._active_sessions.get(username)
        if not session:
            return None
        
        node = session.get_current_node()
        return {
            "username": username,
            "auto_progress_enabled": session.auto_progress_enabled,
            "current_node_id": session.current_node_id,
            "current_node_title": node.ui.title if node else "",
            "visited_nodes_count": len(session.visited_nodes),
            "can_go_prev": len(session.visited_nodes) > 0,
            "can_go_next": node.transitions.on_success is not None if node and node.transitions else False
        }
    
    async def _on_frame_created(self, event: Event) -> None:
        """Handle new frame ingestion."""
        frame: Frame = event.payload.get("frame")
        if not frame:
            return
        
        # Timing instrumentation
        now = time.time()
        frame_interval_ms = (now - self._last_frame_event_time) * 1000 if self._last_frame_event_time > 0 else 0
        self._last_frame_event_time = now
        self._stats["frames_received"] += 1
        
        source_id = frame.source_id
        
        # Find users interested in this source
        target_users = [u for u, s in self._user_sources.items() if s == source_id]
        
        now_ms = int(time.time() * 1000)
        
        for username in target_users:
            if username in self._active_sessions:
                session = self._active_sessions[username]
                
                # Ingest frame into engine (for state tracking)
                events = self.engine.ingest_frame(session, frame.id, now_ms)
                
                # Process events - for async mode we just fire-and-forget the frame
                for e in events:
                    if isinstance(e, NodeGraphDispatchNeeded):
                        # Async mode: submit frame without waiting for response
                        asyncio.create_task(self._ingest_frame_async(session, e))
    
    async def _ingest_frame_async(
        self,
        session: NodeGraphSession,
        event: NodeGraphDispatchNeeded
    ) -> None:
        """Submit frame to AI node asynchronously (fire-and-forget)."""
        # Backpressure: skip frame if too many requests in flight
        if self._ingest_semaphore.locked():
            self._stats["frames_backpressured"] += 1
            logger.info(
                f"[NODEGRAPH_SERVICE] Backpressure: skipping frame for {session.username} "
                f"(max {MAX_CONCURRENT_INGESTS} concurrent, skipped={self._stats['frames_backpressured']})"
            )
            return
        
        async with self._ingest_semaphore:
            await self._do_ingest_frame(session, event)
    
    async def _do_ingest_frame(
        self,
        session: NodeGraphSession,
        event: NodeGraphDispatchNeeded
    ) -> None:
        """Internal: actually perform the frame ingestion (guarded by semaphore)."""
        try:
            # 5 FPS throttle: skip if last ingest was less than 200ms ago
            now = time.time()
            last_ingest = self._last_ingest_time.get(session.username, 0)
            elapsed = now - last_ingest
            
            if elapsed < MIN_INGEST_INTERVAL_SECONDS:
                self._stats["frames_throttled"] += 1
                logger.info(
                    f"[NODEGRAPH_SERVICE] Throttled frame for {session.username}: "
                    f"elapsed={elapsed*1000:.0f}ms < {MIN_INGEST_INTERVAL_SECONDS*1000:.0f}ms "
                    f"(throttled={self._stats['frames_throttled']})"
                )
                return
            
            # Update last ingest time
            self._last_ingest_time[session.username] = now
            
            # Get frame bytes
            frame_bytes = get_frame(event.frame_id)
            if not frame_bytes:
                logger.error(f"[NODEGRAPH_SERVICE] Frame {event.frame_id} not found")
                return
            
            logger.debug(
                f"[NODEGRAPH_SERVICE] Ingesting frame async for {session.username}, "
                f"frame {event.frame_id}, classes={event.target_classes}"
            )
            
            # Submit frame (non-blocking) with timing
            http_start = time.time()
            success = await ingest_frame_async(
                frame_bytes=frame_bytes,
                procedure_id=event.procedure_id,
                user_id=session.username,
                target_classes=event.target_classes,
                excluded_candidates=event.excluded_candidates,
                candidate_scope=event.candidate_scope
            )
            http_elapsed_ms = (time.time() - http_start) * 1000
            self._stats["total_http_time_ms"] += http_elapsed_ms
            self._stats["frames_dispatched"] += 1
            
            # Calculate effective FPS
            total_elapsed = time.time() - self._stats["start_time"]
            effective_fps = self._stats["frames_dispatched"] / total_elapsed if total_elapsed > 0 else 0
            avg_http_ms = self._stats["total_http_time_ms"] / self._stats["frames_dispatched"]
            
            logger.info(
                f"[NODEGRAPH_SERVICE] Frame dispatched for {session.username}: "
                f"http={http_elapsed_ms:.0f}ms, avg_http={avg_http_ms:.0f}ms, "
                f"effective_fps={effective_fps:.1f}, "
                f"dispatched={self._stats['frames_dispatched']}, "
                f"throttled={self._stats['frames_throttled']}, "
                f"backpressured={self._stats['frames_backpressured']}"
            )
            
            if not success:
                logger.warning(f"[NODEGRAPH_SERVICE] Frame ingest failed for {session.username}")
            
        except Exception as e:
            logger.error(f"[NODEGRAPH_SERVICE] Frame ingest error: {e}", exc_info=True)
    
    async def _polling_loop(self, username: str) -> None:
        """Background polling loop for fetching AI results at 5Hz."""
        logger.info(f"[NODEGRAPH_SERVICE] Polling loop started for {username}")
        
        try:
            while True:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                
                # Check if session still exists
                if username not in self._active_sessions:
                    logger.info(f"[NODEGRAPH_SERVICE] Session gone, stopping poll for {username}")
                    break
                
                session = self._active_sessions[username]
                
                # Poll for latest result
                result = await poll_latest_result()
                
                if result is None:
                    # No result available yet or timeout
                    continue
                
                # Check if this is a new result (different sequence_id)
                last_seq = self._last_sequence_ids.get(username, -1)
                if result.sequence_id <= last_seq:
                    # Already processed this result
                    continue
                
                # New result! Update sequence tracker
                self._last_sequence_ids[username] = result.sequence_id
                
                logger.debug(
                    f"[NODEGRAPH_SERVICE] New result for {username}: "
                    f"seq={result.sequence_id}, predictions={result.predictions}"
                )
                
                # Store latest predictions in session (rolling buffer of 3)
                session.latest_predictions.append(result.predictions)
                if len(session.latest_predictions) > 3:
                    session.latest_predictions.pop(0)
                
                # Log predictions to STM (lightweight rolling update)
                await self._log_predictions_to_stm(session, result.predictions)
                
                # Evaluate guards with the predictions (only if auto_progress enabled)
                if session.auto_progress_enabled:
                    now_ms = int(time.time() * 1000)
                    events = self.engine.evaluate_guards(session, result.predictions, now_ms)
                    
                    # Process events
                    await self._process_engine_events(session, events)
                else:
                    logger.debug(f"[NODEGRAPH_SERVICE] Auto-progress disabled for {username}, skipping guard evaluation")
                
        except asyncio.CancelledError:
            logger.info(f"[NODEGRAPH_SERVICE] Polling loop cancelled for {username}")
            raise
        except Exception as e:
            logger.error(f"[NODEGRAPH_SERVICE] Polling loop error for {username}: {e}", exc_info=True)
    
    async def _process_engine_events(
        self,
        session: NodeGraphSession,
        events: List
    ) -> None:
        """Process events from the engine (shared by polling and legacy dispatch)."""
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
                
                # Remove from active (this will also stop the polling loop)
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
    
    async def _log_predictions_to_stm(
        self,
        session: NodeGraphSession,
        predictions: Dict[str, float]
    ) -> None:
        """Log latest AI predictions to STM for agent context.
        
        Formats top 3 predictions as a concise visual state entry.
        Uses a special key so Memory Service can handle as rolling update.
        """
        if not session.external_session_id:
            return
        
        try:
            # Get top 3 predictions by confidence
            sorted_preds = sorted(predictions.items(), key=lambda x: x[1], reverse=True)[:3]
            
            # Format as concise string: "step_03: 0.87, step_02: 0.12, step_01: 0.01"
            pred_str = ", ".join([f"{cls}: {conf:.2f}" for cls, conf in sorted_preds])
            content = f"[visual_state] AI predictions: {pred_str}"
            
            # Log to session (Memory Service will treat visual_state as rolling key)
            await self.strategy.log_event(
                session.external_session_id,
                _PredictionEvent(predictions=predictions, formatted=content)
            )
        except Exception as e:
            logger.error(f"[NODEGRAPH_SERVICE] Failed to log predictions to STM: {e}")
    
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
                "inflight": session.inflight,
                "auto_progress_enabled": session.auto_progress_enabled,
                "visited_nodes_count": len(session.visited_nodes)
            }
        
        return {
            "active_sessions": sessions_data,
            "user_sources": self._user_sources
        }


class _PredictionEvent:
    """Internal event for logging predictions to STM."""
    def __init__(self, predictions: Dict[str, float], formatted: str):
        self.predictions = predictions
        self.formatted = formatted


# Global instance (created lazily when nodegraph strategy is selected)
_nodegraph_service: Optional[NodeGraphProcedureService] = None


def get_nodegraph_service() -> NodeGraphProcedureService:
    """Get or create the global NodeGraphProcedureService instance."""
    global _nodegraph_service
    if _nodegraph_service is None:
        _nodegraph_service = NodeGraphProcedureService()
    return _nodegraph_service
