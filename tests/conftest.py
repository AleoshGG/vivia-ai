import pytest
from fastapi.testclient import TestClient
from src.anomaly_detector_api.main import app

@pytest.fixture
def client():
    """Test client for Anomaly Detector API"""
    return TestClient(app)

@pytest.fixture
def auth_headers():
    return {"X-Internal-API-Key": "changeme-super-secret-key"}
