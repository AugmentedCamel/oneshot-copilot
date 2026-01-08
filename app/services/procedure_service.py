import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from collections import deque

from app.domain.models import UserSession, ProcedureDef, UserState, Decision
from app.domain.procedure_engine import ProcedureEngine
from app.domain.events import ProcedureCompleted, VLMDispatchNeeded, VLMResponseReceived
from app.domain.entities import Event, EventType, Frame
from app.services.ingest_service import ingest_service
from app.services.status_service import save_user_status, load_user_status, delete_user_status
from app.core.event_bus import event_bus
from app.core.frame_store import get_frame
from app.core.vlm_client import post_to_vlm_multipart
from app.config import settings
from app.services.rule_validation import RuleValidationService
from app.services.context_analysis import ContextAnalysisService
from app.services.procedure_strategy import LocalFileProcedureStrategy, MemoryBasedProcedureStrategy
from app.services.memory_service_client import MemoryServiceClient
from app.core.ai_node_client import dispatch_to_ai_node, is_reasoning_mode

logger = logging.getLogger(__name__)

class ProcedureService:
    def __init__(self):
        self._active_sessions: Dict[str, List[UserSession]] = {}  # username -> list of active sessions
        self._queued_sessions: Dict[str, deque] = {}  # username -> queue of (procedure_id, source_id) tuples
        self._user_sources: Dict[str, str] = {}  # username -> source_id (current active source)
        
        # Initialize engine and services
        self.engine = ProcedureEngine()
        self.rule_validator = RuleValidationService()
        self.context_analyzer = ContextAnalysisService()
        
        # Initialize Strategy
        if settings.PROCEDURE_STRATEGY == "memory":
            logger.info(f"Using MemoryBasedProcedureStrategy with URL: {settings.MEMORY_SERVICE_URL}")
            memory_client = MemoryServiceClient(settings.MEMORY_SERVICE_URL)
            self.strategy = MemoryBasedProcedureStrategy(memory_client)
        else:
            logger.info("Using LocalFileProcedureStrategy")
            self.strategy = LocalFileProcedureStrategy()
        
        # Subscribe to frame events
        event_bus.subscribe(EventType.FRAME_CREATED, self._on_frame_created)
        logger.info("[PROCEDURE_SERVICE] Initialized")

    async def start_procedure(self, username: str, procedure_id: str, source_id: Optional[str] = None, policy: str = "replace") -> Dict:
        """
        Start a procedure for a user.
        
        Args:
            username: The user starting the procedure.
            procedure_id: The ID of the procedure to start.
            source_id: Optional source ID. If not provided, tries to use existing or default.
            policy: Concurrency policy ("replace", "parallel", "queue").
            
        Returns:
            Dict with status and session details.
        """
        # 1. Resolve Source ID - default to username if not provided
        if not source_id:
            # First try existing mapping, then default to username
            source_id = self._user_sources.get(username) or username

        # Validate source exists
        source = ingest_service.get_source(source_id)
        if not source:
            all_source_ids = [s.id for s in ingest_service.get_all_sources()]
            raise ValueError(f"Source not found: {source_id}. Available: {all_source_ids}")

        # Update user source mapping
        self._user_sources[username] = source_id
        
        # 2. Resolve Procedure Path & Load via Strategy
        try:
            procedure_def = await self.strategy.load_procedure(procedure_id)
        except Exception as e:
            logger.error(f"Failed to load procedure {procedure_id}: {e}")
            raise ValueError(f"Invalid procedure definition: {e}")

        # 3. Handle Concurrency Policy
        if username not in self._active_sessions:
            self._active_sessions[username] = []
            
        if policy == "replace":
            await self._abort_all_sessions(username)
        elif policy == "queue":
            # If there are active sessions, queue this one
            if self._active_sessions[username]:
                if username not in self._queued_sessions:
                    self._queued_sessions[username] = deque()
                self._queued_sessions[username].append((procedure_id, source_id))
                logger.info(f"Queued procedure {procedure_id} for user {username}")
                return {"status": "queued", "position": len(self._queued_sessions[username])}
        elif policy == "parallel":
            # Do nothing, just add to active
            pass
        else:
            raise ValueError(f"Unknown policy: {policy}")

        # 4. Start Session
        return await self._start_session(username, procedure_def, source_id)

    async def stop_procedure(self, username: str, procedure_id: str) -> bool:
        """Stop a specific procedure."""
        if username in self._active_sessions:
            for session in self._active_sessions[username]:
                if session.procedure and session.procedure.id == procedure_id:
                    self.engine.abort(session)
                    self._active_sessions[username].remove(session)
                    save_user_status(username, self._session_to_dict(session)) # Save aborted state
                    logger.info(f"Stopped procedure {procedure_id} for user {username}")
                    
                    # Close external session if applicable
                    if session.external_session_id:
                        await self.strategy.close_session(session.external_session_id)
                    
                    # Check queue
                    await self._check_queue(username)
                    return True
        return False

    def get_session_by_external_id(self, external_session_id: str) -> Optional[UserSession]:
        """Find an active session by its external session ID."""
        for sessions in self._active_sessions.values():
            for session in sessions:
                if session.external_session_id == external_session_id:
                    return session
        return None

    async def _start_session(self, username: str, procedure_def: ProcedureDef, source_id: str) -> Dict:
        session = UserSession(username=username)
        
        # Initialize external session via strategy
        try:
            external_session_id = await self.strategy.initialize_session(username, procedure_def.id, source_id)
            session.external_session_id = external_session_id
            logger.info(f"Initialized external session {external_session_id} for user {username}")
        except Exception as e:
            logger.error(f"Failed to initialize external session: {e}")
            # Continue without external session or fail? 
            # For now, log and continue, but maybe we should fail if strategy is memory?
            if settings.PROCEDURE_STRATEGY == "memory":
                logger.warning("Continuing without external session ID despite memory strategy.")

        # Start engine
        import time
        now_ms = int(time.time() * 1000)
        events = self.engine.start_procedure(session, procedure_def, now_ms)
        
        # Save session
        self._active_sessions[username].append(session)
        save_user_status(username, self._session_to_dict(session))
        
        # Log initial events
        if session.external_session_id:
            for e in events:
                 await self.strategy.log_event(session.external_session_id, e)
        
        logger.info(f"Started procedure {procedure_def.id} for user {username} on source {source_id}")
        return {
            "status": "started", 
            "procedure_id": procedure_def.id, 
            "session_id": f"{username}_{procedure_def.id}",
            "external_session_id": session.external_session_id
        }

    async def _abort_all_sessions(self, username: str):
        """Abort all active sessions for a user."""
        if username in self._active_sessions:
            for session in self._active_sessions[username]:
                self.engine.abort(session)
                if session.external_session_id:
                    await self.strategy.close_session(session.external_session_id)
                # We could save the aborted state if needed
            self._active_sessions[username] = []
            logger.info(f"Aborted all sessions for user {username}")

    async def _check_queue(self, username: str):
        """Check if we can promote a queued session."""
        if username in self._queued_sessions and self._queued_sessions[username]:
            # Simple logic: if no active sessions, pop from queue
            # Or should queue run in parallel with others? 
            # Usually queue implies "wait until free". 
            # Let's assume queue waits until ALL active sessions are done (strict serial)
            # OR we could have named queues? For now, strict serial for "queue" policy items.
            if not self._active_sessions.get(username):
                next_proc_id, next_source_id = self._queued_sessions[username].popleft()
                logger.info(f"Promoting queued procedure {next_proc_id} for user {username}")
                await self.start_procedure(username, next_proc_id, next_source_id, policy="parallel") # Policy doesn't matter here as it's empty

    async def _on_frame_created(self, event: Event):
        """Handle new frame ingestion."""
        frame: Frame = event.payload.get("frame")
        if not frame:
            return

        source_id = frame.source_id

        # Find users interested in this source
        target_users = [u for u, s in self._user_sources.items() if s == source_id]

        if not target_users:
            return

        import time
        now_ms = int(time.time() * 1000)

        for username in target_users:
            if username in self._active_sessions:
                sessions = list(self._active_sessions[username])
                # Iterate over copy since we might modify list
                for session in sessions:
                    events = self.engine.ingest_frame(session, frame.id, now_ms)
                    
                    # Process events
                    for e in events:
                        # Log event to strategy
                        if session.external_session_id:
                            await self.strategy.log_event(session.external_session_id, e)

                        if isinstance(e, ProcedureCompleted):
                            logger.info(f"Procedure {e.procedure_id} completed for user {username}")
                            if session in self._active_sessions[username]:
                                self._active_sessions[username].remove(session)
                            
                            # Close external session
                            if session.external_session_id:
                                await self.strategy.close_session(session.external_session_id)

                            # Check queue
                            await self._check_queue(username)
                        
                        elif isinstance(e, VLMDispatchNeeded):
                            logger.info(f"Dispatching VLM for user {username}, frame {e.frame_id}")
                            asyncio.create_task(self._handle_vlm_dispatch(session, e))
                        
                        # TODO: Publish other events to bus?
                        # event_bus.publish(...)

    async def _handle_vlm_dispatch(self, session: UserSession, event: VLMDispatchNeeded):
        """Execute VLM call and handle result."""
        try:
            logger.debug(f"Starting VLM dispatch for {session.username}, frame {event.frame_id}")
            # 1. Get Frame
            frame_bytes = get_frame(event.frame_id)
            if not frame_bytes:
                logger.error(f"Frame {event.frame_id} not found for VLM dispatch")
                # Reset inflight if frame missing
                session.inflight = False
                return

            # 2. Prepare VLM Args
            step_def = event.step_def
            
            # === DEBUG: Log step_def to trace step_context ===
            logger.info(f"[VLM_DISPATCH_DEBUG] step_def keys: {list(step_def.keys())}")
            logger.info(f"[VLM_DISPATCH_DEBUG] step_context present: {'step_context' in step_def and step_def['step_context'] is not None}")
            logger.info(f"[VLM_DISPATCH_DEBUG] is_reasoning_mode(): {is_reasoning_mode()}")
            if step_def.get("step_context"):
                logger.info(f"[VLM_DISPATCH_DEBUG] step_context value: {step_def['step_context']}")
            
            # Check if we should use async reasoning mode
            step_context = step_def.get("step_context")
            reasoning_mode = is_reasoning_mode()
            logger.info(f"[VLM_DISPATCH_DEBUG] DECISION CHECK: reasoning_mode={reasoning_mode}, step_context_present={step_context is not None and bool(step_context)}")
            logger.info(f"[VLM_DISPATCH_DEBUG] VLM_STRATEGY setting = '{settings.VLM_STRATEGY}'")
            if is_reasoning_mode() and step_context:
                # =====================================================
                # ASYNC REASONING MODE: Fire-and-forget to ai_node
                # =====================================================
                from app.domain.models import ReasoningConfig, CouncilMember, CouncilConfig
                
                # Reconstruct CouncilConfig from dict if present
                council_config = None
                if step_context.get("council"):
                    council_data = step_context["council"]
                    members = []
                    for m in council_data.get("members", []):
                        members.append(CouncilMember(
                            role=m["role"],
                            prompt=m["prompt"],
                            attention=m.get("attention", "PRIMARY"),
                            weight=m.get("weight", 1.0)
                        ))
                    council_config = CouncilConfig(
                        members=members,
                        reasoning_rules=council_data.get("reasoning_rules", {})
                    )
                
                # Reconstruct ReasoningConfig from dict
                rc = ReasoningConfig(
                    step_id=step_context.get("step_id", str(step_def.get("id"))),
                    instruction=step_context.get("instruction", ""),
                    council=council_config
                )
                
                metadata = {
                    "username": session.username,
                    "session_id": session.external_session_id or "unknown",
                    "frame_id": event.frame_id
                }
                
                success = await dispatch_to_ai_node(
                    frame_bytes=frame_bytes,
                    metadata=metadata,
                    reasoning_config=rc
                )
                
                if success:
                    logger.info(f"[REASONING] Frame dispatched to ai_node for {session.username}")
                    # Reset inflight immediately - don't wait for callback
                    # This allows continuous frame streaming at ~5 FPS
                    session.inflight = False
                    session.inflight_since_ms = None
                    import time
                    session.last_dispatch_ms = int(time.time() * 1000)
                else:
                    logger.warning(f"[REASONING] Failed to dispatch frame to ai_node for {session.username}")
                    # Reset inflight so next frame can try
                    session.inflight = False
                    session.inflight_since_ms = None
                
                # State update will happen in callback - don't process here
                return
            
            # =====================================================
            # LEGACY SYNC MODE: Wait for VLM response
            # =====================================================
            question = step_def.get("positives", ["Is this correct?"])[0] 
            
            negatives = step_def.get("negatives", [])
            bounding_questions = step_def.get("bounding_questions", [])
            debug = event.debug
            
            # 3. Call VLM
            logger.debug(f"Sending request to VLM for {session.username}...")
            response_json, _, _ = await post_to_vlm_multipart(
                file_bytes=frame_bytes,
                question=question,
                negatives=negatives,
                vlm_url=settings.VLM_URL,
                bounding_questions=bounding_questions,
                debug=debug
            )
            logger.debug(f"Received VLM response for {session.username}")
            
            # 4. Parse Decision
            # Expect standardized envelope: {"data": {"final": "YES", ...}, "raw": ...}
            data = response_json.get("data", {})
            decision_str = data.get("final") or data.get("decision")
            
            # Fallback for legacy/migration safety (check top-level)
            if not decision_str:
                decision_str = response_json.get("final") or response_json.get("result")
            
            decision = Decision.parse(decision_str)
                
            logger.info(f"VLM Decision for {session.username}: {decision.value}")
            
            # 5. Handle Decision in Engine
            import time
            now_ms = int(time.time() * 1000)
            
            events = self.engine.handle_vlm_decision(
                session=session,
                frame_id=event.frame_id,
                decision=decision,
                vlm_response=response_json,
                rule_validator=self.rule_validator,
                context_analyzer=self.context_analyzer,
                now_ms=now_ms
            )
            
            # 6. Process Resulting Events
            for e in events:
                # Log event to strategy
                if session.external_session_id:
                    await self.strategy.log_event(session.external_session_id, e)

                if isinstance(e, ProcedureCompleted):
                    logger.info(f"Procedure {e.procedure_id} completed for user {session.username}")
                    if session in self._active_sessions.get(session.username, []):
                        self._active_sessions[session.username].remove(session)
                    
                    # Close external session
                    if session.external_session_id:
                        await self.strategy.close_session(session.external_session_id)

                    await self._check_queue(session.username)
                elif isinstance(e, VLMDispatchNeeded):
                    # Handle chained dispatch (e.g. from buffered frame)
                    logger.info(f"Dispatching VLM for user {session.username}, frame {e.frame_id} (buffered)")
                    asyncio.create_task(self._handle_vlm_dispatch(session, e))
            
            # 7. Log VLM Response Event
            # Extract bounding box info
            bounding_boxes = response_json.get("data", {}).get("bounding_boxes", [])
            # If it's a dict (legacy/local), flatten it
            bb_items = []
            bb_count = 0
            if isinstance(bounding_boxes, dict):
                for k, v in bounding_boxes.items():
                    count = len(v) if isinstance(v, list) else 1
                    bb_count += count
                    bb_items.append(f"{k} ({count})")
            elif isinstance(bounding_boxes, list):
                bb_count = len(bounding_boxes)
                # Try to guess items if possible, or just say "items"
                # For now, just list count
                bb_items.append(f"items ({bb_count})")
            
            bb_items_str = ", ".join(bb_items) if bb_items else "None"

            # Get raw answer
            raw_answer = response_json.get("data", {}).get("result") or response_json.get("answer", "")

            # Create event
            vlm_event = VLMResponseReceived(
                username=session.username,
                timestamp=datetime.utcnow().isoformat() + "Z",
                vlm_goal=question,
                vlm_raw_answer=raw_answer,
                bounding_boxes_detected=bb_count,
                bounding_box_items=bb_items_str,
                progress_decision=decision.value,
                procedure_id=session.procedure.id,
                session_id=session.external_session_id or "unknown"
            )
            
            # Log to strategy
            if session.external_session_id:
                await self.strategy.log_event(session.external_session_id, vlm_event)

            # 8. Save State
            save_user_status(session.username, self._session_to_dict(session))
            logger.info(f"Saved user status for {session.username} after VLM dispatch")
            
        except Exception as e:
            logger.error(f"Error handling VLM dispatch for {session.username}: {e}", exc_info=True)
            # Should we reset inflight?
            session.inflight = False
            session.inflight_since_ms = None
            save_user_status(session.username, self._session_to_dict(session))

    # Helper to serialize session (duplicate of vlm_callback logic, should refactor)
    def _session_to_dict(self, session: UserSession) -> Dict:
        # ... (Reuse logic from vlm_callback or import it if possible)
        # For now, minimal implementation to satisfy save_user_status
        from app.api.vlm_callback import session_to_dict
        return session_to_dict(session)

    def get_debug_state(self) -> Dict:
        """Return internal state for debugging."""
        active_sessions_data = {}
        for username, sessions in self._active_sessions.items():
            active_sessions_data[username] = [self._session_to_dict(s) for s in sessions]
            
        queued_sessions_data = {}
        for username, queue in self._queued_sessions.items():
            queued_sessions_data[username] = list(queue)
            
        return {
            "active_sessions": active_sessions_data,
            "queued_sessions": queued_sessions_data,
            "user_sources": self._user_sources
        }

# Global instance
procedure_service = ProcedureService()
