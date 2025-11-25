from abc import ABC, abstractmethod
from typing import List, Dict, Any
from app.models.rules import RuleDef, RuleValidationResult
from app.domain.entities import Frame

class RuleValidator(ABC):
    @abstractmethod
    def validate_rules(self, rules: List[RuleDef], context: Dict[str, Any]) -> List[RuleValidationResult]:
        pass

class ContextAnalyzer(ABC):
    @abstractmethod
    def analyze(self, username: str, frame_id: str, vlm_response: Dict[str, Any], step_name: str) -> None:
        pass

class ModelPlugin(ABC):
    @abstractmethod
    def load(self, config: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def infer(self, frame: Frame, context: Dict[str, Any]) -> Dict[str, Any]:
        pass

class FeedbackAdapter(ABC):
    @abstractmethod
    async def send(self, message: Dict[str, Any]) -> None:
        pass
