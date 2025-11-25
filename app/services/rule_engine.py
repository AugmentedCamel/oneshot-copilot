import logging
from typing import Dict, Any, List
from app.domain.entities import Event, EventType
from app.core.event_bus import event_bus
from app.services.rule_validation import RuleValidationService
from app.models.rules import RuleDef, RuleValidationResult, RuleStatus

logger = logging.getLogger(__name__)

class RuleEngine:
    def __init__(self):
        self._validator = RuleValidationService()

    async def evaluate(self, job_id: str, source_id: str, rules: List[RuleDef], context: Dict[str, Any]) -> List[RuleValidationResult]:
        """
        Evaluate rules and emit events for failures or triggers.
        """
        results = self._validator.validate_rules(rules, context)
        
        for result in results:
            if result.status == RuleStatus.FAILED:
                # Emit rule triggered event (failure is a trigger in this context)
                await event_bus.publish(Event(
                    type=EventType.RULE_TRIGGERED,
                    job_id=job_id,
                    source_id=source_id,
                    payload={
                        "rule_name": result.rule_name,
                        "status": result.status.value,
                        "message": result.message,
                        "details": result.details,
                        "failure_behavior": result.failure_behavior.value
                    }
                ))
        
        return results

# Global instance
rule_engine = RuleEngine()
