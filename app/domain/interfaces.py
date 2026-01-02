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

class ProcedureStrategy(ABC):
    @abstractmethod
    async def load_procedure(self, procedure_id: str) -> Any:
        """Load procedure definition."""
        pass

    @abstractmethod
    async def initialize_session(self, username: str, procedure_id: str, source_id: str) -> str:
        """Initialize session and return session ID."""
        pass

    @abstractmethod
    async def log_event(self, session_id: str, event: Any) -> None:
        """Log event to session."""
        pass

    @abstractmethod
    async def close_session(self, session_id: str) -> None:
        """Close the session."""
        pass
    
    @abstractmethod
    async def list_available_procedures(self) -> List[Dict[str, Any]]:
        """List all available procedures for this strategy."""
        pass
