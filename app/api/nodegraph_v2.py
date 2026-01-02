"""Node Graph Procedure API endpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict

from app.config import settings

router = APIRouter()


class StartNodeGraphRequest(BaseModel):
    username: str
    procedure_id: str
    source_id: Optional[str] = None


class StopNodeGraphRequest(BaseModel):
    username: str


@router.post("/nodegraph/start")
async def start_nodegraph_procedure(request: StartNodeGraphRequest):
    """Start a node graph procedure for a user.
    
    This uses the NodeGraphProcedureService to load a knowledge graph
    procedure from the Memory Service and begin execution.
    """
    if settings.PROCEDURE_STRATEGY != "nodegraph":
        raise HTTPException(
            status_code=400, 
            detail="Node graph strategy is not enabled. Set PROCEDURE_STRATEGY=nodegraph"
        )
    
    try:
        from app.services.nodegraph_service import get_nodegraph_service
        service = get_nodegraph_service()
        
        result = await service.start_procedure(
            username=request.username,
            procedure_id=request.procedure_id,
            source_id=request.source_id
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nodegraph/stop")
async def stop_nodegraph_procedure(request: StopNodeGraphRequest):
    """Stop the active node graph procedure for a user."""
    if settings.PROCEDURE_STRATEGY != "nodegraph":
        raise HTTPException(
            status_code=400, 
            detail="Node graph strategy is not enabled"
        )
    
    try:
        from app.services.nodegraph_service import get_nodegraph_service
        service = get_nodegraph_service()
        
        stopped = await service.stop_procedure(request.username)
        if not stopped:
            raise HTTPException(status_code=404, detail="No active procedure for user")
        return {"status": "stopped", "username": request.username}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nodegraph/status/{username}")
async def get_nodegraph_status(username: str):
    """Get the current status of a user's node graph procedure."""
    if settings.PROCEDURE_STRATEGY != "nodegraph":
        raise HTTPException(
            status_code=400, 
            detail="Node graph strategy is not enabled"
        )
    
    try:
        from app.services.nodegraph_service import get_nodegraph_service
        service = get_nodegraph_service()
        
        session = service.get_session(username)
        if not session:
            raise HTTPException(status_code=404, detail="No active procedure for user")
        
        node = session.get_current_node()
        return {
            "username": username,
            "procedure_id": session.procedure.procedure_id,
            "procedure_title": session.procedure.title,
            "current_node": {
                "id": session.current_node_id,
                "type": node.type.value if node else None,
                "title": node.ui.title if node else "",
                "instruction": node.ui.instruction if node else ""
            },
            "validation_progress": len(session.validation_buffer),
            "action_timer_active": session.action_timer_start is not None,
            "inflight": session.inflight
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nodegraph/debug")
async def get_nodegraph_debug():
    """Get debug state for all active node graph sessions."""
    if settings.PROCEDURE_STRATEGY != "nodegraph":
        raise HTTPException(
            status_code=400, 
            detail="Node graph strategy is not enabled"
        )
    
    try:
        from app.services.nodegraph_service import get_nodegraph_service
        service = get_nodegraph_service()
        return service.get_debug_state()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nodegraph/available")
async def list_available_procedures():
    """List all available knowledge graph procedures.
    
    Returns a list of procedures that can be started with the current
    nodegraph strategy. Use these procedure_id values with the /start endpoint.
    """
    if settings.PROCEDURE_STRATEGY != "nodegraph":
        raise HTTPException(
            status_code=400, 
            detail="Node graph strategy is not enabled. Set PROCEDURE_STRATEGY=nodegraph"
        )
    
    try:
        from app.services.nodegraph_strategy import NodeGraphProcedureStrategy
        from app.services.memory_service_client import MemoryServiceClient
        
        memory_client = MemoryServiceClient(settings.MEMORY_SERVICE_URL)
        strategy = NodeGraphProcedureStrategy(memory_client)
        
        procedures = await strategy.list_available_procedures()
        
        return {
            "strategy": "nodegraph",
            "procedures": procedures
        }
    except Exception as e:
        # Check if it's a connection error to memory service
        error_msg = str(e)
        if "ConnectError" in error_msg or "Connection refused" in error_msg:
            raise HTTPException(
                status_code=503, 
                detail=f"Memory Service unavailable at {settings.MEMORY_SERVICE_URL}"
            )
        raise HTTPException(status_code=500, detail=str(e))
