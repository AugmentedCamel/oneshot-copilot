"""Rule validation service."""
from typing import Any, Dict, List, Optional
import logging

from app.models.rules import (
    RuleDef, 
    RuleValidationResult, 
    RuleStatus, 
    RuleType,
    FailureBehavior
)
from app.services.rule_handlers.base import RuleHandler
from app.services.rule_handlers.cluster_negative import ClusterNegativeHandler

logger = logging.getLogger(__name__)


class RuleValidationService:
    """
    Service for validating rules using registered handlers.
    
    This service manages rule handlers and coordinates the validation
    of rules against provided context data.
    """
    
    def __init__(self):
        """Initialize the rule validation service with default handlers."""
        self._handlers: Dict[RuleType, RuleHandler] = {}
        logger.info("[RULE_VALIDATION] Initializing RuleValidationService")
        
        # Register default handlers
        self._register_default_handlers()
        
        logger.info(
            f"[RULE_VALIDATION] RuleValidationService initialized with "
            f"{len(self._handlers)} handler(s): {[rt.value for rt in self._handlers.keys()]}"
        )
    
    def _register_default_handlers(self) -> None:
        """Register the default set of rule handlers."""
        # Register cluster_negative handler
        self.register_handler(ClusterNegativeHandler())
        logger.debug("[RULE_VALIDATION] Default handlers registered")
    
    def register_handler(self, handler: RuleHandler) -> None:
        """
        Register a rule handler for a specific rule type.
        
        Args:
            handler: The rule handler to register
        """
        if handler.rule_type in self._handlers:
            logger.warning(
                f"[RULE_VALIDATION] Overwriting existing handler for "
                f"rule_type={handler.rule_type.value}"
            )
        
        self._handlers[handler.rule_type] = handler
        logger.info(
            f"[RULE_VALIDATION] Registered handler: "
            f"rule_type={handler.rule_type.value}, "
            f"handler={handler.__class__.__name__}"
        )
    
    def validate_rules(
        self,
        rules: List[RuleDef],
        context: Dict[str, Any]
    ) -> List[RuleValidationResult]:
        """
        Validate a list of rules against the provided context.
        
        Args:
            rules: List of rule definitions to validate
            context: Context data needed for validation (e.g., VLM response, frame data)
        
        Returns:
            List of RuleValidationResult objects, one for each rule
        """
        print(f"\n[RULE_VALIDATION_SERVICE] validate_rules() called with {len(rules)} rule(s)")
        logger.info(
            f"[RULE_VALIDATION] Starting validation of {len(rules)} rule(s)"
        )
        
        results: List[RuleValidationResult] = []
        
        for rule in rules:
            logger.debug(
                f"[RULE_VALIDATION] Processing rule: name={rule.name}, "
                f"type={rule.rule_type.value}, enabled={rule.enabled}, "
                f"failure_behavior={rule.failure_behavior.value}"
            )
            
            # Skip disabled rules
            if not rule.enabled:
                logger.info(
                    f"[RULE_VALIDATION] Rule '{rule.name}' is disabled, skipping"
                )
                result = RuleValidationResult(
                    rule_name=rule.name,
                    rule_type=rule.rule_type,
                    status=RuleStatus.SKIPPED,
                    message="Rule is disabled",
                    details={"reason": "disabled"},
                    failure_behavior=rule.failure_behavior
                )
                results.append(result)
                continue
            
            # Check if handler exists for this rule type
            handler = self._handlers.get(rule.rule_type)
            if not handler:
                logger.error(
                    f"[RULE_VALIDATION] No handler registered for "
                    f"rule_type={rule.rule_type.value}, rule={rule.name}"
                )
                result = RuleValidationResult(
                    rule_name=rule.name,
                    rule_type=rule.rule_type,
                    status=RuleStatus.ERROR,
                    message=f"No handler registered for rule type: {rule.rule_type.value}",
                    details={
                        "reason": "missing_handler",
                        "rule_type": rule.rule_type.value
                    },
                    failure_behavior=rule.failure_behavior
                )
                results.append(result)
                continue
            
            # Validate the rule using the handler
            try:
                print(f"[RULE_VALIDATION_SERVICE] Calling handler {handler.__class__.__name__} for rule '{rule.name}'")
                logger.info(
                    f"[RULE_VALIDATION] Validating rule '{rule.name}' "
                    f"with {handler.__class__.__name__}"
                )
                result = handler.validate(rule, context)
                results.append(result)
                
                print(f"[RULE_VALIDATION_SERVICE] Rule '{rule.name}' result: {result.status.value} - {result.message}")
                logger.info(
                    f"[RULE_VALIDATION] Rule '{rule.name}' validation completed: "
                    f"status={result.status.value}, message={result.message}"
                )
                
            except Exception as e:
                logger.error(
                    f"[RULE_VALIDATION] Exception during rule validation: "
                    f"rule={rule.name}, error={str(e)}",
                    exc_info=True
                )
                result = RuleValidationResult(
                    rule_name=rule.name,
                    rule_type=rule.rule_type,
                    status=RuleStatus.ERROR,
                    message=f"Validation error: {str(e)}",
                    details={
                        "reason": "validation_exception",
                        "error": str(e)
                    },
                    failure_behavior=rule.failure_behavior
                )
                results.append(result)
        
        # Log summary
        self._log_validation_summary(results)
        
        return results
    
    def _log_validation_summary(self, results: List[RuleValidationResult]) -> None:
        """
        Log a summary of validation results.
        
        Args:
            results: List of validation results to summarize
        """
        total = len(results)
        passed = sum(1 for r in results if r.status == RuleStatus.PASSED)
        failed = sum(1 for r in results if r.status == RuleStatus.FAILED)
        error = sum(1 for r in results if r.status == RuleStatus.ERROR)
        skipped = sum(1 for r in results if r.status == RuleStatus.SKIPPED)
        pending = sum(1 for r in results if r.status == RuleStatus.PENDING)
        blocking = sum(1 for r in results if r.is_blocking())
        
        logger.info("[RULE_VALIDATION] ========== VALIDATION SUMMARY ==========")
        logger.info(f"[RULE_VALIDATION] Total Rules:     {total}")
        logger.info(f"[RULE_VALIDATION] Passed:          {passed}")
        logger.info(f"[RULE_VALIDATION] Failed:          {failed}")
        logger.info(f"[RULE_VALIDATION] Error:           {error}")
        logger.info(f"[RULE_VALIDATION] Skipped:         {skipped}")
        logger.info(f"[RULE_VALIDATION] Pending:         {pending}")
        logger.info(f"[RULE_VALIDATION] Blocking Fails:  {blocking}")
        logger.info("[RULE_VALIDATION] =============================================")
        
        # Log details of blocking failures
        if blocking > 0:
            logger.warning(
                f"[RULE_VALIDATION] {blocking} rule(s) failed with BLOCK behavior:"
            )
            for result in results:
                if result.is_blocking():
                    logger.warning(
                        f"[RULE_VALIDATION]   - {result.rule_name}: {result.message}"
                    )
    
    def has_blocking_failures(self, results: List[RuleValidationResult]) -> bool:
        """
        Check if any validation results are blocking failures.
        
        Args:
            results: List of validation results to check
        
        Returns:
            True if any result is a blocking failure, False otherwise
        """
        blocking = any(r.is_blocking() for r in results)
        if blocking:
            logger.warning(
                "[RULE_VALIDATION] Blocking failures detected - progression should be blocked"
            )
        return blocking