import json
import logging
from pathlib import Path

import joblib
import numpy as np

logger = logging.getLogger(__name__)


class AnomalyModel:
    """Carga los artefactos del modelo una sola vez al startup y expone predict()."""

    def __init__(self, model_dir: Path):
        self._model_dir = model_dir
        self._model     = None
        self._scaler    = None
        self._cols      = None
        self._threshold = None

    def load(self) -> None:
        self._model     = joblib.load(self._model_dir / 'isolation_forest_v1.joblib')
        self._scaler    = joblib.load(self._model_dir / 'scaler_v1.joblib')
        self._cols      = json.loads((self._model_dir / 'feature_columns_v1.json').read_text())
        metadata        = json.loads((self._model_dir / 'metadata_v1.json').read_text())
        self._threshold = metadata['score_threshold']
        logger.info(
            "Modelo de anomalías cargado — roc_auc=%s  threshold=%s  features=%d",
            metadata.get('roc_auc'), self._threshold, len(self._cols),
        )

    def predict(self, raw_features: np.ndarray) -> tuple[bool, float]:
        """Escala y clasifica. Síncrono — llamar desde run_in_executor."""
        scaled = self._scaler.transform(raw_features)
        score  = float(self._model.decision_function(scaled)[0])
        return (-score > self._threshold), score

    @property
    def feature_cols(self) -> list[str]:
        return self._cols
