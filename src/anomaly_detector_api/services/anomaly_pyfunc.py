import json

import joblib
import mlflow.pyfunc
import pandas as pd


class AnomalyDetectorModel(mlflow.pyfunc.PythonModel):
    """
    Modelo `pyfunc` que empaqueta el Isolation Forest, su scaler, el umbral de
    decisión y el orden de columnas en una sola versión del Model Registry.

    Recibe un DataFrame ya transformado por `build_features` y devuelve un
    DataFrame con las columnas `is_anomaly` (bool) y `score` (float).
    """

    def load_context(self, context):
        self.model = joblib.load(context.artifacts["model"])
        self.scaler = joblib.load(context.artifacts["scaler"])
        self.feature_cols = json.loads(
            open(context.artifacts["feature_columns"], encoding="utf-8").read()
        )
        metadata = json.loads(
            open(context.artifacts["metadata"], encoding="utf-8").read()
        )
        self.threshold = metadata["score_threshold"]

    def predict(self, context, model_input: pd.DataFrame) -> pd.DataFrame:
        frame = model_input.reindex(columns=self.feature_cols, fill_value=0.0)
        scaled = self.scaler.transform(frame)
        scores = self.model.decision_function(scaled)
        return pd.DataFrame(
            {
                "is_anomaly": [-s > self.threshold for s in scores],
                "score": [float(s) for s in scores],
            }
        )
