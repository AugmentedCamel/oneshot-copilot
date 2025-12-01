from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.services.procedure_service import procedure_service

router = APIRouter()

class StartProcedureRequest(BaseModel):
    username: str
    procedure_id: str
    source_id: Optional[str] = None
    policy: str = "replace"  # replace, parallel, queue

class StopProcedureRequest(BaseModel):
    username: str
    procedure_id: str

@router.post("/procedures/start")
async def start_procedure(request: StartProcedureRequest):
    try:
        result = await procedure_service.start_procedure(
            username=request.username,
            procedure_id=request.procedure_id,
            source_id=request.source_id,
            policy=request.policy
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/procedures/stop")
async def stop_procedure(request: StopProcedureRequest):
    try:
        stopped = await procedure_service.stop_procedure(
            username=request.username,
            procedure_id=request.procedure_id
        )
        if not stopped:
            raise HTTPException(status_code=404, detail="Procedure not found or not active")
        return {"status": "stopped", "procedure_id": request.procedure_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
