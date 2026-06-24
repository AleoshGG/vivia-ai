import pika
import json
import logging
from typing import Any, Dict
from config.settings import settings

logger = logging.getLogger(__name__)

class QueuePublisher:
    """
    Clase para publicar mensajes en RabbitMQ.
    """
    def __init__(self):
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
            logger.info("Connected to RabbitMQ for publishing.")
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise

    def publish(self, queue_name: str, message: Dict[str, Any]):
        """
        Publica un mensaje (diccionario) en una cola específica asegurando persistencia.
        """
        if not self._channel or self._channel.is_closed:
            self.connect()
        
        # Asegurarse que la cola existe (durable=True para que no se pierda al reiniciar RMQ)
        self._channel.queue_declare(queue=queue_name, durable=True)

        self._channel.basic_publish(
            exchange='',
            routing_key=queue_name,
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,  # 2 = persistente
                content_type='application/json'
            )
        )
        logger.debug(f"Published message to {queue_name}: {message}")

    def close(self):
        if self._connection and not self._connection.is_closed:
            self._connection.close()
