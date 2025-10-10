"""State machine for managing user procedure workflows."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Deque, Dict, List, Optional, Tuple
from collections import deque
import time


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
        self._users: Dict[str, UserSession] = {}
        self._on_step = on_step
        self._on_progress = on_progress_step
        self._post_to_vlm = post_to_vlm
        self._max_frames = max_frames_per_user

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
            self._users[username] = UserSession(
                username=username,
                frame_buffer=deque(maxlen=self._max_frames),
            )
        return self._users[username]

    def _current_step_def(self, u: UserSession) -> Optional[StepDef]:
        if not u.procedure or u.current_index >= len(u.procedure.steps):
            return None
        return u.procedure.steps[u.current_index]

    # ---------- public API (call these from your endpoints)

    def start_procedure(self, username: str, procedure: ProcedureDef) -> None:
        """
        Abort any existing work and start fresh on step 0.
        Emits: on_step
        """
        u = self._get_or_create_user(username)
        now = self._now_ms()
        u.state = UserState.WORKING
        u.procedure = procedure
        u.current_index = 0
        step = self._current_step_def(u)
        u.step_rt = self._init_step_rt(step, now) if step else None
        u.inflight = False
        u.frame_buffer.clear()
        if step:
            self._on_step(username, procedure.id, step.id, step.name)

    def pause(self, username: str) -> None:
        u = self._get_or_create_user(username)
        if u.state == UserState.WORKING:
            u.state = UserState.PAUSED

    def resume(self, username: str) -> None:
        u = self._get_or_create_user(username)
        if u.state == UserState.PAUSED:
            u.state = UserState.WORKING
            self._maybe_dispatch(u)

    def abort(self, username: str) -> None:
        u = self._get_or_create_user(username)
        u.state = UserState.ABORTED
        u.inflight = False

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

    def ingest_frame(self, username: str, frame_id: str) -> None:
        """
        Add a frame to the per-user buffer and maybe dispatch to VLM.
        """
        u = self._get_or_create_user(username)
        if u.state != UserState.WORKING:
            return
        if len(u.frame_buffer) == u.frame_buffer.maxlen:
            # drop oldest (deque does this automatically on append)
            pass
        u.frame_buffer.append(frame_id)
        u.last_frame_at_ms = self._now_ms()
        self._maybe_dispatch(u)

    def vlm_decision(self, username: str, frame_id: str, decision: Decision) -> None:
        """
        Handle callback from VLM.
        - Only affects current step.
        - YES increments consecutive counter; others reset it.
        - On target YES count, progress step and emit progress + on_step/complete.
        """
        u = self._get_or_create_user(username)
        if u.state != UserState.WORKING or not u.procedure or not u.step_rt:
            return

        # Guard: consider stale if step id mismatches (frame_id staleness left to transport)
        step = self._current_step_def(u)
        if not step or u.step_rt.id != step.id:
            return

        # Mark inflight done for this user
        u.inflight = False

        if decision == Decision.YES:
            u.step_rt.yes_consecutive += 1
            if u.step_rt.yes_consecutive >= step.debounce_consecutive_yes:
                # Progress to next step (or complete)
                from_id = step.id
                next_index = u.current_index + 1
                if next_index < len(u.procedure.steps):
                    u.current_index = next_index
                    next_step = self._current_step_def(u)
                    u.step_rt = self._init_step_rt(next_step, self._now_ms())
                    self._on_progress(u.username, u.procedure.id, from_id, next_step.id)
                    self._on_step(u.username, u.procedure.id, next_step.id, next_step.name)
                else:
                    # Completed
                    self._on_progress(u.username, u.procedure.id, from_id, None)
                    u.state = UserState.COMPLETED
                    u.step_rt = None
        else:
            # Any non-YES resets
            u.step_rt.yes_consecutive = 0

        # Continue processing if more frames
        self._maybe_dispatch(u)

    def tick(self, username: str) -> None:
        """
        Time-based housekeeping:
        - If step timeout is reached, reset YES streak and re-arm timeout.
          (Does not advance or fail the step in today's simple design.)
        """
        u = self._get_or_create_user(username)
        if u.state != UserState.WORKING or not u.step_rt:
            return

        now = self._now_ms()
        if now >= u.step_rt.timeout_at_ms:
            # Reset debounce and re-arm timeout
            step = self._current_step_def(u)
            if not step:
                return
            u.step_rt.yes_consecutive = 0
            u.step_rt.timeout_at_ms = now + step.timeout_s * 1000

    # ---------- internals

    def _maybe_dispatch(self, u: UserSession) -> None:
        """
        Send the latest frame to VLM if:
          - WORKING
          - not inflight
          - step exists
          - buffer not empty
        """
        if u.state != UserState.WORKING or u.inflight:
            return
        step = self._current_step_def(u)
        if not step or not u.procedure:
            return
        if not u.frame_buffer:
            return

        # Always use the most recent frame for responsiveness
        frame_id = u.frame_buffer[-1]
        u.inflight = True

        # NOTE: You pass your exact VLM contract elsewhere;
        # this just gives you a single call-site to hook into.
        # idem_key could be derived from frame_id or generated here.
        idem_key = frame_id
        self._post_to_vlm(frame_id, u.procedure.id, step_to_dict(step), u.username, idem_key)


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
    steps = [
        StepDef(
            id=st["id"],
            name=st["name"],
            positives=st["positives"],
            negatives=st["negatives"],
            timeout_s=st["timeout_s"],
            debounce_consecutive_yes=st["debounce"]["consecutive_yes"],
        )
        for st in j["steps"]
    ]
    return ProcedureDef(
        id=j["id"],
        name=j["name"],
        version=j["version"],
        steps=steps,
    )