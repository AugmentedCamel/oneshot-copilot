import logging
import asyncio
from typing import Dict, Any, Optional
from app.domain.entities import Event, EventType, FeedbackChannel
from app.domain.interfaces import FeedbackAdapter
from app.core.event_bus import event_bus
from app.core.adapters import HttpFeedbackAdapter
from app.config import settings


logger = logging.getLogger(__name__)

class FeedbackService:
    def __init__(self):
        self._channels: Dict[str, FeedbackChannel] = {}
        self._adapters: Dict[str, FeedbackAdapter] = {}
        
        # Subscribe to feedback events
        event_bus.subscribe(EventType.FEEDBACK_SENT, self._on_feedback_event)
        event_bus.subscribe(EventType.RULE_TRIGGERED, self._on_rule_triggered)

    def register_channel(self, channel: FeedbackChannel, adapter: FeedbackAdapter):
        self._channels[channel.id] = channel
        self._adapters[channel.id] = adapter
        logger.info(f"Registered feedback channel: {channel.id}")

    async def _on_feedback_event(self, event: Event):
        # Direct feedback request
        channel_id = event.payload.get("channel_id")
        message = event.payload.get("message")
        
        if channel_id and message:
            await self.send_feedback(channel_id, message)

    async def _on_rule_triggered(self, event: Event):
        # Map rule trigger to feedback if configured (TODO: Load mapping from Job/Config)
        # For now, just log or send a generic alert if critical
        pass

    async def send_feedback(self, channel_id: str, message: Dict[str, Any]) -> None:
        adapter = self._adapters.get(channel_id)
        if adapter:
            await adapter.send(message)
        else:
            logger.warning(f"No adapter found for feedback channel: {channel_id}")

    # Legacy support methods (to be deprecated or mapped)
    async def send_step_notification(self, username: str, step_name: str) -> None:
        # Map to a default channel or just use the old logic if needed for migration
        # For now, we'll assume there's a channel named "default_http" or similar
        # Or just keep the old HTTP call here for backward compatibility
        url = f"{settings.MENTRA_URL}/on_step"
        payload = {"username": username, "text": step_name}
        adapter = HttpFeedbackAdapter(url) # Create on the fly or reuse
        await adapter.send(payload)

    async def send_agent_reply(self, username: str, reply: str) -> None:
        """
        Send agent reply to connected clients.
        
        Delivery methods:
        - SSE: For Android/mobile clients with active SSE connection
        - HTTP POST: For Mentra Client (legacy callback)
        """
        # SSE push (Android clients)
        from app.services.sse_manager import sse_manager
        sse_delivered = await sse_manager.publish(username, "agent_reply", {"text": reply})
        
        # HTTP fallback (Mentra Client)
        url = f"{settings.MENTRA_URL}/agent_reply"
        payload = {"username": username, "text": reply}
        adapter = HttpFeedbackAdapter(url)
        await adapter.send(payload)
        
        logger.info(f"[FEEDBACK] Agent reply sent to {username} (SSE: {sse_delivered}, HTTP: True)")

    async def send_progress_notification(self, username: str, from_step: Optional[int], to_step: Optional[int]) -> None:
        url = f"{settings.MENTRA_URL}/progress_step"
        payload = {
            "username": username,
            "text": "progress",
            "from_step": from_step,
            "to_step": to_step
        }
        adapter = HttpFeedbackAdapter(url)
        await adapter.send(payload)
            
    async def send_feedback_legacy(self, username: str, message: str) -> None:
        await self.send_step_notification(username, message)

# Global instance
feedback_service = FeedbackService()
