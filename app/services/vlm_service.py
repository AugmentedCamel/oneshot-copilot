import logging
from typing import Dict, List, Optional, Tuple
from app.core.vlm_client import post_to_vlm_multipart
from app.config import settings

logger = logging.getLogger(__name__)

class VLMService:
    async def query(
        self,
        file_bytes: bytes,
        question: str,
        negatives: List[str],
        bounding_questions: List[str] = None,
        debug: bool = False
    ) -> Tuple[Dict, float, Optional[float]]:
        """
        Send query to VLM service.
        """
        return await post_to_vlm_multipart(
            file_bytes=file_bytes,
            question=question,
            negatives=negatives,
            vlm_url=settings.VLM_URL,
            bounding_questions=bounding_questions,
            debug=debug
        )
