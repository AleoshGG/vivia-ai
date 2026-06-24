import logging
import sys
from .settings import settings

def setup_logging():
    """
    Configura el logging de la aplicación.
    Se puede extender luego para usar structlog o JSON logs.
    """
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Mapeo simple de strings de nivel a constantes de logging
    numeric_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    
    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Reducir ruido de librerías externas si es necesario
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("google.auth").setLevel(logging.WARNING)
    
    return logging.getLogger("vivia_ai")
