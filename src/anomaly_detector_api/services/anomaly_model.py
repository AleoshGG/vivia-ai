import logging

import pandas as pd

from shared.model_loader import ModelLoader

logger = logging.getLogger(__name__)


class AnomalyModel:
    """
    Carga el modelo de anomalías desde el Model Registry de MLflow una sola vez
    al startup y expone predict(). El modelo `pyfunc` empaqueta el Isolation
    Forest, su scaler, el umbral y el orden de columnas (ver `anomaly_pyfunc`).
    """

    def __init__(self, model_name: str, stage: str = "Production"):
        self._model_name = model_name
        self._stage      = stage
        self._pyfunc     = None
        self._version    = None
        self._cols       = None

    def load(self) -> None:
        loader = ModelLoader()
        self._pyfunc, self._version = loader.load_model(self._model_name, self._stage)
        impl = self._pyfunc.unwrap_python_model()
        self._cols = impl.feature_cols
        logger.info(
            "Modelo de anomalías cargado — name=%s stage=%s version=%s features=%d",
            self._model_name, self._stage, self._version, len(self._cols),
        )

    def predict(self, raw_features: pd.DataFrame) -> tuple[bool, float]:
        """Clasifica un vector de features. Síncrono — llamar desde run_in_executor."""
        result = self._pyfunc.predict(raw_features)
        row = result.iloc[0]
        return bool(row["is_anomaly"]), float(row["score"])

    @property
    def feature_cols(self) -> list[str]:
        return self._cols

    @property
    def model_version(self) -> str:
        return self._version
