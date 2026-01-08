"""Node Graph Engine - State machine logic for node graph procedures.

This module implements the guard evaluation, transition logic, and state
management for node graph procedure execution.
"""
import logging
import time
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple

from app.domain.nodegraph_models import (
    NodeGraphSession, NodeDef, CortexConfig, VerificationMode, NodeType
)
from app.domain.events import DomainEvent, StatusChanged

logger = logging.getLogger(__name__)


# Default error threshold for error handling
DEFAULT_ERROR_THRESHOLD = 0.7


@dataclass
class NodeGraphTransitionEvent(DomainEvent):
    """Event emitted when a node transition occurs."""
    procedure_id: str
    from_node: str
    to_node: str
    reason: str  # "success", "error", "timeout"


@dataclass
class NodeGraphCompletedEvent(DomainEvent):
    """Event emitted when a node graph procedure completes."""
    procedure_id: str
    final_node: str


@dataclass
class NodeGraphErrorEvent(DomainEvent):
    """Event emitted when an error is detected."""
    procedure_id: str
    node_id: str
    error_class: str
    message: str


@dataclass
class NodeGraphDispatchNeeded(DomainEvent):
    """Event indicating AI dispatch is needed for the current node."""
    frame_id: str
    procedure_id: str
    node_id: str
    target_classes: List[str]
    excluded_candidates: List[str]
    candidate_scope: List[str]  # Limit AI detection to only these classes
    idem_key: str


