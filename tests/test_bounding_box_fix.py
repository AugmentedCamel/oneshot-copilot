import unittest
from app.services.rule_handlers.cluster_negative import ClusterNegativeHandler
from app.models.rules import RuleDef, RuleType, RuleStatus

class TestBoundingBoxFix(unittest.TestCase):
    def setUp(self):
        self.handler = ClusterNegativeHandler()
        self.rule = RuleDef(
            name="test_cluster_rule",
            rule_type=RuleType.CLUSTER_NEGATIVE,
            params={"target": "pepperoni"}
        )

    def test_standardized_format(self):
        """Test that handler correctly extracts bounding boxes from data.bounding_boxes"""
        context = {
            "vlm_response": {
                "data": {
                    "bounding_boxes": [
                        {"query": "pepperoni", "count": 10, "objects": ["box1"] * 10}
                    ]
                },
                "raw": {}
            }
        }
        result = self.handler.validate(self.rule, context)
        # Count 10 > 9 -> PASSED (no clustering)
        self.assertEqual(result.status, RuleStatus.PASSED)
        self.assertIn("No clustering", result.message)

    def test_legacy_format(self):
        """Test that handler correctly extracts bounding boxes from top-level bounding_results"""
        context = {
            "vlm_response": {
                "bounding_results": [
                    {"query": "pepperoni", "count": 5, "objects": ["box1"] * 5}
                ]
            }
        }
        result = self.handler.validate(self.rule, context)
        # Count 5 <= 9 -> FAILED (clustering detected)
        self.assertEqual(result.status, RuleStatus.FAILED)
        self.assertIn("Clustering detected", result.message)

    def test_raw_format(self):
        """Test that handler correctly extracts bounding boxes from raw.bounding_results"""
        context = {
            "vlm_response": {
                "raw": {
                    "bounding_results": [
                        {"query": "pepperoni", "count": 12, "objects": ["box1"] * 12}
                    ]
                }
            }
        }
        result = self.handler.validate(self.rule, context)
        # Count 12 > 9 -> PASSED
        self.assertEqual(result.status, RuleStatus.PASSED)

if __name__ == '__main__':
    unittest.main()
