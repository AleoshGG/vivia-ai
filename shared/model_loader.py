import logging
# import mlflow
# import mlflow.pyfunc

logger = logging.getLogger(__name__)

class ModelLoader:
    """
    Clase para cargar modelos desde MLflow.
    Implementación comentada temporalmente para evitar fallo si MLflow no está arriba.
    """
    def __init__(self):
        pass

    def load_model(self, model_name: str, stage: str = "Production"):
        """
        Descarga el modelo con stage 'Production' desde MLflow.
        """
        # TODO: Implementar integración con MLflow
        # model_uri = f"models:/{model_name}/{stage}"
        # logger.info(f"Loading model {model_uri}")
        # model = mlflow.pyfunc.load_model(model_uri)
        # return model
        logger.info(f"[STUB] Loading model {model_name} (stage: {stage})")
        return None
