"""Context analysis service for VLM responses."""
import logging
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)


class ContextAnalysisService:
    """
    Service for analyzing VLM response context including bounding boxes and negative results.

    This service provides various analysis methods that can be applied to VLM responses
    to enhance decision-making in the state machine.
    """

    def __init__(self):
        """Initialize the context analysis service."""
        logger.info("[CONTEXT_ANALYSIS] Service initialized")

    def analyze(
        self,
        username: str,
        frame_id: str,
        vlm_response: Dict,
        step_name: Optional[str] = None
    ) -> None:
        """
        Analyze VLM response data including negative results and bounding boxes.

        For now, this method only logs the presence of negative results and bounding boxes.
        Future implementations will include:
        - Clustering analysis for detected items
        - Spatial relationship analysis
        - Temporal tracking across frames

        Args:
            username: Username for context
            frame_id: Frame ID for context
            vlm_response: Full VLM response dictionary
            step_name: Optional step name for context
        """
        context = f"user={username}, frame={frame_id}"
        if step_name:
            context += f", step={step_name}"

        logger.info(f"[CONTEXT_ANALYSIS] Starting analysis - {context}")

        # Check for negative results
        negative_results = vlm_response.get("negative_results") or vlm_response.get("negatives")
        if negative_results:
            self._log_negative_results(negative_results, context)
        else:
            logger.debug(f"[CONTEXT_ANALYSIS] No negative results present - {context}")

        # Check for bounding boxes
        bounding_boxes = vlm_response.get("bounding_boxes") or vlm_response.get("boxes")
        if bounding_boxes:
            self._log_bounding_boxes(bounding_boxes, context)
        else:
            logger.debug(f"[CONTEXT_ANALYSIS] No bounding boxes present - {context}")

        logger.info(f"[CONTEXT_ANALYSIS] Analysis complete - {context}")

    def _log_negative_results(self, negative_results: any, context: str) -> None:
        """
        Log negative question results.

        Args:
            negative_results: Negative results from VLM (dict or list)
            context: Context string for logging
        """
        if isinstance(negative_results, dict):
            count = len(negative_results)
            logger.info(f"[CONTEXT_ANALYSIS] Negative results detected - count={count}, {context}")
            for question, result in negative_results.items():
                # Truncate long questions for logging
                q_preview = question[:100] + "..." if len(question) > 100 else question
                logger.debug(f"[CONTEXT_ANALYSIS] Negative Q: '{q_preview}' -> {result}")

        elif isinstance(negative_results, list):
            count = len(negative_results)
            logger.info(f"[CONTEXT_ANALYSIS] Negative results detected - count={count}, {context}")
            for idx, result in enumerate(negative_results):
                logger.debug(f"[CONTEXT_ANALYSIS] Negative[{idx}]: {result}")

        else:
            logger.warning(f"[CONTEXT_ANALYSIS] Unexpected negative_results format: {type(negative_results)}")

    def _log_bounding_boxes(self, bounding_boxes: any, context: str) -> None:
        """
        Log bounding box detection results.

        Future implementations will analyze:
        - Clustering of detected items
        - Spatial distributions
        - Confidence thresholds

        Args:
            bounding_boxes: Bounding boxes from VLM (dict or list)
            context: Context string for logging
        """
        if isinstance(bounding_boxes, dict):
            # Format: {"item_name": [{"x": ..., "y": ..., "width": ..., "height": ...}, ...]}
            total_detections = sum(len(boxes) if isinstance(boxes, list) else 1 for boxes in bounding_boxes.values())
            logger.info(f"[CONTEXT_ANALYSIS] Bounding boxes detected - items={len(bounding_boxes)}, total_detections={total_detections}, {context}")

            for item_name, boxes in bounding_boxes.items():
                if isinstance(boxes, list):
                    logger.debug(f"[CONTEXT_ANALYSIS] Item '{item_name}': {len(boxes)} detection(s)")
                    for idx, box in enumerate(boxes):
                        logger.debug(f"[CONTEXT_ANALYSIS]   Detection {idx}: {box}")
                else:
                    logger.debug(f"[CONTEXT_ANALYSIS] Item '{item_name}': {boxes}")

        elif isinstance(bounding_boxes, list):
            logger.info(f"[CONTEXT_ANALYSIS] Bounding boxes detected - count={len(bounding_boxes)}, {context}")
            for idx, box in enumerate(bounding_boxes):
                logger.debug(f"[CONTEXT_ANALYSIS] Box[{idx}]: {box}")

        else:
            logger.warning(f"[CONTEXT_ANALYSIS] Unexpected bounding_boxes format: {type(bounding_boxes)}")

    def analyze_clustering(self, target_item: str, bounding_boxes: List[Dict]) -> Dict:
        """
        Analyze if detected items in bounding boxes are clustered.
        
        Simple implementation: counts bounding boxes for the target item.
        - If count > 9: NO cluster detected (well distributed)
        - If count <= 9: Cluster detected (items are grouped)

        Args:
            target_item: The item name to analyze (e.g., "mushroom")
            bounding_boxes: List of bounding box dictionaries (objects array from VLM)
                           Format: [{"x_min": ..., "y_min": ..., "x_max": ..., "y_max": ...}, ...]

        Returns:
            Dictionary with clustering analysis results:
            {
                "is_clustered": bool,  # True if cluster detected
                "count": int,          # Number of detections
                "threshold": int,      # Threshold used (9)
                "target_item": str     # Item analyzed
            }
        """
        logger.info(f"[CONTEXT_ANALYSIS] Analyzing clustering for target_item='{target_item}'")
        
        # Count bounding boxes directly (already filtered for target item)
        count = len(bounding_boxes)
        
        # Simple clustering logic:
        # > 9 detections means well distributed (NOT clustered)
        # <= 9 detections means items are grouped (IS clustered)
        threshold = 9
        is_clustered = count <= threshold
        
        result = {
            "is_clustered": is_clustered,
            "count": count,
            "threshold": threshold,
            "target_item": target_item
        }
        
        logger.info(
            f"[CONTEXT_ANALYSIS] Clustering result: "
            f"target='{target_item}', count={count}, "
            f"is_clustered={is_clustered} (threshold={threshold})"
        )
        
        return result
