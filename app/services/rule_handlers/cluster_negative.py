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
        
        # Print: Rule validation start
        print("\n" + "=" * 50)
        print(f"CLUSTER_NEGATIVE RULE: {rule.name}")
        if target_item:
            print(f"Target: {target_item}")
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
        
        # Navigate to bounding results: 
        # 1. Check data.bounding_boxes (standardized)
        # 2. Check raw.bounding_results (raw response)
        # 3. Check direct access (legacy)
        bounding_results = []
        
        # 1. Standardized
        if "data" in vlm_response and "bounding_boxes" in vlm_response["data"]:
            bounding_results = vlm_response["data"]["bounding_boxes"]
        # 2. Raw
        elif "raw" in vlm_response and "bounding_results" in vlm_response["raw"]:
            bounding_results = vlm_response["raw"]["bounding_results"]
        # 3. Direct/Legacy
        elif "bounding_results" in vlm_response:
            bounding_results = vlm_response["bounding_results"]
            
        print(f"VLM Response structure: response={vlm_response is not None}, bounding_results_count={len(bounding_results)}")
        
        if not bounding_results:
            logger.info(f"[RULE_VALIDATION] No bounding results in VLM response for rule: {rule.name}")
            return self._create_result(
                rule=rule,
                status=RuleStatus.SKIPPED,
                message="No bounding results available for analysis",
                details={"reason": "no_bounding_results"}
            )
        
        # Find bounding result matching target item (handle singular/plural)
        target_variations = [target_item, target_item + "s", target_item.rstrip("s")]
        matching_result = None
        for result in bounding_results:
            query = result.get("query", "").lower()
            for variation in target_variations:
                if variation.lower() in query:
                    matching_result = result
                    break
            if matching_result:
                break
        
        if not matching_result:
            logger.info(f"[RULE_VALIDATION] No bounding results for target '{target_item}' in rule: {rule.name}")
            print(f"Target item '{target_item}' not found in bounding results")
            return self._create_result(
                rule=rule,
                status=RuleStatus.SKIPPED,
                message=f"No bounding results found for target '{target_item}'",
                details={"reason": "target_not_found", "target": target_item}
            )
        
        # Get count directly from bounding result - simpler approach
        count = matching_result.get("count", 0)
        bounding_boxes = matching_result.get("objects", [])
        
        # Debug prints
        print(f"[CLUSTER_NEGATIVE] Target: '{target_item}'")
        print(f"[CLUSTER_NEGATIVE] Count from VLM: {count}")
        print(f"[CLUSTER_NEGATIVE] Bounding boxes: {len(bounding_boxes)}")
        
        if count == 0:
            logger.info(f"[RULE_VALIDATION] No objects detected for target '{target_item}' in rule: {rule.name}")
            return self._create_result(
                rule=rule,
                status=RuleStatus.SKIPPED,
                message=f"No objects detected for target '{target_item}' (count=0)",
                details={"reason": "no_objects", "target": target_item, "count": 0}
            )
        
        # Simple clustering logic using count field
        # count > 9 = no cluster (items are distributed) -> PASS
        # count <= 9 = cluster detected (items are grouped) -> FAIL
        threshold = 9
        is_clustered = count <= threshold
        
        # Debug: Show logic
        print(f"[CLUSTER_NEGATIVE] Threshold: {threshold}")
        print(f"[CLUSTER_NEGATIVE] Logic: count ({count}) {'<=' if is_clustered else '>'} threshold ({threshold})")
        print(f"[CLUSTER_NEGATIVE] Result: {'CLUSTER DETECTED' if is_clustered else 'NO CLUSTER'}")
        
        # cluster_negative rule: we DON'T want clustering
        # If is_clustered is True, the rule FAILS
        # If is_clustered is False, the rule PASSES
        if is_clustered:
            result = self._create_result(
                rule=rule,
                status=RuleStatus.FAILED,
                message=f"Clustering detected for '{target_item}' (count={count} <= {threshold})",
                details={
                    "target": target_item,
                    "count": count,
                    "threshold": threshold,
                    "is_clustered": True,
                    "reason": "clustering_detected"
                }
            )
            
            # Print: Final decision (FAILED)
            print(f"[CLUSTER_NEGATIVE] Decision: FAILED - Clustering detected")
            print("=" * 50 + "\n")
            
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
                    "target": target_item,
                    "count": count,
                    "threshold": threshold,
                    "is_clustered": False,
                    "reason": "no_clustering"
                }
            )
            
            # Print: Final decision (PASSED)
            print(f"[CLUSTER_NEGATIVE] Decision: PASSED - No clustering detected")
            print("=" * 50 + "\n")
            
            logger.info(
                f"[RULE_VALIDATION] Rule '{rule.name}' PASSED: "
                f"no clustering for '{target_item}' (count={count})"
            )
        
        return result