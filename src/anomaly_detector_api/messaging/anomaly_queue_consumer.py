import asyncio
import logging
import threading
import time

import pika

from config.settings import settings
from ..models.property import PropertyRequest
from ..persistence.database import build_engine, build_session_factory
from ..persistence.inference_repository import InferenceRepository
from ..services.anomaly_model import AnomalyModel
from ..services.text_risk import TextRiskService
from ..services.text_risk.llm_text_client import LlamaTextRiskClient
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
        # El consumer corre en su PROPIO hilo y mantiene su PROPIO event loop y
        # engine async. asyncpg ata cada conexión al event loop donde se creó,
        # así que NO se puede reutilizar el engine del lifespan (vive en el loop
        # de uvicorn): hacerlo provoca "got Future attached to a different loop".
        # Por eso loop, engine y repositorio se construyen dentro de run().
        self._loop       = None
        self._engine     = None
        self._repository = None
        self._text_risk  = None

    def run(self):
        # Loop + engine dedicados a este hilo (ver nota en __init__). Se crean una
        # sola vez y se reutilizan para todos los mensajes.
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._engine = build_engine()
        self._repository = InferenceRepository(build_session_factory(self._engine))
        # Cliente sin estado (httpx por llamada) — seguro en este hilo/loop.
        self._text_risk = TextRiskService(
            LlamaTextRiskClient(
                settings.llama_server_url,
                timeout=settings.text_risk_timeout,
                max_tokens=settings.text_risk_max_tokens,
            ),
            enabled=settings.text_risk_enabled,
        )

        delay = 5
        try:
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
        finally:
            # Cierre ordenado del engine dentro de su propio loop.
            try:
                self._loop.run_until_complete(self._engine.dispose())
            finally:
                self._loop.close()

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
            use_case = AnalyzePropertyUseCase(
                self._model, self._repository, self._text_risk, source="queue"
            )
            # Mismo loop dedicado del hilo (no asyncio.run, que crearía uno nuevo
            # por mensaje y rompería el engine asyncpg atado a este loop).
            self._loop.run_until_complete(use_case.execute(request))
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as e:
            logger.error("Error procesando mensaje de anomalía draftId=%s: %s", draft_id, e)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
