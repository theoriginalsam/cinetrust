"""MLflow pyfunc wrapper so the trust model lives in the Unity Catalog model registry."""

from __future__ import annotations

import mlflow.pyfunc
import pandas as pd

from .features import MODEL_FEATURES
from .trust import TrustModel


class TrustPyfunc(mlflow.pyfunc.PythonModel):
    def __init__(self, model: TrustModel):
        self.model = model

    def predict(self, context, model_input: pd.DataFrame, params=None) -> pd.DataFrame:
        return self.model.predict(model_input[MODEL_FEATURES].reset_index(drop=True))