class NodeGraphEngine:
    """State machine engine for node graph procedure execution.
    
    Implements:
    - Step A: Context Lookup
    - Step B: AI Interrogation preparation  
    - Step C: Guard Evaluation (error priority, VISUAL_STATE, ACTION_DURATION)
    - Step D: Transition Execution
    """

    def start_procedure(
        self, 
        session: NodeGraphSession, 
        now_ms: int
    ) -> List[DomainEvent]:
        """Start a node graph procedure.
        
        Sets the session to the initial node and emits status changed event.
        """
        events = []
        
        # Set initial node
        session.current_node_id = session.procedure.initial_node_id
        session.reset_validation_state()
        session.inflight = False
        session.last_frame_at_ms = now_ms
        
        logger.info(
            f"[NODEGRAPH] Started procedure {session.procedure.procedure_id} "
            f"for {session.username} at node {session.current_node_id}"
        )
        
        events.append(StatusChanged(username=session.username))
        return events

    def get_current_context(
        self, 
        session: NodeGraphSession
    ) -> Tuple[Optional[NodeDef], Optional[CortexConfig]]:
        """Step A: Context Lookup.
        
        Returns the current node and its cortex configuration.
        """
        node = session.get_current_node()
        if not node:
            logger.error(f"[NODEGRAPH] Node {session.current_node_id} not found")
            return None, None
        
        return node, node.cortex_config

    def prepare_dispatch(
        self,
        session: NodeGraphSession,
        frame_id: str,
        now_ms: int
    ) -> List[DomainEvent]:
        """Prepare AI dispatch for the current node.

        Returns a NodeGraphDispatchNeeded event if dispatch is needed.
        """
        events = []

        # Time-based throttle: allow max 20 fps (50ms between ingests)
        # This replaces the old inflight blocking which waited for HTTP completion
        # and was limiting us to ~1 fps.
        MIN_INGEST_INTERVAL_MS = 50
        if session.last_frame_at_ms is not None:
            elapsed_ms = now_ms - session.last_frame_at_ms
            if elapsed_ms < MIN_INGEST_INTERVAL_MS:
                # Too soon since last ingest, skip this frame
                logger.debug(
                    f"[NODEGRAPH] prepare_dispatch: throttled for {session.username} "
                    f"(elapsed={elapsed_ms}ms < {MIN_INGEST_INTERVAL_MS}ms)"
                )
                return events

        node = session.get_current_node()
        if not node:
            logger.warning(f"[NODEGRAPH] prepare_dispatch: no current node for {session.username}")
            return events

        # FINAL nodes don't need AI verification
        if node.type == NodeType.FINAL:
            logger.debug(f"[NODEGRAPH] prepare_dispatch: node {node.id} is FINAL, skipping")
            return events

        if not node.cortex_config:
            logger.warning(f"[NODEGRAPH] Node {node.id} has no cortex_config")
            return events

        # Get all classes to check for this node
        target_classes = session.procedure.get_all_target_classes(session.current_node_id)

        # Get excluded candidates and candidate scope from cortex config
        excluded_candidates = node.cortex_config.excluded_candidates if node.cortex_config else []
        candidate_scope = node.cortex_config.candidate_scope if node.cortex_config else []

        session.inflight = True
        session.inflight_frame_id = frame_id
        session.last_frame_at_ms = now_ms

        logger.debug(
            f"[NODEGRAPH] prepare_dispatch: creating dispatch event for {session.username}, "
            f"node={node.id}, target_classes={target_classes}"
        )

        events.append(NodeGraphDispatchNeeded(
            username=session.username,
            frame_id=frame_id,
            procedure_id=session.procedure.procedure_id,
            node_id=session.current_node_id,
            target_classes=target_classes,
            excluded_candidates=excluded_candidates,
            candidate_scope=candidate_scope,
            idem_key=frame_id
        ))

        return events

    def evaluate_guards(
        self,
        session: NodeGraphSession,
        predictions: Dict[str, float],
        now_ms: int
    ) -> List[DomainEvent]:
        """Step C: Guard Evaluation.

        Evaluates predictions against the current node's guards and
        triggers transitions as needed.

        Priority order:
        1. Check errors (safety first)
        2. Check success (VISUAL_STATE or ACTION_DURATION)
        """
        events = []

        # Mark as not inflight
        session.inflight = False
        session.inflight_frame_id = None

        node = session.get_current_node()
        if not node:
            logger.error(f"[NODEGRAPH] Cannot evaluate guards: node not found")
            return events

        # FINAL nodes complete the procedure
        if node.type == NodeType.FINAL:
            logger.info(f"[NODEGRAPH] evaluate_guards: node {node.id} is FINAL, completing procedure")
            events.append(NodeGraphCompletedEvent(
                username=session.username,
                procedure_id=session.procedure.procedure_id,
                final_node=node.id
            ))
            return events

        cortex = node.cortex_config
        if not cortex:
            logger.warning(f"[NODEGRAPH] evaluate_guards: node {node.id} has no cortex_config")
            return events

        logger.info(
            f"[NODEGRAPH] Evaluating guards for {session.username} at node {node.id}: "
            f"target_class={cortex.target_class}, mode={cortex.verification_mode.value}, "
            f"min_confidence={cortex.min_confidence}, predictions={predictions}"
        )
        
        # ===== PRIORITY 1: Check Errors (Safety First) =====
        for handler in node.error_handling:
            error_score = predictions.get(handler.trigger_class, 0.0)
            if error_score >= DEFAULT_ERROR_THRESHOLD:
                logger.warning(
                    f"[NODEGRAPH] Error detected: {handler.trigger_class} "
                    f"(score={error_score:.2f}) -> fallback to {handler.fallback_node}"
                )
                
                # Emit error event
                events.append(NodeGraphErrorEvent(
                    username=session.username,
                    procedure_id=session.procedure.procedure_id,
                    node_id=node.id,
                    error_class=handler.trigger_class,
                    message=handler.message
                ))
                
                # Transition to fallback
                events.extend(self._execute_transition(
                    session, handler.fallback_node, "error", now_ms
                ))
                return events
        
        # ===== PRIORITY 2: Check Success =====
        target_score = predictions.get(cortex.target_class, 0.0)
        is_confident = target_score >= cortex.min_confidence
        
        logger.info(
            f"[NODEGRAPH] Target {cortex.target_class}: score={target_score:.2f}, "
            f"threshold={cortex.min_confidence}, confident={is_confident}"
        )

        if cortex.verification_mode == VerificationMode.VISUAL_STATE:
            events.extend(self._evaluate_visual_state(
                session, node, cortex, is_confident, now_ms
            ))
        elif cortex.verification_mode == VerificationMode.ACTION_DURATION:
            events.extend(self._evaluate_action_duration(
                session, node, cortex, is_confident, now_ms
            ))

        if events:
            logger.info(f"[NODEGRAPH] evaluate_guards produced {len(events)} events: {[type(e).__name__ for e in events]}")
        else:
            logger.debug(f"[NODEGRAPH] evaluate_guards: no transition (buffer={len(session.validation_buffer)})")

        return events

    def _evaluate_visual_state(
        self,
        session: NodeGraphSession,
        node: NodeDef,
        cortex: CortexConfig,
        is_confident: bool,
        now_ms: int
    ) -> List[DomainEvent]:
        """Evaluate VISUAL_STATE verification mode.
        
        Requires `stability_frames` consecutive confident detections.
        """
        events = []
        stability_frames = cortex.stability_frames or 5
        
        if is_confident:
            session.validation_buffer.append(True)
            logger.info(
                f"[NODEGRAPH] VISUAL_STATE: buffer has "
                f"{len(session.validation_buffer)}/{stability_frames} confident frames"
            )
        else:
            # Strict mode: clear buffer on non-confident frame
            if session.validation_buffer:
                logger.info(f"[NODEGRAPH] VISUAL_STATE: clearing buffer (not confident)")
            session.validation_buffer.clear()
        
        # Check if we have enough consecutive confident frames
        if len(session.validation_buffer) >= stability_frames:
            logger.info(
                f"[NODEGRAPH] VISUAL_STATE success: {stability_frames} stable frames"
            )
            if node.transitions and node.transitions.on_success:
                events.extend(self._execute_transition(
                    session, node.transitions.on_success, "success", now_ms
                ))
        
        return events

    def _evaluate_action_duration(
        self,
        session: NodeGraphSession,
        node: NodeDef,
        cortex: CortexConfig,
        is_confident: bool,
        now_ms: int
    ) -> List[DomainEvent]:
        """Evaluate ACTION_DURATION verification mode.
        
        Requires action to be held for `duration_threshold_seconds`.
        """
        events = []
        duration_threshold = cortex.duration_threshold_seconds or 3.0
        now_seconds = now_ms / 1000.0
        
        if is_confident:
            if session.action_timer_start is None:
                # Start the timer
                session.action_timer_start = now_seconds
                logger.info(f"[NODEGRAPH] ACTION_DURATION: started timer at {now_seconds:.2f}s")
            else:
                elapsed = now_seconds - session.action_timer_start
                logger.info(
                    f"[NODEGRAPH] ACTION_DURATION: elapsed={elapsed:.2f}s / "
                    f"{duration_threshold}s"
                )

                if elapsed >= duration_threshold:
                    logger.info(
                        f"[NODEGRAPH] ACTION_DURATION success: "
                        f"{elapsed:.2f}s >= {duration_threshold}s"
                    )
                    if node.transitions and node.transitions.on_success:
                        events.extend(self._execute_transition(
                            session, node.transitions.on_success, "success", now_ms
                        ))
        else:
            # User stopped action, reset timer
            if session.action_timer_start is not None:
                logger.info(f"[NODEGRAPH] ACTION_DURATION: resetting timer (action stopped)")
            session.action_timer_start = None
        
        return events

    def _execute_transition(
        self,
        session: NodeGraphSession,
        target_node_id: str,
        reason: str,
        now_ms: int
    ) -> List[DomainEvent]:
        """Step D: Execute a transition to a new node.
        
        Updates cursor, resets validation state, and emits events.
        """
        events = []
        
        from_node_id = session.current_node_id
        
        # Update cursor
        session.current_node_id = target_node_id
        
        # Reset validation state for new node
        session.reset_validation_state()
        
        logger.info(
            f"[NODEGRAPH] Transition: {from_node_id} -> {target_node_id} "
            f"(reason={reason})"
        )
        
        # Emit transition event
        events.append(NodeGraphTransitionEvent(
            username=session.username,
            procedure_id=session.procedure.procedure_id,
            from_node=from_node_id,
            to_node=target_node_id,
            reason=reason
        ))
        
        # Emit status changed
        events.append(StatusChanged(username=session.username))
        
        # Check if new node is FINAL
        new_node = session.get_current_node()
        if new_node and new_node.type == NodeType.FINAL:
            logger.info(f"[NODEGRAPH] Reached FINAL node: {target_node_id}")
            events.append(NodeGraphCompletedEvent(
                username=session.username,
                procedure_id=session.procedure.procedure_id,
                final_node=target_node_id
            ))
        
        return events

    def ingest_frame(
        self,
        session: NodeGraphSession,
        frame_id: str,
        now_ms: int
    ) -> List[DomainEvent]:
        """Handle a new frame for the session.

        Returns dispatch event if AI verification is needed.
        """
        events = []

        node = session.get_current_node()
        if not node:
            logger.warning(
                f"[NODEGRAPH] ingest_frame: no current node for {session.username}, "
                f"node_id={session.current_node_id}"
            )
            return events

        # FINAL nodes don't need frame processing
        if node.type == NodeType.FINAL:
            logger.debug(f"[NODEGRAPH] ingest_frame: node {node.id} is FINAL, skipping")
            return events

        logger.debug(
            f"[NODEGRAPH] ingest_frame: processing frame {frame_id} for {session.username}, "
            f"node={node.id}, type={node.type.value}"
        )

        # Prepare AI dispatch
        events.extend(self.prepare_dispatch(session, frame_id, now_ms))

        return events

    def get_current_ui(self, session: NodeGraphSession) -> Optional[Dict]:
        """Get the current node's UI data for the frontend."""
        node = session.get_current_node()
        if not node:
            return None
        
        return {
            "node_id": node.id,
            "type": node.type.value,
            "title": node.ui.title,
            "instruction": node.ui.instruction
        }
