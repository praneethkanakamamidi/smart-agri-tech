"""
Run this script from the project root directory using:

    python -m src.ml_models.train_model

This ensures that the 'src' package is correctly recognized and module imports work properly.
"""

import pandas as pd
import pickle
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.ensemble import RandomForestClassifier
from src.helpers.logging_config import logging  # Not used for now

def load_dataset(filepath: str) -> pd.DataFrame:
    """Loads the dataset from a CSV file."""
    print("-" * 50)
    print(f"Loading dataset from: {filepath} ...")
    try:
        df = pd.read_csv(filepath)
        print(f"Dataset loaded successfully. Shape: {df.shape}")
        return df
    except Exception as e:
        print(f"Error loading dataset: {e}")
        raise

def preprocess_data(df: pd.DataFrame):
    """Preprocesses the data: feature extraction, encoding, and scaling."""
    print("-" * 50)
    print("Starting data preprocessing...")

    try:
        # Selecting relevant features and target variable
        X = df[['N', 'P', 'K', 'temperature', 'humidity', 'ph', 'rainfall']]
        y = df['label']

        # Encode categorical target variable
        label_encoder = LabelEncoder()
        y_encoded = label_encoder.fit_transform(y)
        print("Target variable encoded.")

        # Split data into training and test sets (80-20 split)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_encoded, test_size=0.2, random_state=42
        )
        print(f"Data split: {X_train.shape[0]} train, {X_test.shape[0]} test.")

        # Standardize features for better model performance
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        print("Feature scaling applied.")

        return X_train_scaled, X_test_scaled, y_train, y_test, scaler, label_encoder
    except Exception as e:
        print(f"Error during preprocessing: {e}")
        raise

def train_model(X_train, y_train) -> RandomForestClassifier:
    """Trains a RandomForest model."""
    print("-" * 50)
    print("Training RandomForest model...")
    try:
        model = RandomForestClassifier(n_estimators=100, random_state=42)
        model.fit(X_train, y_train)
        print("Model training completed successfully.")
        return model
    except Exception as e:
        print(f"Error training model: {e}")
        raise

def save_objects(model, scaler, label_encoder):
    """Saves model and preprocessing objects."""
    print("-" * 50)
    print("Saving model and preprocessing objects...")
    try:
        with open('src/ml_models/model.pkl', 'wb') as f:
            pickle.dump(model, f)
        print("Model saved: src/ml_models/model.pkl")

        with open('src/ml_models/scaler.pkl', 'wb') as f:
            pickle.dump(scaler, f)
        print("Scaler saved: src/ml_models/scaler.pkl")

        with open('src/ml_models/label_encoder.pkl', 'wb') as f:
            pickle.dump(label_encoder, f)
        print("Label encoder saved: src/ml_models/label_encoder.pkl")

    except Exception as e:
        print(f"Error saving objects: {e}")
        raise

if __name__ == "__main__":
    print("=" * 50)
    print("Starting the training pipeline...")

    try:
        df = load_dataset('src/data_source/crop_dataset.csv')
        X_train_scaled, X_test_scaled, y_train, y_test, scaler, label_encoder = preprocess_data(df)
        model = train_model(X_train_scaled, y_train)
        save_objects(model, scaler, label_encoder)
        print("=" * 50)
        print("Training pipeline completed successfully!")
    except Exception as e:
        print("=" * 50)
        print(f"CRITICAL ERROR: {e}")
        raise
