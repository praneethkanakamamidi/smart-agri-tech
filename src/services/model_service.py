from fastapi import HTTPException, status
import pickle
import numpy as np
from src.helpers.logging_config import logging  # Import logger

class ModelService:
    def predict_crop(self, payload) -> dict:
        """Predicts the crop type based on the input features and returns a dictionary."""
        try:
            logging.info("Loading model, scaler, and label encoder...")

            with open('src/ml_models/model.pkl', 'rb') as model_file:
                crop_model = pickle.load(model_file)
            with open('src/ml_models/scaler.pkl', 'rb') as scaler_file:
                scaler = pickle.load(scaler_file)
            with open('src/ml_models/label_encoder.pkl', 'rb') as label_encoder_file:
                label_encoder = pickle.load(label_encoder_file)

            logging.info("Model, scaler, and label encoder loaded successfully.")

            # Extracting features
            features = {
                "N": payload.N,
                "P": payload.P,
                "K": payload.K,
                "temperature": payload.temperature,
                "humidity": payload.humidity,
                "ph": payload.ph,
                "rainfall": payload.rainfall,
            }
            logging.info(f"Received input features: {features}")

            # Convert to numpy array and scale
            input_data = np.array([list(features.values())])
            input_data_scaled = scaler.transform(input_data)

            # Predict crop
            predicted_crop_encoded = crop_model.predict(input_data_scaled)[0]
            predicted_crop = label_encoder.inverse_transform([predicted_crop_encoded])[0]

            logging.info(f"Predicted crop: {predicted_crop}")

            return {
                "status": "success",
                "input_features": features,
                "predicted_crop": predicted_crop,
            }

        except Exception as e:
            logging.exception(f"Error in model prediction: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "Internal Server Error", "message": str(e)},
                headers={"Content-Type": "application/json"}
            )
