"""State machine for managing user procedure workflows."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Deque, Dict, List, Optional, Tuple
from collections import deque
import time
import logging

logger = logging.getLogger(__name__)

# Import status service for file persistence
try:
    from app.services.status_service import save_user_status, delete_user_status
    _status_service_available = True
except ImportError:
    logger.warning("Status service not available - status files will not be saved")
    _status_service_available = False


# ====== Public types & callbacks =====================================================

class UserState(str, Enum):
    IDLE = "IDLE"
    WORKING = "WORKING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class Decision(str, Enum):
    YES = "YES"
    NO = "NO"
    UNCERTAIN = "UNCERTAIN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


OnStepFn = Callable[[str, str, int, str], None]
# (username, procedure_id, step_id, step_name)

ProgressStepFn = Callable[[str, str, Optional[int], Optional[int]], None]
# (username, procedure_id, from_step_id, to_step_id) ; to_step_id None => finished

PostToVLMFn = Callable[[str, str, Dict, str, str], None]
# (frame_id, procedure_id, step_def, username, idem_key)


# ====== Data models (you load procedures as dicts from your JSON) ====================

@dataclass
class StepDef:
    id: int
    name: str
    positives: List[str]
    negatives: List[str]
    timeout_s: int
    debounce_consecutive_yes: int  # expect 2 for now


@dataclass
class ProcedureDef:
    id: str               # e.g., "pizza_custom@v1"
    name: str
    version: int
    steps: List[StepDef]


@dataclass
class StepRuntime:
    id: int
    started_at_ms: int
    timeout_at_ms: int
    yes_consecutive: int = 0


@dataclass
class UserSession:
    username: str
    state: UserState = UserState.IDLE
    procedure: Optional[ProcedureDef] = None
    current_index: int = 0
    step_rt: Optional[StepRuntime] = None
    inflight: bool = False
    inflight_since_ms: Optional[int] = None  # Track when inflight was set
    inflight_frame_id: Optional[str] = None  # Track which frame is inflight
    frame_buffer: Deque[str] = field(default_factory=lambda: deque(maxlen=10))  # frame_ids
    last_frame_at_ms: Optional[int] = None


# ====== State Machine ================================================================

class UserStateMachine:
    """
    A per-user controller with:
      - single in-flight VLM job
      - ring buffer of frames
      - YES-only progression (2 consecutive YES by default)
      - timeout resets debounce (keeps the same step)
    """

    def __init__(
        self,
        on_step: OnStepFn,
        on_progress_step: ProgressStepFn,
        post_to_vlm: PostToVLMFn,
        max_frames_per_user: int = 10,
    ):
        logger.info("Initializing UserStateMachine")
        self._users: Dict[str, UserSession] = {}
        self._on_step = on_step
        self._on_progress = on_progress_step
        self._post_to_vlm = post_to_vlm
        self._max_frames = max_frames_per_user
        logger.debug(f"StateMachine config: max_frames_per_user={max_frames_per_user}")

    # ---------- helpers

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _init_step_rt(step: StepDef, now_ms: int) -> StepRuntime:
        return StepRuntime(
            id=step.id,
            started_at_ms=now_ms,
            timeout_at_ms=now_ms + step.timeout_s * 1000,
            yes_consecutive=0,
        )

    def _get_or_create_user(self, username: str) -> UserSession:
        if username not in self._users:
            logger.debug(f"Creating new user session: username={username}")
            self._users[username] = UserSession(
                username=username,
                frame_buffer=deque(maxlen=self._max_frames),
            )
            logger.info(f"User session created: username={username}, max_frames={self._max_frames}")
        return self._users[username]

    def _current_step_def(self, u: UserSession) -> Optional[StepDef]:
        if not u.procedure or u.current_index >= len(u.procedure.steps):
            return None
        return u.procedure.steps[u.current_index]

    def _save_status_file(self, username: str) -> None:
        """
        Save the current procedure status to a JSON file.
        Called automatically when status changes.
        """
        if not _status_service_available:
            return
        
        try:
            status_data = self.get_procedure_status(username)
            if status_data:
                save_user_status(username, status_data)
        except Exception as e:
            logger.error(f"Failed to save status file - username={username}, error: {str(e)}", exc_info=True)

    # ---------- public API (call these from your endpoints)

    def start_procedure(self, username: str, procedure: ProcedureDef) -> None:
        """
        Abort any existing work and start fresh on step 0.
        Emits: on_step
        """
        logger.info(f"[STATE_MACHINE] Starting procedure - username={username}, procedure={procedure.id}, steps={len(procedure.steps)}")
        # Delete any existing status file before starting new procedure
        if _status_service_available:
            delete_user_status(username, procedure.id)
        u = self._get_or_create_user(username)
        now = self._now_ms()
        u.state = UserState.WORKING
        u.procedure = procedure
        u.current_index = 0
        step = self._current_step_def(u)
        u.step_rt = self._init_step_rt(step, now) if step else None
        u.inflight = False
        u.frame_buffer.clear()
        logger.debug(f"Procedure state initialized - username={username}, initial_step={step.id if step else None}")
        if step:
            logger.info(f"[STATE_MACHINE] User entered step - username={username}, step_id={step.id}, step_name={step.name}")
            self._on_step(username, procedure.id, step.id, step.name)
            # Save initial status
            self._save_status_file(username)

    def pause(self, username: str) -> None:
        logger.info(f"[STATE_MACHINE] Pausing procedure - username={username}")
        u = self._get_or_create_user(username)
        if u.state == UserState.WORKING:
            u.state = UserState.PAUSED
            logger.debug(f"Procedure paused - username={username}, previous_state=WORKING")
        else:
            logger.warning(f"Pause requested but user not in WORKING state - username={username}, state={u.state.value}")

    def resume(self, username: str) -> None:
        logger.info(f"[STATE_MACHINE] Resuming procedure - username={username}")
        u = self._get_or_create_user(username)
        if u.state == UserState.PAUSED:
            u.state = UserState.WORKING
            logger.debug(f"Procedure resumed - username={username}, new_state=WORKING")
            self._maybe_dispatch(u)
        else:
            logger.warning(f"Resume requested but user not in PAUSED state - username={username}, state={u.state.value}")

    def abort(self, username: str) -> None:
        logger.info(f"[STATE_MACHINE] Aborting procedure - username={username}")
        u = self._get_or_create_user(username)
        previous_state = u.state.value
        u.state = UserState.ABORTED
        u.inflight = False
        logger.debug(f"Procedure aborted - username={username}, previous_state={previous_state}")
        # Save status after abort
        self._save_status_file(username)

    def status(self, username: str) -> Dict:
        u = self._get_or_create_user(username)
        step = self._current_step_def(u)
        return {
            "username": username,
            "state": u.state.value,
            "procedure_id": u.procedure.id if u.procedure else None,
            "current_step_id": step.id if step else None,
            "current_step_name": step.name if step else None,
            "yes_consecutive": u.step_rt.yes_consecutive if u.step_rt else 0,
            "inflight": u.inflight,
            "buffer_len": len(u.frame_buffer),
        }

    def get_procedure_status(self, username: str) -> Optional[Dict]:
        """
        Generate procedure status JSON for a user including username field.
        Returns None if user has no active procedure.
        
        Args:
            username: Username to get status for
            
        Returns:
            Dictionary with username, id, name, version, and steps with status
        """
        u = self._get_or_create_user(username)
        if not u.procedure:
            return None
        
        steps_with_status = []
        for idx, step in enumerate(u.procedure.steps):
            # Determine status based on current_index and state
            if u.state == UserState.COMPLETED:
                status = "done"
            elif idx < u.current_index:
                status = "done"
            elif idx == u.current_index and u.state == UserState.WORKING:
                status = "in_progress"
            else:
                status = "todo"
            
            steps_with_status.append({
                "id": step.id,
                "name": step.name,
                "status": status
            })
        
        return {
            "_comment": "DEBUG FILE: This file is for frontend testing. Edit this manually and call GET /api/procedure?username=dummy to see your changes immediately.",
            "username": username,
            "id": u.procedure.id,
            "name": u.procedure.name,
            "version": u.procedure.version,
            "steps": steps_with_status
        }

    def ingest_frame(self, username: str, frame_id: str) -> None:
        """
        Add a frame to the per-user buffer and maybe dispatch to VLM.
        """
        logger.debug(f"[STATE_MACHINE] Ingesting frame - username={username}, frame_id={frame_id}")
        u = self._get_or_create_user(username)
        if u.state != UserState.WORKING:
            logger.debug(f"Frame ignored (user not WORKING) - username={username}, state={u.state.value}")
            return
        if len(u.frame_buffer) == u.frame_buffer.maxlen:
            oldest_frame = u.frame_buffer[0] if u.frame_buffer else None
            logger.debug(f"Frame buffer full, dropping oldest - username={username}, dropping={oldest_frame}")
        u.frame_buffer.append(frame_id)
        u.last_frame_at_ms = self._now_ms()
        logger.debug(f"Frame added to buffer - username={username}, buffer_size={len(u.frame_buffer)}")
        self._maybe_dispatch(u)

    def vlm_decision(self, username: str, frame_id: str, decision: Decision) -> None:
        """
        Handle callback from VLM.
        - Only affects current step.
        - YES increments consecutive counter; others reset it.
        - On target YES count, progress step and emit progress + on_step/complete.
        """
        logger.info(f"[STATE_MACHINE] Processing VLM decision - username={username}, frame_id={frame_id}, decision={decision.value}")
        u = self._get_or_create_user(username)
        if u.state != UserState.WORKING or not u.procedure or not u.step_rt:
            logger.debug(f"VLM decision ignored - username={username}, state={u.state.value}, has_procedure={u.procedure is not None}, has_step_rt={u.step_rt is not None}")
            return

        # Guard: consider stale if step id mismatches (frame_id staleness left to transport)
        step = self._current_step_def(u)
        if not step or u.step_rt.id != step.id:
            logger.warning(f"VLM decision stale - username={username}, step_mismatch (current={step.id if step else None}, runtime={u.step_rt.id})")
            return

        # Mark inflight done for this user
        # IMPORTANT: Keep inflight_frame_id set to prevent redispatch of same frame
        logger.info(f"[STATE_MACHINE] *** SETTING INFLIGHT=FALSE *** - username={username}, frame_id={frame_id}")
        u.inflight = False
        u.inflight_since_ms = None
        # DO NOT clear inflight_frame_id here - it's used for deduplication in _maybe_dispatch
        logger.debug(f"VLM response received, marking inflight=False - username={username}, keeping inflight_frame_id={u.inflight_frame_id} for deduplication")

        if decision == Decision.YES:
            u.step_rt.yes_consecutive += 1
            logger.debug(f"YES decision - username={username}, consecutive_yes={u.step_rt.yes_consecutive}/{step.debounce_consecutive_yes}")
            if u.step_rt.yes_consecutive >= step.debounce_consecutive_yes:
                # Progress to next step (or complete)
                from_id = step.id
                next_index = u.current_index + 1
                if next_index < len(u.procedure.steps):
                    u.current_index = next_index
                    next_step = self._current_step_def(u)
                    u.step_rt = self._init_step_rt(next_step, self._now_ms())
                    # Clear inflight_frame_id when progressing to new step (old frame no longer relevant)
                    u.inflight_frame_id = None
                    logger.info(f"[STATE_MACHINE] Step progression - username={username}, from_step={from_id}, to_step={next_step.id}, cleared_inflight_frame")
                    self._on_progress(u.username, u.procedure.id, from_id, next_step.id)
                    logger.info(f"[STATE_MACHINE] User entered step - username={username}, step_id={next_step.id}, step_name={next_step.name}")
                    self._on_step(u.username, u.procedure.id, next_step.id, next_step.name)
                    # Save status after step progression
                    self._save_status_file(username)
                else:
                    # Completed
                    logger.info(f"[STATE_MACHINE] Procedure completed - username={username}, final_step={from_id}")
                    self._on_progress(u.username, u.procedure.id, from_id, None)
                    u.state = UserState.COMPLETED
                    u.step_rt = None
                    u.inflight_frame_id = None
                    # Save status after completion
                    self._save_status_file(username)
        else:
            # Any non-YES resets
            previous_count = u.step_rt.yes_consecutive
            u.step_rt.yes_consecutive = 0
            logger.debug(f"{decision.value} decision - username={username}, reset consecutive_yes from {previous_count} to 0")

        # Continue processing if more frames
        self._maybe_dispatch(u)

    def tick(self, username: str) -> None:
        """
        Time-based housekeeping:
        - If step timeout is reached, reset YES streak and re-arm timeout.
          (Does not advance or fail the step in today's simple design.)
        - If VLM request timeout is reached (1 second), clear inflight flag.
        """
        u = self._get_or_create_user(username)
        if u.state != UserState.WORKING:
            return

        now = self._now_ms()
        
        # Check for VLM request timeout (1 second)
        if u.inflight and u.inflight_since_ms is not None:
            elapsed_ms = now - u.inflight_since_ms
            if elapsed_ms > 1000:  # 1 second timeout
                logger.warning(f"[STATE_MACHINE] *** VLM REQUEST TIMEOUT *** - username={username}, frame_id={u.inflight_frame_id}, elapsed_ms={elapsed_ms}")
                logger.warning(f"[STATE_MACHINE] Clearing inflight flag to allow new requests - username={username}")
                u.inflight = False
                u.inflight_since_ms = None
                u.inflight_frame_id = None
                # Try to dispatch next frame if available
                self._maybe_dispatch(u)
        
        # Check for step timeout
        if u.step_rt:
            if now >= u.step_rt.timeout_at_ms:
                # Reset debounce and re-arm timeout
                step = self._current_step_def(u)
                if not step:
                    return
                logger.warning(f"[STATE_MACHINE] Step timeout reached - username={username}, step_id={step.id}, resetting consecutive_yes")
                u.step_rt.yes_consecutive = 0
                u.step_rt.timeout_at_ms = now + step.timeout_s * 1000
                logger.debug(f"Timeout re-armed - username={username}, new_timeout_ms={u.step_rt.timeout_at_ms}")

    # ---------- internals

    def _maybe_dispatch(self, u: UserSession) -> None:
        """
        Send the latest frame to VLM if:
          - WORKING
          - not inflight
          - step exists
          - buffer not empty
          - frame hasn't already been dispatched
        """
        if u.state != UserState.WORKING or u.inflight:
            logger.debug(f"Dispatch skipped - username={u.username}, state={u.state.value}, inflight={u.inflight}")
            return
        step = self._current_step_def(u)
        if not step or not u.procedure:
            logger.debug(f"Dispatch skipped (no step/procedure) - username={u.username}")
            return
        if not u.frame_buffer:
            logger.info(f"[STATE_MACHINE] Dispatch skipped - username={u.username}, reason=empty_buffer, inflight={u.inflight}")
            return

        # Always use the most recent frame for responsiveness
        frame_id = u.frame_buffer[-1]
        logger.info(f"[STATE_MACHINE] *** FRAME BUFFER STATE *** - username={u.username}, buffer_size={len(u.frame_buffer)}, latest_frame={frame_id}, inflight_frame={u.inflight_frame_id}")
        
        # CRITICAL: Prevent redispatching the same frame (buffer deduplication)
        if frame_id == u.inflight_frame_id:
            logger.warning(f"[STATE_MACHINE] *** SKIPPING REDISPATCH *** - username={u.username}, frame_id={frame_id} already processed, removing from buffer")
            # Remove the processed frame from buffer to allow new frames
            if frame_id in u.frame_buffer:
                # Remove all instances of this frame_id from the buffer
                u.frame_buffer = deque([fid for fid in u.frame_buffer if fid != frame_id], maxlen=u.frame_buffer.maxlen)
                logger.info(f"[STATE_MACHINE] Frame removed from buffer - username={u.username}, frame_id={frame_id}, new_buffer_size={len(u.frame_buffer)}")
            return
        now = self._now_ms()
        logger.info(f"[STATE_MACHINE] *** SETTING INFLIGHT=TRUE *** - username={u.username}, frame_id={frame_id}, step_id={step.id}, previous_frame={u.inflight_frame_id}")
        u.inflight = True
        u.inflight_since_ms = now
        # Update inflight_frame_id to the new frame being dispatched
        u.inflight_frame_id = frame_id
        logger.info(f"[STATE_MACHINE] Dispatching frame to VLM - username={u.username}, frame_id={frame_id}, step_id={step.id}")

        # NOTE: You pass your exact VLM contract elsewhere;
        # this just gives you a single call-site to hook into.
        # idem_key could be derived from frame_id or generated here.
        idem_key = frame_id
        logger.info(f"[STATE_MACHINE] *** CALLING VLM POST FUNCTION *** - frame_id={frame_id}, procedure={u.procedure.id}, username={u.username}, idem_key={idem_key}")
        self._post_to_vlm(frame_id, u.procedure.id, step_to_dict(step), u.username, idem_key)
        logger.info(f"[STATE_MACHINE] *** VLM POST FUNCTION RETURNED *** - frame_id={frame_id}, username={u.username}")


# ====== Utilities ===================================================================

def step_to_dict(s: StepDef) -> Dict:
    return {
        "id": s.id,
        "name": s.name,
        "positives": s.positives,
        "negatives": s.negatives,
        "timeout_s": s.timeout_s,
        "debounce": {"consecutive_yes": s.debounce_consecutive_yes},
    }


def procedure_from_json(j: Dict) -> ProcedureDef:
    logger.debug(f"[PROCEDURE_PARSE] Starting to parse procedure JSON - id={j.get('id')}")
    steps = []
    for st in j["steps"]:
        # Check if negatives field exists
        has_negatives = "negatives" in st
        negatives_value = st.get("negatives", [])
        logger.debug(f"[PROCEDURE_PARSE] Parsing step {st['id']}: has_negatives={has_negatives}, using_default={'[]' if not has_negatives else 'from_json'}")
        
        steps.append(StepDef(
            id=st["id"],
            name=st["name"],
            positives=st["positives"],
            negatives=negatives_value,
            timeout_s=st["timeout_s"],
            debounce_consecutive_yes=st["debounce"]["consecutive_yes"],
        ))
    logger.info(f"[PROCEDURE_PARSE] Successfully parsed {len(steps)} steps from JSON")
    return ProcedureDef(
        id=j["id"],
        name=j["name"],
        version=j["version"],
        steps=steps,
    )