import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    """Test client for Anomaly Detector API"""
    # Import perezoso: permite correr los tests de otros servicios sin instalar
    # las dependencias pesadas de anomalías (mlflow, sqlalchemy, pika).
    from src.anomaly_detector_api.main import app
    return TestClient(app)

@pytest.fixture
def auth_headers():
    return {"X-Internal-API-Key": "changeme-super-secret-key"}
