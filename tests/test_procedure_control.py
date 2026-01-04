"""Tests for Procedure Control API endpoints."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def mock_settings():
    """Mock settings to enable nodegraph strategy."""
    with patch("app.api.procedure_control.settings") as mock:
        mock.PROCEDURE_STRATEGY = "nodegraph"
        yield mock


@pytest.fixture
def mock_nodegraph_service():
    """Mock the nodegraph service."""
    with patch("app.api.procedure_control.get_nodegraph_service") as mock_getter:
        service = MagicMock()
        mock_getter.return_value = service
        yield service


@pytest.fixture
def client(mock_settings):
    """Create test client with mocked settings."""
    from app.main import app
    return TestClient(app)


class TestAutoProgress:
    """Tests for the auto_progress endpoint."""
    
    def test_toggle_auto_progress_success(self, client, mock_nodegraph_service):
        """Test successfully toggling auto progress."""
        mock_nodegraph_service.set_auto_progress.return_value = True
        
        response = client.post(
            "/api/v2/procedures/nodegraph/control/auto_progress",
            json={"username": "test_user", "enabled": False}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "updated"
        assert data["username"] == "test_user"
        assert data["auto_progress_enabled"] == False
        mock_nodegraph_service.set_auto_progress.assert_called_once_with("test_user", False)
    
    def test_toggle_auto_progress_no_session(self, client, mock_nodegraph_service):
        """Test toggling when no active session exists."""
        mock_nodegraph_service.set_auto_progress.return_value = False
        
        response = client.post(
            "/api/v2/procedures/nodegraph/control/auto_progress",
            json={"username": "unknown_user", "enabled": True}
        )
        
        assert response.status_code == 404
        assert "No active session" in response.json()["detail"]


class TestForceNext:
    """Tests for the force_next endpoint."""
    
    def test_force_next_success(self, client, mock_nodegraph_service):
        """Test successfully forcing next step."""
        mock_nodegraph_service.force_next_node = AsyncMock(return_value={
            "node_id": "step_02",
            "type": "ACTION",
            "title": "Step 2",
            "instruction": "Do step 2"
        })
        
        response = client.post(
            "/api/v2/procedures/nodegraph/control/next",
            json={"username": "test_user"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "advanced"
        assert data["current_node"]["node_id"] == "step_02"
    
    def test_force_next_no_next_node(self, client, mock_nodegraph_service):
        """Test forcing next when at terminal node."""
        mock_nodegraph_service.force_next_node = AsyncMock(return_value=None)
        
        response = client.post(
            "/api/v2/procedures/nodegraph/control/next",
            json={"username": "test_user"}
        )
        
        assert response.status_code == 400
        assert "no next transition" in response.json()["detail"].lower()


class TestForcePrev:
    """Tests for the force_prev endpoint."""
    
    def test_force_prev_success(self, client, mock_nodegraph_service):
        """Test successfully forcing previous step."""
        mock_nodegraph_service.force_prev_node = AsyncMock(return_value={
            "node_id": "step_01",
            "type": "ACTION",
            "title": "Step 1",
            "instruction": "Do step 1"
        })
        
        response = client.post(
            "/api/v2/procedures/nodegraph/control/prev",
            json={"username": "test_user"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "reverted"
        assert data["current_node"]["node_id"] == "step_01"
    
    def test_force_prev_no_history(self, client, mock_nodegraph_service):
        """Test forcing prev when at start with no history."""
        mock_nodegraph_service.force_prev_node = AsyncMock(return_value=None)
        
        response = client.post(
            "/api/v2/procedures/nodegraph/control/prev",
            json={"username": "test_user"}
        )
        
        assert response.status_code == 400
        assert "no history" in response.json()["detail"].lower()


class TestControlStatus:
    """Tests for the control_status endpoint."""
    
    def test_get_control_status_success(self, client, mock_nodegraph_service):
        """Test getting control status."""
        mock_nodegraph_service.get_control_status.return_value = {
            "username": "test_user",
            "auto_progress_enabled": True,
            "current_node_id": "step_01",
            "current_node_title": "Step 1",
            "visited_nodes_count": 0,
            "can_go_prev": False,
            "can_go_next": True
        }
        
        response = client.get(
            "/api/v2/procedures/nodegraph/control/status",
            params={"username": "test_user"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "test_user"
        assert data["auto_progress_enabled"] == True
        assert data["can_go_prev"] == False
        assert data["can_go_next"] == True
    
    def test_get_control_status_no_session(self, client, mock_nodegraph_service):
        """Test getting status when no session exists."""
        mock_nodegraph_service.get_control_status.return_value = None
        
        response = client.get(
            "/api/v2/procedures/nodegraph/control/status",
            params={"username": "unknown_user"}
        )
        
        assert response.status_code == 404
        assert "No active session" in response.json()["detail"]


class TestStrategyGuard:
    """Tests that endpoints reject requests when not in nodegraph mode."""
    
    def test_rejects_when_not_nodegraph(self, client):
        """Test that endpoints return 400 when nodegraph is not enabled."""
        with patch("app.api.procedure_control.settings") as mock_settings:
            mock_settings.PROCEDURE_STRATEGY = "linear"
            
            response = client.post(
                "/api/v2/procedures/nodegraph/control/auto_progress",
                json={"username": "test", "enabled": True}
            )
            
            assert response.status_code == 400
            assert "not enabled" in response.json()["detail"].lower()
