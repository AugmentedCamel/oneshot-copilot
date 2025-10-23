"""Base VLM Strategy interface."""
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple


class VLMStrategy(ABC):
    """Abstract base class for VLM client strategies."""
    
    @abstractmethod
    async def query(
        self,
        file_bytes: bytes,
        question: str,
        negatives: list[str]
    ) -> Tuple[Dict, float, Optional[float]]:
        """
        Send query to VLM service.
        
        Args:
            file_bytes: Image file bytes
            question: The positive question to ask
            negatives: List of negative questions
            
        Returns:
            Tuple of (response_json, http_post_ms, server_proc_ms)
            - response_json: Response JSON containing the answer
            - http_post_ms: HTTP request duration in milliseconds
            - server_proc_ms: VLM server processing time in milliseconds (if available)
        """
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this VLM strategy."""
        pass