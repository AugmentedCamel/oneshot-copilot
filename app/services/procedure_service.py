import logging
import asyncio
from typing import Dict, List, Optional
from collections import deque

from app.domain.models import UserSession, ProcedureDef, UserState
from app.domain.procedure_engine import ProcedureEngine
from app.domain.events import ProcedureCompleted
from app.domain.entities import Event, EventType, Frame
from app.models.procedure import load_procedure
from app.services.ingest_service import ingest_service
from app.services.status_service import save_user_status, load_user_status, delete_user_status
from app.core.event_bus import event_bus

logger = logging.getLogger(__name__)

class ProcedureService:
    def __init__(self):
        self._active_sessions: Dict[str, List[UserSession]] = {}  # username -> list of active sessions
        self._queued_sessions: Dict[str, deque] = {}  # username -> queue of (procedure_id, source_id) tuples
        self._user_sources: Dict[str, str] = {}  # username -> source_id (current active source)
        
        # Initialize engine
        self.engine = ProcedureEngine()
        
        # Subscribe to frame events
        event_bus.subscribe(EventType.FRAME_CREATED, self._on_frame_created)

    def start_procedure(self, username: str, procedure_id: str, source_id: Optional[str] = None, policy: str = "replace") -> Dict:
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
        logger.info(f"Request to start procedure: user={username}, id={procedure_id}, source={source_id}, policy={policy}")
        
        # 1. Resolve Source ID
        if not source_id:
            source_id = self._user_sources.get(username)
            if not source_id:
                # Try to find a default source from ingest service? 
                # For now, require source_id if not already mapped
                # Or maybe we can just pick the first one?
                # Let's fail if ambiguous
                raise ValueError("Source ID is required for new session if not already established.")
        
        # Validate source exists
        source = ingest_service.get_source(source_id)
        if not source:
            raise ValueError(f"Source not found: {source_id}")
            
        # Update user source mapping
        self._user_sources[username] = source_id
        
        # 2. Resolve Procedure Path & Load
        # Assuming procedure_id maps to a file in app/data/procedures
        # e.g. "pizza_custom@v1" -> "pizza_custom.json" (simplified mapping)
        # For now, we'll strip version for filename or just use the ID as filename base
        filename = f"{procedure_id.split('@')[0]}.json"
        try:
            procedure_def = load_procedure(f"app/data/procedures/{filename}")
        except FileNotFoundError:
            raise ValueError(f"Procedure not found: {procedure_id}")
        except Exception as e:
            logger.error(f"Failed to load procedure {procedure_id}: {e}")
            raise ValueError(f"Invalid procedure definition: {e}")

        # 3. Handle Concurrency Policy
        if username not in self._active_sessions:
            self._active_sessions[username] = []
            
        if policy == "replace":
            self._abort_all_sessions(username)
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
        return self._start_session(username, procedure_def, source_id)

    def stop_procedure(self, username: str, procedure_id: str) -> bool:
        """Stop a specific procedure."""
        if username in self._active_sessions:
            for session in self._active_sessions[username]:
                if session.procedure and session.procedure.id == procedure_id:
                    self.engine.abort(session)
                    self._active_sessions[username].remove(session)
                    save_user_status(username, self._session_to_dict(session)) # Save aborted state
                    logger.info(f"Stopped procedure {procedure_id} for user {username}")
                    
                    # Check queue
                    self._check_queue(username)
                    return True
        return False

    def _start_session(self, username: str, procedure_def: ProcedureDef, source_id: str) -> Dict:
        session = UserSession(username=username)
        
        # Start engine
        import time
        now_ms = int(time.time() * 1000)
        events = self.engine.start_procedure(session, procedure_def, now_ms)
        
        # Save session
        self._active_sessions[username].append(session)
        save_user_status(username, self._session_to_dict(session))
        
        logger.info(f"Started procedure {procedure_def.id} for user {username} on source {source_id}")
        return {"status": "started", "procedure_id": procedure_def.id, "session_id": f"{username}_{procedure_def.id}"}

    def _abort_all_sessions(self, username: str):
        """Abort all active sessions for a user."""
        if username in self._active_sessions:
            for session in self._active_sessions[username]:
                self.engine.abort(session)
                # We could save the aborted state if needed
            self._active_sessions[username] = []
            logger.info(f"Aborted all sessions for user {username}")

    def _check_queue(self, username: str):
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
                self.start_procedure(username, next_proc_id, next_source_id, policy="parallel") # Policy doesn't matter here as it's empty

    async def _on_frame_created(self, event: Event):
        """Handle new frame ingestion."""
        frame: Frame = event.payload.get("frame")
        if not frame:
            return

        source_id = frame.source_id
        
        # Find users interested in this source
        # Inefficient O(N) lookup for now, can optimize with reverse map if needed
        target_users = [u for u, s in self._user_sources.items() if s == source_id]
        
        import time
        now_ms = int(time.time() * 1000)
        
        for username in target_users:
            if username in self._active_sessions:
                # Iterate over copy since we might modify list
                for session in list(self._active_sessions[username]):
                    events = self.engine.ingest_frame(session, frame.id, now_ms)
                    
                    # Process events
                    for e in events:
                        if isinstance(e, ProcedureCompleted):
                            logger.info(f"Procedure {e.procedure_id} completed for user {username}")
                            if session in self._active_sessions[username]:
                                self._active_sessions[username].remove(session)
                            
                            # Check queue
                            self._check_queue(username)
                        
                        # TODO: Publish other events to bus?
                        # event_bus.publish(...)

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
