import pytest
import asyncio
from unittest.mock import MagicMock, patch
from app.services.procedure_service import ProcedureService
from app.domain.models import ProcedureDef, UserSession
from app.domain.entities import Event, EventType, Frame

@pytest.fixture
def mock_engine():
    with patch("app.services.procedure_service.ProcedureEngine") as MockEngine:
        engine = MockEngine.return_value
        engine.start_procedure.return_value = []
        engine.ingest_frame.return_value = []
        yield engine

@pytest.fixture
def mock_ingest():
    with patch("app.services.procedure_service.ingest_service") as MockIngest:
        MockIngest.get_source.return_value = MagicMock(id="cam1")
        yield MockIngest

@pytest.fixture
def mock_load_proc():
    with patch("app.services.procedure_service.load_procedure") as MockLoad:
        MockLoad.return_value = ProcedureDef(id="proc1", name="Test", version=1, steps=[])
        yield MockLoad

@pytest.fixture
def service(mock_engine, mock_ingest, mock_load_proc):
    return ProcedureService()

def test_start_procedure_replace(service, mock_engine):
    # Start first procedure
    service.start_procedure("user1", "proc1", "cam1", policy="replace")
    assert len(service._active_sessions["user1"]) == 1
    
    # Start second with replace
    service.start_procedure("user1", "proc2", "cam1", policy="replace")
    assert len(service._active_sessions["user1"]) == 1
    assert mock_engine.abort.called

def test_start_procedure_parallel(service):
    service.start_procedure("user1", "proc1", "cam1", policy="parallel")
    service.start_procedure("user1", "proc2", "cam1", policy="parallel")
    assert len(service._active_sessions["user1"]) == 2

def test_start_procedure_queue(service):
    service.start_procedure("user1", "proc1", "cam1", policy="replace")
    
    # Queue second
    res = service.start_procedure("user1", "proc2", "cam1", policy="queue")
    assert res["status"] == "queued"
    assert len(service._active_sessions["user1"]) == 1
    assert len(service._queued_sessions["user1"]) == 1

@pytest.mark.asyncio
async def test_frame_ingestion(service, mock_engine):
    service.start_procedure("user1", "proc1", "cam1", policy="replace")
    
    event = Event(
        type=EventType.FRAME_CREATED,
        job_id=None,
        source_id="cam1",
        payload={"frame": Frame(id="f1", source_id="cam1", timestamp_ms=1000, data=b"")}
    )
    
    await service._on_frame_created(event)
    mock_engine.ingest_frame.assert_called()

if __name__ == "__main__":
    # Manual run helper if pytest not available
    print("Please run with pytest")
