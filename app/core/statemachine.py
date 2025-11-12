"""State machine for managing user procedure workflows."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple
import time
import logging

# Import rule models
from app.models.rules import RuleDef, RuleValidationResult, FailureBehavior

# Import perf_counter for high-precision timing
from time import perf_counter

logger = logging.getLogger(__name__)

# Import status service for file persistence
try:
    from app.services.status_service import save_user_status, delete_user_status, delete_all_user_status
    _status_service_available = True
except ImportError:
    logger.warning("Status service not available - status files will not be saved")
    _status_service_available = False

# Import context analysis service
try:
    from app.services.context_analysis import ContextAnalysisService
    _context_analysis_available = True
except ImportError:
    logger.warning("Context analysis service not available")
    _context_analysis_available = False

# Import rule validation service
try:
    from app.services.rule_validation import RuleValidationService
    _rule_validation_available = True
except ImportError:
    logger.warning("Rule validation service not available")
    _rule_validation_available = False


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

PostToVLMFn = Callable[[str, str, Dict, str, str, bool], None]
# (frame_id, procedure_id, step_def, username, idem_key, debug)


# ====== Data models (you load procedures as dicts from your JSON) ====================

@dataclass
class StepDef:
    id: int
    name: str
    positives: List[str]
    negatives: List[str]
    timeout_s: int
    debounce_consecutive_yes: int  # expect 2 for now
    bounding_questions: List[str] = field(default_factory=list)  # optional: items to detect bounding boxes for
    debug: bool = False  # optional: enable debug logging to file
    rules: List[RuleDef] = field(default_factory=list)  # optional: validation rules for this step
    
    def has_rules(self) -> bool:
        """Check if this step has any rules defined."""
        return len(self.rules) > 0
    
    def get_blocking_rules(self) -> List[RuleDef]:
        """Get all rules with BLOCK failure behavior."""
        return [
            rule for rule in self.rules
            if rule.enabled and rule.failure_behavior == FailureBehavior.BLOCK
        ]


@dataclass
class ProcedureDef:
    id: str               # e.g., "pizza_custom@v1"
    name: str
    version: int
    steps: List[StepDef]


@dataclass
class RuleRuntime:
    """Runtime state for rule validation."""
    results: List[RuleValidationResult] = field(default_factory=list)
    last_validation_ms: Optional[int] = None
    
    def has_blocking_failures(self) -> bool:
        """Check if any rule results are blocking failures."""
        return any(r.is_blocking() for r in self.results)


@dataclass
class StepRuntime:
    id: int
    started_at_ms: int
    timeout_at_ms: int
    yes_consecutive: int = 0
    rule_runtime: Optional[RuleRuntime] = None


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
    last_feedback_sent_ms: Optional[int] = None  # Track last feedback time


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
        
        # Initialize context analysis service if available
        if _context_analysis_available:
            self._context_analysis = ContextAnalysisService()
            logger.info("Context analysis service initialized")
        else:
            self._context_analysis = None
            logger.warning("Context analysis service not available")
        
        # Initialize rule validation service if available
        if _rule_validation_available:
            self._rule_validation = RuleValidationService()
            logger.info("Rule validation service initialized")
        else:
            self._rule_validation = None
            logger.warning("Rule validation service not available")
        
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
        # Delete ALL existing status files for this username before starting new procedure
        # This ensures clean state when switching between procedures
        if _status_service_available:
            deleted_count = delete_all_user_status(username)
            logger.info(f"[STATE_MACHINE] Cleaned up {deleted_count} old status file(s) for username={username}")
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
            # DISABLED: Don't send feedback on step transitions, only on errors
            # self._on_step(username, procedure.id, step.id, step.name)
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

    def vlm_decision(self, username: str, frame_id: str, decision: Decision, vlm_response: Optional[Dict] = None) -> None:
        """
        Handle callback from VLM.
        - Only affects current step.
        - YES increments consecutive counter; others reset it.
        - On target YES count, progress step and emit progress + on_step/complete.
        
        Args:
            username: Username for the session
            frame_id: Frame ID that was processed
            decision: Decision enum (YES/NO/UNCERTAIN/NOT_APPLICABLE)
            vlm_response: Optional full VLM response data for context analysis
        """
        # [TIMING] Record VLM response time and start of decision processing
        response_time = perf_counter()
        decision_start = perf_counter()
        
        logger.info(f"[STATE_MACHINE] Processing VLM decision - username={username}, frame_id={frame_id}, decision={decision.value}")
        u = self._get_or_create_user(username)
        
        # DEBUG: Print VLM response structure received by state machine
        if vlm_response:
            print(f"\n{'='*80}")
            print(f"[STATE_MACHINE] VLM RESPONSE RECEIVED:")
            print(f"  Response keys: {list(vlm_response.keys())}")
            if "response" in vlm_response:
                resp = vlm_response.get("response", {})
                print(f"  response keys: {list(resp.keys())}")
                if "raw_json" in resp:
                    raw = resp.get("raw_json", {})
                    print(f"  response.raw_json keys: {list(raw.keys())}")
                    if "bounding_results" in raw:
                        br = raw.get("bounding_results", [])
                        print(f"  response.raw_json.bounding_results: {len(br)} item(s)")
                        if br:
                            print(f"  First bounding_result sample: {br[0]}")
            print(f"{'='*80}\n")
        else:
            print(f"\n[STATE_MACHINE] WARNING: No vlm_response provided to state machine\n")
        
        # Print step info with rule status
        step = self._current_step_def(u)
        if step:
            has_rules = step.has_rules()
            rule_count = len(step.rules) if has_rules else 0
            print(f"\n[VLM DECISION] Step: '{step.name}' | Decision: {decision.value} | Has Rules: {has_rules} ({rule_count} rule(s))")

        # Perform context analysis if VLM response data is available and service is initialized
        if vlm_response and self._context_analysis:
            try:
                print(f"[STATE_MACHINE] → Passing VLM response to context analysis service")
                step_def = self._current_step_def(u)
                step_name = step_def.name if step_def else None
                self._context_analysis.analyze(
                    username=username,
                    frame_id=frame_id,
                    vlm_response=vlm_response,
                    step_name=step_name
                )
                print(f"[STATE_MACHINE] ✓ Context analysis completed")
            except Exception as e:
                logger.error(f"[VLM_DECISION] Context analysis failed - error={str(e)}", exc_info=True)
                print(f"[STATE_MACHINE] ✗ Context analysis failed: {str(e)}")
                # Continue with decision processing even if analysis fails
        
        # Perform rule validation if VLM response data is available, service is initialized, and step has rules
        step = self._current_step_def(u)
        print(f"\n[DEBUG] Checking rule validation conditions:")
        print(f"  - step exists: {step is not None}")
        print(f"  - step.has_rules(): {step.has_rules() if step else 'N/A'}")
        print(f"  - vlm_response provided: {vlm_response is not None}")
        print(f"  - self._rule_validation initialized: {self._rule_validation is not None}")
        if step and step.has_rules() and vlm_response and self._rule_validation:
            try:
                print(f"\n{'='*80}")
                print(f"[RULE VALIDATION] Step '{step.name}' has {len(step.rules)} rule(s) - starting validation")
                print(f"{'='*80}\n")
                logger.info(f"[VLM_DECISION] Validating {len(step.rules)} rule(s) for step {step.name}")
                
                # Initialize rule_runtime if needed
                if u.step_rt and u.step_rt.rule_runtime is None:
                    u.step_rt.rule_runtime = RuleRuntime()
                
                # Build context dictionary for rule validation
                context = {
                    "username": username,
                    "frame_id": frame_id,
                    "step_name": step.name,
                    "step_id": step.id,
                    "vlm_response": vlm_response
                }
                
                print(f"[STATE_MACHINE] → Passing context to rule validation service:")
                print(f"  - vlm_response present: {vlm_response is not None}")
                print(f"  - vlm_response type: {type(vlm_response)}")
                print(f"  - context keys: {list(context.keys())}")
                
                # Validate rules
                validation_start_ms = self._now_ms()
                results = self._rule_validation.validate_rules(step.rules, context)
                validation_duration_ms = self._now_ms() - validation_start_ms
                
                # Store results in step runtime
                if u.step_rt and u.step_rt.rule_runtime:
                    u.step_rt.rule_runtime.results = results
                    u.step_rt.rule_runtime.last_validation_ms = validation_duration_ms
                
                # Log summary of rule validation results
                blocking_failures = [r for r in results if r.is_blocking()]
                if blocking_failures:
                    failed_names = [r.rule_name for r in blocking_failures]
                    print(f"\n{'!'*80}")
                    print(f"[RULE VALIDATION] ❌ {len(blocking_failures)} BLOCKING RULE(S) FAILED:")
                    for r in blocking_failures:
                        print(f"  - Rule: {r.rule_name}")
                        print(f"    Status: {r.status.value}")
                        print(f"    Message: {r.message}")
                    print(f"{'!'*80}\n")
                    logger.warning(
                        f"[VLM_DECISION] {len(blocking_failures)} blocking rule(s) failed - "
                        f"username={username}, step={step.name}, failed={failed_names}"
                    )
                    
                    # NEW: Send feedback to client when step looks complete but rules block it
                    # Only send if decision is YES (user thinks step is done) and enough time has passed
                    current_time_ms = self._now_ms()
                    time_since_last_feedback = (
                        (current_time_ms - u.last_feedback_sent_ms)
                        if u.last_feedback_sent_ms is not None
                        else float('inf')
                    )
                    
                    should_send_feedback = (
                        decision == Decision.YES and
                        time_since_last_feedback >= 4000  # 4 seconds throttle
                    )
                    
                    if should_send_feedback and self._on_step:
                        u.last_feedback_sent_ms = current_time_ms
                        
                        # Build feedback message based on rule type
                        failure = blocking_failures[0]  # Use first failure
                        
                        # Customize message based on rule name
                        if 'cluster' in failure.rule_name.lower():
                            # Extract target from rule parameters if available
                            target = "the items"
                            # Get target from details if available (set by rule handler)
                            if failure.details and 'target' in failure.details:
                                target = failure.details['target']
                            feedback_message = f"Please do not cluster the {target}"
                        else:
                            # Generic fallback
                            feedback_message = f"Issue detected: {failure.message}"
                        
                        try:
                            # Send feedback using existing on_step callback (sends text to client)
                            self._on_step(username, u.procedure.id, step.id, feedback_message)
                            logger.info(
                                f"[FEEDBACK] Sent to client - username={username}, "
                                f"step={step.name}, message='{feedback_message}'"
                            )
                        except Exception as e:
                            logger.error(
                                f"[FEEDBACK] Failed to send - username={username}, "
                                f"error={str(e)}"
                            )
                else:
                    print(f"\n{'='*80}")
                    print(f"[RULE VALIDATION] ✓ ALL RULES PASSED - step can progress")
                    print(f"{'='*80}\n")
                    logger.info(f"[VLM_DECISION] All rules passed - username={username}, step={step.name}")
                    
            except Exception as e:
                logger.error(f"[VLM_DECISION] Rule validation failed - error={str(e)}", exc_info=True)
                # Continue with decision processing even if rule validation fails
        
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
        
        # [TIMING] Check state validity
        state_check_start = perf_counter()
        if u.state != UserState.WORKING or not u.procedure or not u.step_rt:
            state_check_ms = (perf_counter() - state_check_start) * 1000
            logger.debug(f"VLM decision ignored - username={username}, state={u.state.value}, has_procedure={u.procedure is not None}, has_step_rt={u.step_rt is not None}, check_duration={state_check_ms:.3f}ms")
            return
        state_check_ms = (perf_counter() - state_check_start) * 1000

        # Guard: consider stale if step id mismatches (frame_id staleness left to transport)
        step = self._current_step_def(u)
        if not step or u.step_rt.id != step.id:
            logger.warning(f"VLM decision stale - username={username}, step_mismatch (current={step.id if step else None}, runtime={u.step_rt.id})")
            return

        # [TIMING] Mark inflight done for this user
        inflight_update_start = perf_counter()
        # IMPORTANT: Keep inflight_frame_id set to prevent redispatch of same frame
        logger.info(f"[STATE_MACHINE] *** SETTING INFLIGHT=FALSE *** - username={username}, frame_id={frame_id}")
        u.inflight = False
        u.inflight_since_ms = None
        # DO NOT clear inflight_frame_id here - it's used for deduplication in _maybe_dispatch
        logger.debug(f"VLM response received, marking inflight=False - username={username}, keeping inflight_frame_id={u.inflight_frame_id} for deduplication")
        inflight_update_ms = (perf_counter() - inflight_update_start) * 1000

        # [TIMING] Process decision logic
        decision_logic_start = perf_counter()
        if decision == Decision.YES:
            u.step_rt.yes_consecutive += 1
            logger.debug(f"YES decision - username={username}, consecutive_yes={u.step_rt.yes_consecutive}/{step.debounce_consecutive_yes}")
            if u.step_rt.yes_consecutive >= step.debounce_consecutive_yes:
                # Check if rules block progression before advancing
                rules_block_progression = False
                if u.step_rt and u.step_rt.rule_runtime and u.step_rt.rule_runtime.has_blocking_failures():
                    rules_block_progression = True
                    blocking_failures = [r for r in u.step_rt.rule_runtime.results if r.is_blocking()]
                    failed_names = [r.rule_name for r in blocking_failures]
                    print(f"\n{'🛑'*40}")
                    print(f"[PROGRESSION BLOCKED] Cannot advance to next step!")
                    print(f"  Step: {step.name}")
                    print(f"  Consecutive YES: {u.step_rt.yes_consecutive}/{step.debounce_consecutive_yes}")
                    print(f"  Failed Rules: {', '.join(failed_names)}")
                    print(f"{'🛑'*40}\n")
                    logger.warning(
                        f"[STATE_MACHINE] Step progression BLOCKED by rules - "
                        f"username={username}, step={step.name}, consecutive_yes={u.step_rt.yes_consecutive}, "
                        f"failed_rules={failed_names}"
                    )
                    # Keep consecutive_yes at threshold - don't reset, but don't advance either
                
                if not rules_block_progression:
                    # [TIMING] Progress to next step (or complete)
                    step_progress_start = perf_counter()
                    print(f"\n{'✓'*40}")
                    print(f"[PROGRESSION ALLOWED] Advancing to next step")
                    print(f"  Current Step: {step.name}")
                    print(f"  Consecutive YES: {u.step_rt.yes_consecutive}/{step.debounce_consecutive_yes}")
                    print(f"  Rules: All passed or no blocking failures")
                    print(f"{'✓'*40}\n")
                    logger.info(f"[STATE_MACHINE] Step progression - rules passed, advancing to next step")
                    from_id = step.id
                    next_index = u.current_index + 1
                    if next_index < len(u.procedure.steps):
                        u.current_index = next_index
                        u.last_feedback_sent_ms = None  # Reset feedback tracking for new step
                        next_step = self._current_step_def(u)
                        u.step_rt = self._init_step_rt(next_step, self._now_ms())
                        # Clear inflight_frame_id when progressing to new step (old frame no longer relevant)
                        u.inflight_frame_id = None
                        logger.info(f"[STATE_MACHINE] Step progression - username={username}, from_step={from_id}, to_step={next_step.id}, cleared_inflight_frame")
                        self._on_progress(u.username, u.procedure.id, from_id, next_step.id)
                        logger.info(f"[STATE_MACHINE] User entered step - username={username}, step_id={next_step.id}, step_name={next_step.name}")
                        # DISABLED: Don't send feedback on step transitions, only on errors
                        # self._on_step(u.username, u.procedure.id, next_step.id, next_step.name)
                        # Save status after step progression
                        self._save_status_file(username)
                        step_progress_ms = (perf_counter() - step_progress_start) * 1000
                        logger.info(f"[⏱️ TIMING] Step progression completed - duration={step_progress_ms:.3f}ms")
                    else:
                        # Completed
                        logger.info(f"[STATE_MACHINE] Procedure completed - username={username}, final_step={from_id}")
                        self._on_progress(u.username, u.procedure.id, from_id, None)
                        u.state = UserState.COMPLETED
                        u.last_feedback_sent_ms = None  # Reset feedback tracking on completion
                        u.step_rt = None
                        u.inflight_frame_id = None
                        # Save status after completion
                        self._save_status_file(username)
                        step_progress_ms = (perf_counter() - step_progress_start) * 1000
                        logger.info(f"[⏱️ TIMING] Procedure completion processing - duration={step_progress_ms:.3f}ms")
        else:
            # Any non-YES resets
            previous_count = u.step_rt.yes_consecutive
            u.step_rt.yes_consecutive = 0
            logger.debug(f"{decision.value} decision - username={username}, reset consecutive_yes from {previous_count} to 0")
        
        decision_logic_ms = (perf_counter() - decision_logic_start) * 1000

        # [TIMING] Process buffered frame if available
        buffer_process_start = perf_counter()
        if u.buffered_frame:
            buffered_frame_id = u.buffered_frame
            u.buffered_frame = None  # Clear buffer before dispatching
            logger.info(f"[STATE_MACHINE] Processing buffered frame after VLM response - username={username}, buffered_frame={buffered_frame_id}")
            self._maybe_dispatch(u, buffered_frame_id)
        buffer_process_ms = (perf_counter() - buffer_process_start) * 1000
        
        # [TIMING] Log total decision processing time with breakdown
        total_decision_ms = (perf_counter() - decision_start) * 1000
        logger.info(f"[⏱️ TIMING] ========== DECISION PROCESSING BREAKDOWN ==========")
        logger.info(f"[⏱️ TIMING] State Check:          {state_check_ms:7.3f}ms")
        logger.info(f"[⏱️ TIMING] Inflight Update:      {inflight_update_ms:7.3f}ms")
        logger.info(f"[⏱️ TIMING] Decision Logic:       {decision_logic_ms:7.3f}ms")
        logger.info(f"[⏱️ TIMING] Buffer Processing:    {buffer_process_ms:7.3f}ms")
        logger.info(f"[⏱️ TIMING] TOTAL DECISION:       {total_decision_ms:7.3f}ms")
        logger.info(f"[⏱️ TIMING] =====================================================")

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
        
        # Check for VLM request timeout (2.5 seconds, aligned with HTTP client timeout)
        if u.inflight and u.inflight_since_ms is not None:
            elapsed_ms = now - u.inflight_since_ms
            if elapsed_ms > 2500:  # 2.5 second timeout (aligned with HTTP_TIMEOUT)
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
        debug = step.debug if step else False
        logger.info(f"[STATE_MACHINE] *** CALLING VLM POST FUNCTION *** - frame_id={frame_id}, procedure={u.procedure.id}, username={u.username}, idem_key={idem_key}, debug={debug}")
        self._post_to_vlm(frame_id, u.procedure.id, step_to_dict(step), u.username, idem_key, debug)
        logger.info(f"[STATE_MACHINE] *** VLM POST FUNCTION RETURNED *** - frame_id={frame_id}, username={u.username}")


# ====== Utilities ===================================================================

def step_to_dict(s: StepDef) -> Dict:
    # Serialize rules to dict format
    rules_data = []
    for rule in s.rules:
        rules_data.append({
            "rule_type": rule.rule_type.value,
            "name": rule.name,
            "enabled": rule.enabled,
            "failure_behavior": rule.failure_behavior.value,
            "params": rule.params
        })
    
    return {
        "id": s.id,
        "name": s.name,
        "positives": s.positives,
        "negatives": s.negatives,
        "bounding_questions": s.bounding_questions,
        "timeout_s": s.timeout_s,
        "debounce": {"consecutive_yes": s.debounce_consecutive_yes},
        "debug": s.debug,
        "rules": rules_data,
    }


def procedure_from_json(j: Dict) -> ProcedureDef:
    logger.debug(f"[PROCEDURE_PARSE] Starting to parse procedure JSON - id={j.get('id')}")
    steps = []
    for st in j["steps"]:
        # Check if negatives field exists
        has_negatives = "negatives" in st
        negatives_value = st.get("negatives", [])
        logger.debug(f"[PROCEDURE_PARSE] Parsing step {st['id']}: has_negatives={has_negatives}, using_default={'[]' if not has_negatives else 'from_json'}")
        
        # Check if bounding_questions field exists
        has_bounding = "bounding_questions" in st
        bounding_value = st.get("bounding_questions", [])
        if has_bounding:
            logger.debug(f"[PROCEDURE_PARSE] Step {st['id']} has bounding_questions: {bounding_value}")
        
        # Check if debug field exists
        has_debug = "debug" in st
        debug_value = st.get("debug", False)
        if has_debug:
            logger.debug(f"[PROCEDURE_PARSE] Step {st['id']} has debug flag: {debug_value}")
        
        # Parse rules if they exist
        rules_list = []
        if "rules" in st:
            rules_data = st["rules"]
            logger.debug(f"[PROCEDURE_PARSE] Step {st['id']} has {len(rules_data)} rule(s)")
            for rule_data in rules_data:
                # Support both "type" (JSON format) and "rule_type" (internal format) field names
                rule_type_value = rule_data.get("type") or rule_data.get("rule_type")
                if not rule_type_value:
                    logger.error(f"[PROCEDURE_PARSE] Missing rule type field in rule: {rule_data.get('name', 'unnamed')}")
                    raise KeyError("Rule definition must have 'type' or 'rule_type' field")
                
                # Support both "parameters" (JSON format) and "params" (internal format) field names
                params_value = rule_data.get("parameters") or rule_data.get("params", {})
                
                # Create RuleDef with defaults and let __post_init__ handle conversions
                rule = RuleDef(
                    rule_type=rule_type_value,
                    name=rule_data["name"],
                    enabled=rule_data.get("enabled", True),
                    failure_behavior=rule_data.get("failure_behavior", "block"),
                    params=params_value
                )
                rules_list.append(rule)
                logger.debug(
                    f"[PROCEDURE_PARSE] Parsed rule: name={rule.name}, "
                    f"type={rule.rule_type.value}, enabled={rule.enabled}, "
                    f"behavior={rule.failure_behavior.value}"
                )
        
        steps.append(StepDef(
            id=st["id"],
            name=st["name"],
            positives=st["positives"],
            negatives=negatives_value,
            bounding_questions=bounding_value,
            timeout_s=st["timeout_s"],
            debounce_consecutive_yes=st["debounce"]["consecutive_yes"],
            debug=debug_value,
            rules=rules_list,
        ))
    logger.info(f"[PROCEDURE_PARSE] Successfully parsed {len(steps)} steps from JSON")
    return ProcedureDef(
        id=j["id"],
        name=j["name"],
        version=j["version"],
        steps=steps,
    )