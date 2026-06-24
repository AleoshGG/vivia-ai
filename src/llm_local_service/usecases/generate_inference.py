from shared.queue_publisher import QueuePublisher
import uuid

class GenerateInferenceUseCase:
    """
    Orquesta la inferencia del LLM local.
    """
    def __init__(self):
        self.publisher = QueuePublisher()
        
    def execute(self, prompt: str) -> str:
        job_id = str(uuid.uuid4())
        message = {
            "job_id": job_id,
            "prompt": prompt,
            "task": "llm_inference"
        }
        self.publisher.publish("llm_queue", message)
        return job_id
