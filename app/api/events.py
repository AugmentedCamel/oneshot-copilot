"""
SSE Events Endpoint - Server-Sent Events for real-time client updates.

Provides push notifications for agent replies to mobile clients that cannot
receive HTTP POST callbacks (like Android apps).
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.services.sse_manager import sse_manager

router = APIRouter()


@router.get("/events/{username}")
async def sse_events(username: str):
    """
    SSE endpoint for receiving real-time events.
    
    Connect to this endpoint to receive:
    - `agent_reply`: AI responses to user questions
    - `heartbeat`: Keep-alive signals (every 30s)
    
    Example usage (curl):
        curl -N http://localhost:8000/api/v2/events/my_username
    
    Example response:
        event: agent_reply
        data: {"text": "Pour about 1kg of salt until full."}
        
        event: heartbeat
        data: {}
    """
    async def event_generator():
        async for event in sse_manager.subscribe(username):
            yield event
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )
