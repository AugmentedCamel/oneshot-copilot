import asyncio
import logging
from typing import Callable, List, Dict, Any
from app.domain.entities import Event, EventType

logger = logging.getLogger(__name__)

class EventBus:
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable[[Event], Any]]] = {}
        self._all_subscribers: List[Callable[[Event], Any]] = []

    def subscribe(self, event_type: EventType, callback: Callable[[Event], Any]):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def subscribe_all(self, callback: Callable[[Event], Any]):
        self._all_subscribers.append(callback)

    def unsubscribe(self, event_type: EventType, callback: Callable[[Event], Any]):
        """Remove a callback from the subscribers list for the given event type."""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(callback)
            except ValueError:
                pass  # Callback was not subscribed

    async def publish(self, event: Event):
        # Notify specific subscribers
        if event.type in self._subscribers:
            for callback in self._subscribers[event.type]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        asyncio.create_task(callback(event))
                    else:
                        callback(event)
                except Exception as e:
                    logger.error(f"Error in event subscriber for {event.type}: {e}", exc_info=True)

        # Notify catch-all subscribers
        for callback in self._all_subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(event))
                else:
                    callback(event)
            except Exception as e:
                logger.error(f"Error in global event subscriber: {e}", exc_info=True)

# Global instance
event_bus = EventBus()
