from shared.queue_publisher import QueuePublisher
import uuid

class DetectAnomalyUseCase:
    """
    Orquesta el proceso de detección de anomalías.
    En la versión actual, publica un trabajo en la cola.
    """
    def __init__(self):
        self.publisher = QueuePublisher()
        
    def execute(self, data_key: str) -> str:
        job_id = str(uuid.uuid4())
        message = {
            "job_id": job_id,
            "data_key": data_key,
            "task": "anomaly_detection"
        }
        self.publisher.publish("anomaly_queue", message)
        return job_id
