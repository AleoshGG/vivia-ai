import asyncio
import logging
import threading
import time

import pika

from config.settings import settings
from ..models.property import PropertyRequest
from ..services.anomaly_model import AnomalyModel
from ..usecases.analyze_property import AnalyzePropertyUseCase

logger = logging.getLogger(__name__)

QUEUE_NAME = "vivia.validation.anomaly.submit"
DLQ_NAME = "vivia.dlq"


class AnomalyQueueConsumer:

    def __init__(self, model: AnomalyModel):
        self._model      = model
        self._stop_event = threading.Event()
        self._connection = None
        self._channel    = None

    def run(self):
        delay = 5
        while not self._stop_event.is_set():
            try:
                self._connect()
                logger.info("AnomalyQueueConsumer conectado. Esperando mensajes en %s.", QUEUE_NAME)
                self._channel.start_consuming()
                delay = 5
            except Exception as e:
                if self._stop_event.is_set():
                    break
                logger.error("AnomalyQueueConsumer error: %s. Reintentando en %ds...", e, delay)
                self._close_connection()
                time.sleep(delay)
                delay = min(delay * 2, 60)

    def stop(self):
        self._stop_event.set()
        self._close_connection()

    def _connect(self):
        credentials = pika.PlainCredentials(settings.rabbitmq_user, settings.rabbitmq_password)
        parameters = pika.ConnectionParameters(
            host=settings.rabbitmq_host,
            port=settings.rabbitmq_port,
            virtual_host=settings.rabbitmq_vhost,
            credentials=credentials,
            heartbeat=60,
        )
        self._connection = pika.BlockingConnection(parameters)
        self._channel = self._connection.channel()

        self._channel.queue_declare(
            queue=QUEUE_NAME,
            durable=True,
            arguments={
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": DLQ_NAME,
            },
        )
        self._channel.basic_qos(prefetch_count=1)
        self._channel.basic_consume(queue=QUEUE_NAME, on_message_callback=self._on_message)

    def _close_connection(self):
        try:
            if self._connection and not self._connection.is_closed:
                self._connection.close()
        except Exception:
            pass

    def _on_message(self, ch, method, properties, body):
        import json
        draft_id = "unknown"
        try:
            payload = json.loads(body)
            draft_id = payload.get("draft", {}).get("id", "unknown")
            request = PropertyRequest.model_validate({"draft": payload["draft"]})
            asyncio.run(AnalyzePropertyUseCase(self._model).execute(request))
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as e:
            logger.error("Error procesando mensaje de anomalía draftId=%s: %s", draft_id, e)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
