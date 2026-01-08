from fastapi import APIRouter, HTTPException, Body
from typing import Optional
from app.services.procedure_service import procedure_service
from app.config import settings
import httpx
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_step_info_from_nodegraph_session(ng_session):
    """Extract step info from a NodeGraph session."""
    step_name = None
    step_action = None
    step_number = None

    node = ng_session.get_current_node()
    if node:
        step_name = node.ui.title
        step_action = node.ui.instruction
        # Step number is the position in visited_nodes + 1 (current)
        step_number = len(ng_session.visited_nodes) + 1

    return step_number, step_name, step_action


def _get_step_info_from_legacy_session(session):
    """Extract step info from a legacy session."""
    step_name = None
    step_action = None
    step_number = None

    if session.procedure and 0 <= session.current_index < len(session.procedure.steps):
        step = session.procedure.steps[session.current_index]
        step_name = step.name
        step_number = session.current_index + 1
        # Legacy steps don't have an action field
        step_action = None

    return step_number, step_name, step_action

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

    external_session_id = None
    procedure_name = None
    step_number = None
    step_name = None
    step_action = None

    # Check which strategy is active
    if settings.PROCEDURE_STRATEGY == "nodegraph":
        from app.services.nodegraph_service import get_nodegraph_service
        nodegraph_svc = get_nodegraph_service()

        ng_session = None
        if session_id:
            # Look up by external session ID
            for user, sess in nodegraph_svc._sessions.items():
                if sess.external_session_id == session_id:
                    ng_session = sess
                    break
            if not ng_session:
                logger.warning(f"No active NodeGraph session found for external ID {session_id}")
                raise HTTPException(status_code=404, detail=f"No active session found for session ID {session_id}")
        elif username:
            ng_session = nodegraph_svc.get_session(username)
            if not ng_session:
                logger.warning(f"No active NodeGraph session found for user {username}")
                raise HTTPException(status_code=400, detail=f"No active session found for user {username}")
        else:
            raise HTTPException(status_code=400, detail="Must provide either 'session_id' or 'username'")

        if not ng_session.external_session_id:
            logger.warning(f"Active NodeGraph session for user {ng_session.username} has no external session ID")
            raise HTTPException(status_code=400, detail="Active session has no external session ID (Memory Service not connected?)")

        external_session_id = ng_session.external_session_id
        procedure_name = ng_session.procedure.title
        step_number, step_name, step_action = _get_step_info_from_nodegraph_session(ng_session)

    else:
        # Legacy strategy
        session = None
        if session_id:
            session = procedure_service.get_session_by_external_id(session_id)
            if not session:
                logger.warning(f"No active session found for external ID {session_id}")
                raise HTTPException(status_code=404, detail=f"No active session found for session ID {session_id}")
        elif username:
            sessions = procedure_service._active_sessions.get(username)
            if sessions:
                session = sessions[0]
            else:
                logger.warning(f"No active session found for user {username}")
                raise HTTPException(status_code=400, detail=f"No active session found for user {username}")
        else:
            raise HTTPException(status_code=400, detail="Must provide either 'session_id' or 'username'")

        if not session.external_session_id:
            logger.warning(f"Active session for user {session.username} has no external session ID")
            raise HTTPException(status_code=400, detail="Active session has no external session ID (Memory Service not connected?)")

        external_session_id = session.external_session_id
        procedure_name = session.procedure.name if session.procedure else None
        step_number, step_name, step_action = _get_step_info_from_legacy_session(session)

    # 3. Prepare payload with correct field names for Memory Service
    payload = {
        "session_id": external_session_id,
        "query": query,
        "procedure_name": procedure_name,
        "step_number": step_number,
        "step_name": step_name,
        "step_action": step_action
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
