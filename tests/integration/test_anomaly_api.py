import pytest

def test_anomaly_health(client):
    response = client.get("/api/anomaly/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_anomaly_detect_unauthorized(client):
    response = client.post("/api/anomaly/detect", json={"data_key": "test"})
    assert response.status_code == 403

# def test_anomaly_detect_authorized(client, auth_headers):
#     # Requires mocking RabbitMQ
#     pass
