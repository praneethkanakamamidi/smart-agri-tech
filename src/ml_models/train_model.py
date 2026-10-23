"""
Trains the crop recommendation model and writes the artifacts the API loads.

    python -m src.ml_models.train_model

Run from the project root so the 'src' package resolves.
"""

import pickle

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, LabelEncoder

from src.helpers.logging_config import get_logger

logger = get_logger(__name__)

DATASET_PATH = 'src/data_source/crop_dataset.csv'
FEATURES = ['N', 'P', 'K', 'temperature', 'humidity', 'ph', 'rainfall']
ARTIFACTS = {
    'model': 'src/ml_models/model.pkl',
    'scaler': 'src/ml_models/scaler.pkl',
    'label_encoder': 'src/ml_models/label_encoder.pkl',
}


def load_dataset(filepath: str) -> pd.DataFrame:
    """Loads the dataset from a CSV file."""
    df = pd.read_csv(filepath)
    logger.info(f"Loaded dataset {filepath}: {df.shape[0]} rows, {df.shape[1]} columns")
    return df


def preprocess_data(df: pd.DataFrame):
    """Selects features, encodes the target, splits 80/20 and standardises the features."""
    X = df[FEATURES]
    label_encoder = LabelEncoder()
    y_encoded = label_encoder.fit_transform(df['label'])

    X_train, X_test, y_train, y_test = train_test_split(X, y_encoded, test_size=0.2, random_state=42)

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    logger.info(f"Split: {len(X_train)} train, {len(X_test)} test; {len(label_encoder.classes_)} crop classes")
    return X_train_scaled, X_test_scaled, y_train, y_test, scaler, label_encoder


def train_model(X_train, y_train) -> RandomForestClassifier:
    """Trains a RandomForest model."""
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    return model


def save_objects(model, scaler, label_encoder):
    """Saves the model and preprocessing objects."""
    for name, obj in (('model', model), ('scaler', scaler), ('label_encoder', label_encoder)):
        with open(ARTIFACTS[name], 'wb') as f:
            pickle.dump(obj, f)
        logger.info(f"Saved {ARTIFACTS[name]}")


if __name__ == "__main__":
    try:
        df = load_dataset(DATASET_PATH)
        X_train_scaled, X_test_scaled, y_train, y_test, scaler, label_encoder = preprocess_data(df)
        model = train_model(X_train_scaled, y_train)
        logger.info(f"Hold-out accuracy: {model.score(X_test_scaled, y_test):.4f}")
        save_objects(model, scaler, label_encoder)
    except Exception:
        logger.exception("Training pipeline failed")
        raise
