"""Domain models for the procedure engine."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict
from app.models.rules import RuleDef, RuleValidationResult, FailureBehavior

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

    @staticmethod
    def parse(value: Any) -> Decision:
        """
        Robustly parse a decision string from VLM output.
        Handles variations like "[yes]", "yes.", "YES", etc.
        """
        if value is None:
            return Decision.NO
            
        s = str(value).strip().lower()
        
        # Remove common punctuation/brackets
        import re
        s = re.sub(r'[\[\]\.\(\)\s]', '', s)
        
        if s == "yes":
            return Decision.YES
        elif s == "no":
            return Decision.NO
        elif s == "uncertain":
            return Decision.UNCERTAIN
        elif s == "not_applicable" or s == "na":
            return Decision.NOT_APPLICABLE
            
        return Decision.NO


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
    external_session_id: Optional[str] = None  # ID of the session in the external Memory Service
