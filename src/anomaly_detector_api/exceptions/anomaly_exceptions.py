from shared.exceptions import BaseServiceException

class AnomalyDetectionError(BaseServiceException):
    def __init__(self, message: str):
        super().__init__(message, code="anomaly_detection_error")
