"""Rule validation system data models."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RuleType(str, Enum):
    """Types of rules that can be validated."""
    CLUSTER_NEGATIVE = "cluster_negative"
    SPATIAL_COVERAGE = "spatial_coverage"
    COUNT_THRESHOLD = "count_threshold"
    CUSTOM = "custom"


class FailureBehavior(str, Enum):
    """Behavior when a rule fails validation."""
    BLOCK = "block"  # Block progression to next step
    WARN = "warn"    # Log warning but allow progression
    LOG = "log"      # Only log the failure


class RuleStatus(str, Enum):
    """Status of a rule validation."""
    PENDING = "pending"      # Not yet validated
    PASSED = "passed"        # Validation passed
    FAILED = "failed"        # Validation failed
    ERROR = "error"          # Error during validation
    SKIPPED = "skipped"      # Rule was skipped (e.g., feature not implemented)


@dataclass
class RuleDef:
    """
    Definition of a validation rule.
    
    Rules default to:
    - enabled: true
    - failure_behavior: "block"
    """
    rule_type: RuleType
    name: str
    enabled: bool = True
    failure_behavior: FailureBehavior = FailureBehavior.BLOCK
    params: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Convert string values to enums if needed."""
        # Convert rule_type string to enum
        if isinstance(self.rule_type, str):
            self.rule_type = RuleType(self.rule_type)
        
        # Convert failure_behavior string to enum
        if isinstance(self.failure_behavior, str):
            self.failure_behavior = FailureBehavior(self.failure_behavior)


@dataclass
class RuleValidationResult:
    """Result of validating a single rule."""
    rule_name: str
    rule_type: RuleType
    status: RuleStatus
    message: str
    details: Optional[Dict[str, Any]] = None
    failure_behavior: FailureBehavior = FailureBehavior.BLOCK
    
    def __post_init__(self):
        """Convert string values to enums if needed."""
        # Convert rule_type string to enum
        if isinstance(self.rule_type, str):
            self.rule_type = RuleType(self.rule_type)
        
        # Convert status string to enum
        if isinstance(self.status, str):
            self.status = RuleStatus(self.status)
        
        # Convert failure_behavior string to enum
        if isinstance(self.failure_behavior, str):
            self.failure_behavior = FailureBehavior(self.failure_behavior)
    
    def is_blocking(self) -> bool:
        """Check if this result should block progression."""
        return (
            self.status in [RuleStatus.FAILED, RuleStatus.SKIPPED]
            and self.failure_behavior == FailureBehavior.BLOCK
        )