from fastapi import APIRouter, HTTPException, Body
from typing import Optional
from app.services.procedure_service import procedure_service
from app.config import settings
import httpx
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/assist")
async def agent_assist(
    query: str = Body(..., embed=True),
    username: Optional[str] = Body(None, embed=True),
    session_id: Optional[str] = Body(None, embed=True)
):
    """
    Endpoint to ask a question to the memory agent during a procedure.
    Requires either 'session_id' (Memory Service ID) or 'username' (to look up active session).
    """
    logger.info(f"Received agent assist request. User: {username}, Session: {session_id}, Query: {query}")

    session = None

    # 1. Try lookup by session_id
    if session_id:
        session = procedure_service.get_session_by_external_id(session_id)
        if not session:
            logger.warning(f"No active session found for external ID {session_id}")
            raise HTTPException(status_code=404, detail=f"No active session found for session ID {session_id}")

    # 2. Try lookup by username if session not found yet
    elif username:
        sessions = procedure_service._active_sessions.get(username)
        if sessions:
            # Assume the first session is the active one we care about
            session = sessions[0]
        else:
            logger.warning(f"No active session found for user {username}")
            raise HTTPException(status_code=400, detail=f"No active session found for user {username}")
    
    else:
        raise HTTPException(status_code=400, detail="Must provide either 'session_id' or 'username'")

    # Validate session has external ID (if looked up by username)
    if not session.external_session_id:
         logger.warning(f"Active session for user {session.username} has no external session ID")
         raise HTTPException(status_code=400, detail="Active session has no external session ID (Memory Service not connected?)")

    # 3. Prepare payload
    payload = {
        "session_id": session.external_session_id,
        "query": query,
        "current_step_name": session.procedure.steps[session.current_index].name if session.procedure else None,
        "procedure_name": session.procedure.name if session.procedure else None
    }
    
    logger.debug(f"Forwarding to memory service: {payload}")

    # 4. Call Memory Service
    url = f"{settings.MEMORY_SERVICE_URL}/agent/assist"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Memory service error: {e.response.text}")
            raise HTTPException(status_code=e.response.status_code, detail=f"Memory service error: {e.response.text}")
        except Exception as e:
            logger.error(f"Failed to call memory service: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to call memory service: {e}")
