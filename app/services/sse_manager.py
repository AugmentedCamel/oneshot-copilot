"""
SSE Manager - Server-Sent Events connection management.

Handles SSE connections for pushing real-time events to clients (e.g., Android apps).
See implementation_plan.md for background on why this exists.
"""
import asyncio
import logging
import json
from typing import Dict, Any, AsyncGenerator
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SSEEvent:
    """Represents an SSE event to be sent to clients."""
    event_type: str
    data: Dict[str, Any]
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    def format(self) -> str:
        """Format as SSE wire protocol."""
        data_json = json.dumps(self.data)
        return f"event: {self.event_type}\ndata: {data_json}\n\n"


class SSEManager:
    """
    Manages SSE connections per username.
    
    Usage:
        # In endpoint - subscribe and yield events
        async for event in sse_manager.subscribe(username):
            yield event
        
        # From any service - push event to connected client
        await sse_manager.publish(username, "agent_reply", {"text": "Hello"})
    """
    
    def __init__(self, heartbeat_interval: int = 30):
        self._connections: Dict[str, asyncio.Queue] = {}
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_tasks: Dict[str, asyncio.Task] = {}
    
    async def subscribe(self, username: str) -> AsyncGenerator[str, None]:
        """
        Subscribe to events for a username.
        Yields formatted SSE strings as events arrive.
        """
        # Create queue for this connection
        queue: asyncio.Queue = asyncio.Queue()
        self._connections[username] = queue
        logger.info(f"[SSE] Client connected: {username}")
        
        # Start heartbeat task
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(username))
        self._heartbeat_tasks[username] = heartbeat_task
        
        try:
            while True:
                event: SSEEvent = await queue.get()
                yield event.format()
        except asyncio.CancelledError:
            logger.info(f"[SSE] Client disconnected: {username}")
        finally:
            # Cleanup
            self._connections.pop(username, None)
            heartbeat_task.cancel()
            self._heartbeat_tasks.pop(username, None)
    
    async def publish(self, username: str, event_type: str, data: Dict[str, Any]) -> bool:
        """
        Publish an event to a connected client.
        Returns True if client was connected and event was queued.
        """
        queue = self._connections.get(username)
        if queue is None:
            logger.debug(f"[SSE] No connection for {username}, event not delivered: {event_type}")
            return False
        
        event = SSEEvent(event_type=event_type, data=data)
        await queue.put(event)
        logger.info(f"[SSE] Published {event_type} to {username}")
        return True
    
    async def _heartbeat_loop(self, username: str):
        """Send periodic heartbeats to keep connection alive."""
        try:
            while True:
                await asyncio.sleep(self._heartbeat_interval)
                await self.publish(username, "heartbeat", {})
        except asyncio.CancelledError:
            pass
    
    def is_connected(self, username: str) -> bool:
        """Check if a user has an active SSE connection."""
        return username in self._connections
    
    def get_connected_users(self) -> list:
        """Get list of currently connected usernames."""
        return list(self._connections.keys())


# Global instance
sse_manager = SSEManager()
