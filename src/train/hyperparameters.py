"""LightGBM hyperparameters for occupancy prediction model."""

LIGHTGBM_PARAMS = {
    "objective": "regression",
    "metric": "mae",
    "boosting_type": "gbdt",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "verbose": -1,
}

NUM_BOOST_ROUNDS = 100

VALIDATION_SPLIT = 0.1  # Last 10% of data for validation

FEATURE_COLUMNS = [
    "facility",
    "hour",
    "day_of_week",
    "month",
    "is_weekend",
    "is_holiday",
    "is_school_vacation",
    "temperature_c",
    "precipitation_mm",
    "weather_code",
]

TARGET_COLUMN = "occupancy_percent"

CATEGORICAL_FEATURES = ["facility"]
