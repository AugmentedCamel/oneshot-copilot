"""Cluster negative rule handler."""
from typing import Any, Dict
import logging

from app.models.rules import RuleDef, RuleValidationResult, RuleStatus, RuleType
from app.services.rule_handlers.base import RuleHandler
from app.services.context_analysis import ContextAnalysisService

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
        self._context_analysis = ContextAnalysisService()
        logger.info("[RULE_VALIDATION] ClusterNegativeHandler initialized")
    
    def validate(
        self,
        rule: RuleDef,
        context: Dict[str, Any]
    ) -> RuleValidationResult:
        """
        Validate cluster negative rule.
        
        This rule prevents clustering of negative items. It uses simple
        counting logic:
        - If count > 9: NO cluster (PASSED - items are well distributed)
        - If count <= 9: Cluster detected (FAILED - items are grouped)
        
        Args:
            rule: The rule definition to validate
            context: Context data (VLM response, frame data, etc.)
        
        Returns:
            RuleValidationResult with validation outcome
        """
        logger.info(f"[RULE_VALIDATION] Validating cluster_negative rule: {rule.name}")
        logger.debug(f"[RULE_VALIDATION] Rule params: {rule.params}")
        
        # Extract target item from rule parameters
        target_item = rule.params.get("target")
        if not target_item:
            logger.error(f"[RULE_VALIDATION] Missing 'target' in rule params: {rule.name}")
            return self._create_result(
                rule=rule,
                status=RuleStatus.ERROR,
                message="Missing 'target' parameter in rule definition",
                details={"reason": "missing_target", "params": rule.params}
            )
        
        # Extract VLM response from context
        vlm_response = context.get("vlm_response")
        if not vlm_response:
            logger.warning(f"[RULE_VALIDATION] No VLM response in context for rule: {rule.name}")
            return self._create_result(
                rule=rule,
                status=RuleStatus.SKIPPED,
                message="No VLM response available in context",
                details={"reason": "no_vlm_response"}
            )
        
        # Extract bounding boxes from VLM response
        bounding_boxes = vlm_response.get("bounding_boxes") or vlm_response.get("boxes")
        if not bounding_boxes:
            logger.info(f"[RULE_VALIDATION] No bounding boxes in VLM response for rule: {rule.name}")
            return self._create_result(
                rule=rule,
                status=RuleStatus.SKIPPED,
                message="No bounding boxes available for analysis",
                details={"reason": "no_bounding_boxes"}
            )
        
        # Perform clustering analysis
        try:
            clustering_result = self._context_analysis.analyze_clustering(
                target_item=target_item,
                bounding_boxes=bounding_boxes
            )
            
            is_clustered = clustering_result.get("is_clustered", False)
            count = clustering_result.get("count", 0)
            threshold = clustering_result.get("threshold", 9)
            
            # cluster_negative rule: we DON'T want clustering
            # If is_clustered is True, the rule FAILS
            # If is_clustered is False, the rule PASSES
            if is_clustered:
                result = self._create_result(
                    rule=rule,
                    status=RuleStatus.FAILED,
                    message=f"Clustering detected for '{target_item}' (count={count} <= {threshold})",
                    details={
                        "clustering_result": clustering_result,
                        "reason": "clustering_detected"
                    }
                )
                logger.warning(
                    f"[RULE_VALIDATION] Rule '{rule.name}' FAILED: "
                    f"clustering detected for '{target_item}' (count={count})"
                )
            else:
                result = self._create_result(
                    rule=rule,
                    status=RuleStatus.PASSED,
                    message=f"No clustering detected for '{target_item}' (count={count} > {threshold})",
                    details={
                        "clustering_result": clustering_result,
                        "reason": "no_clustering"
                    }
                )
                logger.info(
                    f"[RULE_VALIDATION] Rule '{rule.name}' PASSED: "
                    f"no clustering for '{target_item}' (count={count})"
                )
            
            return result
            
        except Exception as e:
            logger.error(
                f"[RULE_VALIDATION] Error during clustering analysis for rule '{rule.name}': {str(e)}",
                exc_info=True
            )
            return self._create_result(
                rule=rule,
                status=RuleStatus.ERROR,
                message=f"Clustering analysis error: {str(e)}",
                details={"reason": "analysis_exception", "error": str(e)}
            )