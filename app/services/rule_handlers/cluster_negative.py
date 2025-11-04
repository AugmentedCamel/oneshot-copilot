"""Cluster negative rule handler."""
from typing import Any, Dict
import logging

from app.models.rules import RuleDef, RuleValidationResult, RuleStatus, RuleType
from app.services.rule_handlers.base import RuleHandler

logger = logging.getLogger(__name__)


class ClusterNegativeHandler(RuleHandler):
    """
    Handler for cluster_negative rules.
    
    This handler validates that negative items are not clustered together
    in the detected objects. Currently returns SKIPPED as the clustering
    algorithm is not yet implemented.
    """
    
    def __init__(self):
        """Initialize the cluster negative handler."""
        super().__init__(RuleType.CLUSTER_NEGATIVE)
        logger.info("[RULE_VALIDATION] ClusterNegativeHandler initialized")
    
    def validate(
        self, 
        rule: RuleDef, 
        context: Dict[str, Any]
    ) -> RuleValidationResult:
        """
        Validate cluster negative rule.
        
        Currently returns SKIPPED status as the clustering algorithm
        is not yet implemented.
        
        Args:
            rule: The rule definition to validate
            context: Context data (VLM response, frame data, etc.)
        
        Returns:
            RuleValidationResult with SKIPPED status
        """
        logger.info(f"[RULE_VALIDATION] Validating cluster_negative rule: {rule.name}")
        logger.debug(f"[RULE_VALIDATION] Rule params: {rule.params}")
        
        # Return SKIPPED with message indicating algorithm not implemented
        result = self._create_result(
            rule=rule,
            status=RuleStatus.SKIPPED,
            message="Clustering algorithm not yet implemented",
            details={
                "reason": "clustering_not_implemented",
                "rule_params": rule.params
            }
        )
        
        logger.info(
            f"[RULE_VALIDATION] Rule '{rule.name}' skipped: "
            f"status={result.status.value}, message={result.message}"
        )
        
        return result