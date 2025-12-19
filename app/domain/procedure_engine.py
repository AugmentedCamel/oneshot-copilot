import logging
from typing import List, Optional, Dict, Any
from app.domain.models import (
    UserSession, ProcedureDef, UserState, StepRuntime, Decision, RuleRuntime, StepDef
)
from app.domain.events import (
    DomainEvent, StepStarted, StepProgressed, ProcedureCompleted,
    VLMDispatchNeeded, FeedbackNeeded, StatusChanged
)
from app.domain.interfaces import RuleValidator, ContextAnalyzer
from app.models.rules import FailureBehavior

logger = logging.getLogger(__name__)

class ProcedureEngine:
    """
    Pure domain logic for procedure execution.
    Operates on UserSession and returns DomainEvents.
    """

    @staticmethod
    def _init_step_rt(step: StepDef, now_ms: int) -> StepRuntime:
        return StepRuntime(
            id=step.id,
            started_at_ms=now_ms,
            timeout_at_ms=now_ms + step.timeout_s * 1000,
            yes_consecutive=0,
        )

    @staticmethod
    def _current_step_def(session: UserSession) -> Optional[StepDef]:
        if not session.procedure or session.current_index >= len(session.procedure.steps):
            return None
        return session.procedure.steps[session.current_index]

    @staticmethod
    def _step_to_dict(s: StepDef) -> Dict:
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
            
        # Serialize step_context if present
        step_context_data = None
        if s.step_context:
            from dataclasses import asdict
            step_context_data = asdict(s.step_context)
            
        return {
            "id": s.id,
            "name": s.name,
            "positives": s.positives,
            "negatives": s.negatives,
            "timeout_s": s.timeout_s,
            "debounce_consecutive_yes": s.debounce_consecutive_yes,
            "bounding_questions": s.bounding_questions,
            "debug": s.debug,
            "rules": rules_data,
            "step_context": step_context_data
        }

    def start_procedure(self, session: UserSession, procedure: ProcedureDef, now_ms: int) -> List[DomainEvent]:
        events = []
        session.state = UserState.WORKING
        session.procedure = procedure
        session.current_index = 0
        step = self._current_step_def(session)
        session.step_rt = self._init_step_rt(step, now_ms) if step else None
        session.inflight = False
        session.buffered_frame = None
        
        events.append(StatusChanged(username=session.username))
        
        if step:
            # events.append(StepStarted(
            #     username=session.username,
            #     procedure_id=procedure.id,
            #     step_id=step.id,
            #     step_name=step.name
            # ))
            pass
            
        return events

    def pause(self, session: UserSession) -> List[DomainEvent]:
        if session.state == UserState.WORKING:
            session.state = UserState.PAUSED
            return [StatusChanged(username=session.username)]
        return []

    def resume(self, session: UserSession, now_ms: int) -> List[DomainEvent]:
        events = []
        if session.state == UserState.PAUSED:
            session.state = UserState.WORKING
            events.append(StatusChanged(username=session.username))
            # Try to dispatch if we have a buffered frame?
            # The original code calls _maybe_dispatch here.
            events.extend(self._maybe_dispatch(session, now_ms))
        return events

    def abort(self, session: UserSession) -> List[DomainEvent]:
        session.state = UserState.ABORTED
        session.inflight = False
        return [StatusChanged(username=session.username)]

    def ingest_frame(self, session: UserSession, frame_id: str, now_ms: int) -> List[DomainEvent]:
        events = []
        if session.state != UserState.WORKING:
            return events

        session.last_frame_at_ms = now_ms
        # In pure domain, we don't track perf_counter here, that's for the service layer/controller.
        # But we can track logical time if needed.

        if session.inflight:
            session.buffered_frame = frame_id
        else:
            events.extend(self._maybe_dispatch(session, now_ms, frame_id))
            
        return events

    def handle_vlm_decision(
        self,
        session: UserSession,
        frame_id: Optional[str],  # Can be None for reasoning callbacks (batched, not tied to specific frame)
        decision: Decision,
        vlm_response: Optional[Dict],
        rule_validator: Optional[RuleValidator],
        context_analyzer: Optional[ContextAnalyzer],
        now_ms: int
    ) -> List[DomainEvent]:
        events = []
        
        if session.state != UserState.WORKING or not session.procedure or not session.step_rt:
            return events

        step = self._current_step_def(session)
        if not step or session.step_rt.id != step.id:
            return events

        # Mark inflight done (only relevant for legacy sync mode)
        session.inflight = False
        session.inflight_since_ms = None
        # Keep inflight_frame_id for deduplication (handled in _maybe_dispatch)

        # Context Analysis (skip if no frame_id - reasoning mode)
        if vlm_response and context_analyzer and frame_id:
            try:
                context_analyzer.analyze(
                    username=session.username,
                    frame_id=frame_id,
                    vlm_response=vlm_response,
                    step_name=step.name
                )
            except Exception as e:
                logger.error(f"Context analysis failed: {e}")

        # Rule Validation (skip if no frame_id - reasoning mode)
        if step.has_rules() and vlm_response and rule_validator and frame_id:
            if session.step_rt.rule_runtime is None:
                session.step_rt.rule_runtime = RuleRuntime()
            
            context = {
                "username": session.username,
                "frame_id": frame_id,
                "step_name": step.name,
                "step_id": step.id,
                "vlm_response": vlm_response
            }
            
            results = rule_validator.validate_rules(step.rules, context)
            session.step_rt.rule_runtime.results = results
            # last_validation_ms logic omitted for simplicity or can be added

            blocking_failures = [r for r in results if r.is_blocking()]
            if blocking_failures:
                # Feedback logic
                time_since_last = (now_ms - session.last_feedback_sent_ms) if session.last_feedback_sent_ms else float('inf')
                if decision == Decision.YES and time_since_last >= 4000:
                    session.last_feedback_sent_ms = now_ms
                    failure = blocking_failures[0]
                    
                    if 'cluster' in failure.rule_name.lower():
                        target = failure.details.get('target', "the items") if failure.details else "the items"
                        msg = f"Please spread out the {target} more evenly"
                    else:
                        msg = f"Issue detected: {failure.message}"
                        
                    events.append(FeedbackNeeded(
                        message=msg,
                        step_id=step.id,
                        procedure_id=session.procedure.id,
                        username=session.username
                    ))

        # Decision Logic
        logger.info(f"[STEP_DEBUG] Processing decision: {decision} for user {session.username}")
        if decision == Decision.YES:
            # Check for Freeze case (YES + UNCERTAIN Negative)
            if vlm_response and "data" in vlm_response:
                neg_res = vlm_response["data"].get("negative_result")
                if neg_res and Decision.parse(neg_res) == Decision.UNCERTAIN:
                    logger.info(f"[STEP_DEBUG] Freeze case (Pos=YES, Neg=UNCERTAIN): Frozen yes count at {session.step_rt.yes_consecutive}")
                    return events

            session.step_rt.yes_consecutive += 1
            logger.info(f"[STEP_DEBUG] YES count: {session.step_rt.yes_consecutive}/{step.debounce_consecutive_yes}")
            
            if session.step_rt.yes_consecutive >= step.debounce_consecutive_yes:
                # Check rules
                rules_block = False
                if session.step_rt.rule_runtime and session.step_rt.rule_runtime.has_blocking_failures():
                    rules_block = True
                    logger.info(f"[STEP_DEBUG] Progression blocked by rules")
                
                if not rules_block:
                    # Progress
                    from_id = step.id
                    next_index = session.current_index + 1
                    
                    if next_index < len(session.procedure.steps):
                        session.current_index = next_index
                        session.last_feedback_sent_ms = None
                        next_step = self._current_step_def(session)
                        session.step_rt = self._init_step_rt(next_step, now_ms)
                        session.inflight_frame_id = None
                        
                        events.append(StepProgressed(
                            username=session.username,
                            procedure_id=session.procedure.id,
                            from_step=from_id,
                            to_step=next_step.id
                        ))
                        events.append(StatusChanged(username=session.username))
                    else:
                        # Completed
                        events.append(ProcedureCompleted(
                            username=session.username,
                            procedure_id=session.procedure.id,
                            final_step=from_id
                        ))
                        events.append(StepProgressed(
                            username=session.username,
                            procedure_id=session.procedure.id,
                            from_step=from_id,
                            to_step=-1 # -1 or None for completion
                        ))
                        session.state = UserState.COMPLETED
                        session.last_feedback_sent_ms = None
                        session.step_rt = None
                        session.inflight_frame_id = None
                        events.append(StatusChanged(username=session.username))
        else:
            # Decision is NOT YES (NO, UNCERTAIN, etc.)
            
            # Check for "Penalize" condition:
            # Positive Question = YES AND Negative Question = YES
            # In this case, we decrement consecutive yes by 1 instead of resetting.
            
            is_penalize_case = False
            is_freeze_case = False
            if vlm_response and "data" in vlm_response:
                data = vlm_response["data"]
                # Check positive result (usually "result")
                pos_res = data.get("result")
                # Check negative result (usually "negative_result")
                neg_res = data.get("negative_result")
                
                if pos_res and neg_res:
                    # Parse both to be sure
                    p_dec = Decision.parse(pos_res)
                    n_dec = Decision.parse(neg_res)
                    
                    if p_dec == Decision.YES:
                        if n_dec == Decision.YES:
                            is_penalize_case = True
                        elif n_dec == Decision.UNCERTAIN:
                            is_freeze_case = True
            
            if is_penalize_case:
                session.step_rt.yes_consecutive = max(0, session.step_rt.yes_consecutive - 1)
                logger.info(f"[STEP_DEBUG] Penalize case (Pos=YES, Neg=YES): Decremented yes count to {session.step_rt.yes_consecutive}")
            elif is_freeze_case:
                # Do nothing, keep consecutive yes count the same
                logger.info(f"[STEP_DEBUG] Freeze case (Pos=YES, Neg=UNCERTAIN): Frozen yes count at {session.step_rt.yes_consecutive}")
            else:
                session.step_rt.yes_consecutive = 0
                logger.info(f"[STEP_DEBUG] Decision {decision}: Reset yes count to 0")

        # Process buffered frame
        if session.buffered_frame:
            buffered_id = session.buffered_frame
            session.buffered_frame = None
            events.extend(self._maybe_dispatch(session, now_ms, buffered_id))

        return events

    def tick(self, session: UserSession, now_ms: int) -> List[DomainEvent]:
        events = []
        if session.state != UserState.WORKING:
            return events

        # VLM Timeout
        if session.inflight and session.inflight_since_ms is not None:
            if (now_ms - session.inflight_since_ms) > 2500:
                session.inflight = False
                session.inflight_since_ms = None
                session.inflight_frame_id = None
                
                if session.buffered_frame:
                    buffered_id = session.buffered_frame
                    session.buffered_frame = None
                    events.extend(self._maybe_dispatch(session, now_ms, buffered_id))

        # Step Timeout
        if session.step_rt:
            if now_ms >= session.step_rt.timeout_at_ms:
                step = self._current_step_def(session)
                if step:
                    session.step_rt.yes_consecutive = 0
                    session.step_rt.timeout_at_ms = now_ms + step.timeout_s * 1000

        return events

    def _maybe_dispatch(self, session: UserSession, now_ms: int, frame_id: Optional[str] = None) -> List[DomainEvent]:
        if session.state != UserState.WORKING or session.inflight:
            return []
        
        step = self._current_step_def(session)
        if not step:
            return []

        # Rate limiting removed - dispatch as fast as responses come back
        # The inflight flag already prevents overlapping requests,
        # so new frames are sent immediately when the previous response arrives

        if frame_id is None:
            frame_id = session.buffered_frame
            if frame_id:
                session.buffered_frame = None
        
        if not frame_id:
            return []

        if frame_id == session.inflight_frame_id:
            return []

        session.inflight = True
        session.inflight_since_ms = now_ms
        session.inflight_frame_id = frame_id
        
        return [VLMDispatchNeeded(
            username=session.username,
            frame_id=frame_id,
            procedure_id=session.procedure.id,
            step_def=self._step_to_dict(step),
            idem_key=frame_id,
            debug=step.debug
        )]
