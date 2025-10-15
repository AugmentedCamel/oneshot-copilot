"""State machine for managing user procedure workflows."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple
import time
import logging

# Import perf_counter for high-precision timing
from time import perf_counter

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
    buffered_frame: Optional[str] = None  # Single buffered frame (overwrite semantics)
    last_frame_at_ms: Optional[int] = None
    # Timing instrumentation for VLM request performance tracking
    frame_ingest_time: Optional[float] = None  # When frame was ingested (perf_counter)
    vlm_dispatch_time: Optional[float] = None  # When frame was dispatched to VLM (perf_counter)
    vlm_response_time: Optional[float] = None  # When VLM response was received (perf_counter)


# ====== State Machine ================================================================

class UserStateMachine:
    """
    A per-user controller with:
      - single in-flight VLM job
      - single frame buffer (overwrites on new frame when inflight)
      - YES-only progression (2 consecutive YES by default)
      - timeout resets debounce (keeps the same step)
    """

    def __init__(
        self,
        on_step: OnStepFn,
        on_progress_step: ProgressStepFn,
        post_to_vlm: PostToVLMFn,
        max_frames_per_user: int = 10,  # Kept for backward compatibility but unused
    ):
        logger.info("Initializing UserStateMachine")
        self._users: Dict[str, UserSession] = {}
        self._on_step = on_step
        self._on_progress = on_progress_step
        self._post_to_vlm = post_to_vlm
        logger.debug("StateMachine initialized with single-frame buffering")

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
            self._users[username] = UserSession(username=username)
            logger.info(f"User session created: username={username}")
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
        u.buffered_frame = None
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
            "has_buffered_frame": u.buffered_frame is not None,
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
        Handle incoming frame:
        - If no request is in-flight, dispatch immediately
        - If request is in-flight, buffer this frame (overwriting any previous buffered frame)
        """
        # [TIMING] Record frame ingest time
        ingest_time = perf_counter()
        
        logger.debug(f"[STATE_MACHINE] Ingesting frame - username={username}, frame_id={frame_id}")
        u = self._get_or_create_user(username)
        if u.state != UserState.WORKING:
            logger.debug(f"Frame ignored (user not WORKING) - username={username}, state={u.state.value}")
            return
        
        # [TIMING] Store ingest timestamp
        u.frame_ingest_time = ingest_time
        logger.info(f"[⏱️ TIMING] Frame ingested - username={username}, frame_id={frame_id}")
        
        u.last_frame_at_ms = self._now_ms()
        
        # If VLM request is in flight, buffer the frame (overwriting previous buffer)
        if u.inflight:
            previous_buffered = u.buffered_frame
            u.buffered_frame = frame_id
            if previous_buffered:
                logger.info(f"[STATE_MACHINE] Frame buffer overwritten - username={username}, old_frame={previous_buffered}, new_frame={frame_id}")
            else:
                logger.info(f"[STATE_MACHINE] Frame buffered while inflight - username={username}, frame_id={frame_id}")
        else:
            # No request in flight, dispatch immediately
            logger.debug(f"[STATE_MACHINE] No inflight request, dispatching immediately - username={username}, frame_id={frame_id}")
            self._maybe_dispatch(u, frame_id)

    def vlm_decision(self, username: str, frame_id: str, decision: Decision) -> None:
        """
        Handle callback from VLM.
        - Only affects current step.
        - YES increments consecutive counter; others reset it.
        - On target YES count, progress step and emit progress + on_step/complete.
        """
        # [TIMING] Record VLM response time
        response_time = perf_counter()
        
        logger.info(f"[STATE_MACHINE] Processing VLM decision - username={username}, frame_id={frame_id}, decision={decision.value}")
        u = self._get_or_create_user(username)
        
        # [TIMING] Calculate and log timing metrics
        if u.frame_ingest_time and u.vlm_dispatch_time:
            u.vlm_response_time = response_time
            
            # Calculate durations
            dispatch_latency = (u.vlm_dispatch_time - u.frame_ingest_time) * 1000  # ms
            vlm_processing_time = (u.vlm_response_time - u.vlm_dispatch_time) * 1000  # ms
            total_latency = (u.vlm_response_time - u.frame_ingest_time) * 1000  # ms
            
            logger.info(f"[⏱️ TIMING] VLM response received - username={username}, frame_id={frame_id}")
            logger.info(f"[⏱️ TIMING] ├─ Ingest → Dispatch: {dispatch_latency:.2f}ms")
            logger.info(f"[⏱️ TIMING] ├─ VLM Processing: {vlm_processing_time:.2f}ms")
            logger.info(f"[⏱️ TIMING] └─ Total (Ingest → Response): {total_latency:.2f}ms")
        else:
            logger.warning(f"[⏱️ TIMING] Incomplete timing data - username={username}, frame_id={frame_id}, has_ingest={u.frame_ingest_time is not None}, has_dispatch={u.vlm_dispatch_time is not None}")
        
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

        # Process buffered frame if available
        if u.buffered_frame:
            buffered_frame_id = u.buffered_frame
            u.buffered_frame = None  # Clear buffer before dispatching
            logger.info(f"[STATE_MACHINE] Processing buffered frame after VLM response - username={username}, buffered_frame={buffered_frame_id}")
            self._maybe_dispatch(u, buffered_frame_id)

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
                # Try to dispatch buffered frame if available
                if u.buffered_frame:
                    buffered_frame_id = u.buffered_frame
                    u.buffered_frame = None  # Clear buffer before dispatching
                    logger.info(f"[STATE_MACHINE] Processing buffered frame after timeout - username={username}, buffered_frame={buffered_frame_id}")
                    self._maybe_dispatch(u, buffered_frame_id)
        
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

    def _maybe_dispatch(self, u: UserSession, frame_id: Optional[str] = None) -> None:
        """
        Send a frame to VLM if:
          - WORKING
          - not inflight
          - step exists
          - frame_id provided or buffered frame available
          - frame hasn't already been dispatched
        """
        if u.state != UserState.WORKING or u.inflight:
            logger.debug(f"Dispatch skipped - username={u.username}, state={u.state.value}, inflight={u.inflight}")
            return
        step = self._current_step_def(u)
        if not step or not u.procedure:
            logger.debug(f"Dispatch skipped (no step/procedure) - username={u.username}")
            return
        
        # Use provided frame_id, or fall back to buffered frame
        if frame_id is None:
            frame_id = u.buffered_frame
            if frame_id:
                u.buffered_frame = None  # Clear buffer since we're dispatching it
                logger.info(f"[STATE_MACHINE] Using buffered frame for dispatch - username={u.username}, frame_id={frame_id}")
        
        if not frame_id:
            logger.debug(f"[STATE_MACHINE] Dispatch skipped - username={u.username}, reason=no_frame_available")
            return

        logger.info(f"[STATE_MACHINE] *** FRAME STATE *** - username={u.username}, dispatching_frame={frame_id}, inflight_frame={u.inflight_frame_id}, has_buffered={u.buffered_frame is not None}")
        
        # CRITICAL: Prevent redispatching the same frame
        if frame_id == u.inflight_frame_id:
            logger.warning(f"[STATE_MACHINE] *** SKIPPING REDISPATCH *** - username={u.username}, frame_id={frame_id} already processed")
            return
        
        now = self._now_ms()
        
        # [TIMING] Record VLM dispatch time
        dispatch_time = perf_counter()
        u.vlm_dispatch_time = dispatch_time
        
        # [TIMING] Log time from ingest to dispatch
        if u.frame_ingest_time:
            time_to_dispatch = (dispatch_time - u.frame_ingest_time) * 1000  # Convert to ms
            logger.info(f"[⏱️ TIMING] Dispatching to VLM - username={u.username}, frame_id={frame_id}, time_since_ingest={time_to_dispatch:.2f}ms")
        else:
            logger.warning(f"[⏱️ TIMING] Dispatch without ingest timestamp - username={u.username}, frame_id={frame_id}")
        
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