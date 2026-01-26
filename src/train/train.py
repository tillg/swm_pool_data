#!/usr/bin/env python3
"""Train LightGBM model for facility occupancy prediction."""

import argparse
import logging
import pickle
import sys
from pathlib import Path

import lightgbm as lgb
import pandas as pd
from sklearn.metrics import mean_absolute_error

from hyperparameters import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    LIGHTGBM_PARAMS,
    NUM_BOOST_ROUNDS,
    TARGET_COLUMN,
    VALIDATION_SPLIT,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_data(data_path: Path) -> pd.DataFrame:
    """Load and prepare training data."""
    df = pd.read_csv(data_path)
    logger.info(f"Loaded {len(df)} rows from {data_path}")

    # Convert facility to categorical
    df["facility"] = df["pool_name"].astype("category")

    # Keep only rows where facility is open
    df = df[df["is_open"] == 1].copy()
    logger.info(f"Filtered to {len(df)} rows where facility is open")

    return df


def train_model(df: pd.DataFrame) -> tuple[lgb.Booster, float]:
    """Train LightGBM model with time-based split."""
    # Sort by timestamp for time-based split
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Split: last 10% for validation
    split_idx = int(len(df) * (1 - VALIDATION_SPLIT))
    train_df = df.iloc[:split_idx]
    val_df = df.iloc[split_idx:]

    logger.info(f"Train set: {len(train_df)} rows, Validation set: {len(val_df)} rows")

    X_train = train_df[FEATURE_COLUMNS]
    y_train = train_df[TARGET_COLUMN]
    X_val = val_df[FEATURE_COLUMNS]
    y_val = val_df[TARGET_COLUMN]

    train_data = lgb.Dataset(
        X_train, label=y_train,
        categorical_feature=CATEGORICAL_FEATURES
    )
    val_data = lgb.Dataset(
        X_val, label=y_val,
        categorical_feature=CATEGORICAL_FEATURES,
        reference=train_data
    )

    model = lgb.train(
        LIGHTGBM_PARAMS,
        train_data,
        num_boost_round=NUM_BOOST_ROUNDS,
        valid_sets=[val_data],
        callbacks=[lgb.log_evaluation(period=20)],
    )

    # Calculate MAE on validation set
    y_pred = model.predict(X_val)
    mae = mean_absolute_error(y_val, y_pred)

    return model, mae


def save_model(model: lgb.Booster, output_path: Path) -> None:
    """Save trained model to pickle file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        pickle.dump(model, f)
    logger.info(f"Model saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Train occupancy prediction model")
    parser.add_argument(
        "--data",
        type=str,
        default="../../datasets/occupancy_features.csv",
        help="Path to training data CSV"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="../../models/occupancy_model.pkl",
        help="Path to save trained model"
    )

    args = parser.parse_args()

    data_path = Path(args.data)
    output_path = Path(args.output)

    if not data_path.exists():
        logger.error(f"Data file not found: {data_path}")
        sys.exit(1)

    df = load_data(data_path)

    if len(df) == 0:
        logger.error("No training data available")
        sys.exit(1)

    logger.info("Training model...")
    model, mae = train_model(df)

    logger.info(f"Validation MAE: {mae:.2f} percentage points")

    save_model(model, output_path)
    logger.info("Training complete")


if __name__ == "__main__":
    main()
