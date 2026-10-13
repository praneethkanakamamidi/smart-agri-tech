"""Crop recommendation. The model artifacts are loaded once per process, not on every request."""
import pickle
import threading
from pathlib import Path

import pandas as pd
from fastapi import HTTPException, status

from src.helpers.logging_config import get_logger

logger = get_logger(__name__)
MODEL_DIR = Path(__file__).resolve().parent.parent / "ml_models"
FEATURES = ("N", "P", "K", "temperature", "humidity", "ph", "rainfall")

_lock = threading.Lock()
_artifacts: tuple | None = None


def _load_artifacts() -> tuple:
    """Load model, scaler and label encoder (bundled, trusted files) once, thread-safely."""
    global _artifacts
    if _artifacts is None:
        with _lock:
            if _artifacts is None:
                loaded = []
                for name in ("model.pkl", "scaler.pkl", "label_encoder.pkl"):
                    with open(MODEL_DIR / name, "rb") as fh:
                        loaded.append(pickle.load(fh))
                _artifacts = tuple(loaded)
                logger.info("Crop recommendation model loaded.")
    return _artifacts


class ModelService:
    def predict_crop(self, payload) -> dict:
        """Predicts the crop type based on the input features and returns a dictionary."""
        features = {name: getattr(payload, name) for name in FEATURES}
        try:
            crop_model, scaler, label_encoder = _load_artifacts()
            columns = list(getattr(scaler, "feature_names_in_", FEATURES))
            frame = pd.DataFrame([[features[c] for c in columns]], columns=columns)  # same names/order as training
            input_data_scaled = scaler.transform(frame)
            predicted = crop_model.predict(input_data_scaled)[0]
            predicted_crop = label_encoder.inverse_transform([predicted])[0]
        except Exception:
            logger.exception("Crop prediction failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Crop recommendation is temporarily unavailable.",
            )
        return {"status": "success", "input_features": features, "predicted_crop": str(predicted_crop)}
