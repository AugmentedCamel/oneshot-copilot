"""Base class for rule handlers."""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import logging

from app.models.rules import RuleDef, RuleValidationResult, RuleStatus, RuleType

logger = logging.getLogger(__name__)


class RuleHandler(ABC):
    """
    Abstract base class for rule handlers.
    
    Each rule type should have its own handler that implements the validate() method.
    """
    
    def __init__(self, rule_type: RuleType):
        """
        Initialize the rule handler.
        
        Args:
            rule_type: The type of rule this handler processes
        """
        self.rule_type = rule_type
        logger.debug(f"[RULE_VALIDATION] Initialized handler for rule_type={rule_type.value}")
    
    @abstractmethod
    def validate(
        self, 
        rule: RuleDef, 
        context: Dict[str, Any]
    ) -> RuleValidationResult:
        """
        Validate a rule against the provided context.
        
        Args:
            rule: The rule definition to validate
            context: Context data needed for validation (e.g., VLM response, frame data)
        
        Returns:
            RuleValidationResult with the validation outcome
        """
        pass
    
    def _create_result(
        self,
        rule: RuleDef,
        status: RuleStatus,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ) -> RuleValidationResult:
        """
        Helper method to create a validation result.
        
        Args:
            rule: The rule being validated
            status: The validation status
            message: Descriptive message about the result
            details: Optional additional details
        
        Returns:
            RuleValidationResult object
        """
        return RuleValidationResult(
            rule_name=rule.name,
            rule_type=rule.rule_type,
            status=status,
            message=message,
            details=details,
            failure_behavior=rule.failure_behavior
        )