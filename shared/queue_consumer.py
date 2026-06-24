import pika
import json
import logging
from typing import Callable, Any
from config.settings import settings

logger = logging.getLogger(__name__)

class QueueConsumer:
    """
    Consumidor de RabbitMQ genérico.
    """
    def __init__(self, queue_name: str):
        self.queue_name = queue_name
        self._connection = None
        self._channel = None

    def connect(self):
        try:
            credentials = pika.PlainCredentials(settings.rabbitmq_user, settings.rabbitmq_password)
            parameters = pika.ConnectionParameters(
                host=settings.rabbitmq_host,
                port=settings.rabbitmq_port,
                virtual_host=settings.rabbitmq_vhost,
                credentials=credentials
            )
            self._connection = pika.BlockingConnection(parameters)
            self._channel = self._connection.channel()
            
            # Durable queue
            self._channel.queue_declare(queue=self.queue_name, durable=True)
            # Solo un mensaje a la vez (Fair dispatch)
            self._channel.basic_qos(prefetch_count=1)
            
            logger.info(f"Connected to RabbitMQ for consuming from {self.queue_name}.")
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise

    def start_consuming(self, callback: Callable[[Any, Any, Any, dict], None]):
        """
        Inicia el consumo de mensajes usando un callback.
        El callback debe recibir (ch, method, properties, payload_dict).
        """
        if not self._channel or self._channel.is_closed:
            self.connect()

        def wrapper(ch, method, properties, body):
            try:
                payload = json.loads(body)
                callback(ch, method, properties, payload)
                # Confirmar procesamiento
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                # Rechazar mensaje, requeue=False si queremos enviarlo a DLQ (idealmente configurada)
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

        self._channel.basic_consume(queue=self.queue_name, on_message_callback=wrapper)
        logger.info(f"[*] Waiting for messages in {self.queue_name}. To exit press CTRL+C")
        self._channel.start_consuming()

    def close(self):
        if self._connection and not self._connection.is_closed:
            self._connection.close()
