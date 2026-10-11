import json
import os
from pathlib import Path

import pandas as pd
import numpy as np
from sklearn.metrics import classification_report, roc_auc_score, average_precision_score, confusion_matrix
from xgboost import XGBClassifier


BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = Path(os.getenv("DATASET_PATH", str(BASE_DIR / "training data/cab_ins02_dataset.json")))
MODEL_PATH = Path(os.getenv("OUTPUT_MODEL_PATH", str(BASE_DIR / "models/xgb_cab_ins02.json")))


def chronological_splits(df):
    """Split real observations before any training-only transformations."""
    if len(df) < 10:
        raise ValueError("At least ten observations are needed for train/dev/test")
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="raise")
    df = df.sort_values("timestamp").reset_index(drop=True)
    first, second = int(len(df) * 0.6), int(len(df) * 0.8)
    # Keep simultaneous readings on the same side of each boundary.
    train_end, dev_end = df.iloc[first]["timestamp"], df.iloc[second]["timestamp"]
    splits = (df[df.timestamp < train_end], df[(df.timestamp >= train_end) & (df.timestamp < dev_end)], df[df.timestamp >= dev_end])
    if any(part.empty for part in splits):
        raise ValueError("Not enough distinct timestamps for three independent splits")
    return splits

FEATURE_COLUMNS = [
    "pvc_screw_pressure_bar",
    "color_screw_pressure_bar",
    "nylon_screw_pressure_bar",
    "pvc_screw_speed_rpm",
    "color_screw_speed_rpm",
    "nylon_screw_speed_rpm",
    "motor_load_amps",
    "motor_load_percent",
    "line_speed_m_min",
    "payoff_tension_n",
    "takeup_tension_n",
    "post_extrusion_diameter_mm",
    "machine_status",
]


def load_dataset(path: Path) -> pd.DataFrame:
    with path.open() as f:
        data = json.load(f)
    rows = []
    for item in data:
        row = {
            "machine_id": item.get("machine_id"),
            "timestamp": item.get("timestamp"),
        }
        row.update(item.get("features", {}))
        rows.append(row)
    df = pd.DataFrame(rows)
    return df


def main() -> None:
    df = load_dataset(DATA_PATH)

    # Target label (binary)
    if "maintenance_required" not in df.columns:
        raise RuntimeError("Missing target label: maintenance_required")

    train, dev, test = chronological_splits(df)
    feature_cols = FEATURE_COLUMNS
    X_train, y_train = train[feature_cols], train["maintenance_required"].astype(int)
    X_dev, y_dev = dev[feature_cols], dev["maintenance_required"].astype(int)
    X_test, y_test = test[feature_cols], test["maintenance_required"].astype(int)
    if y_train.nunique() < 2:
        raise ValueError("Training split must contain both classes")
    # Do not invent normal labels from small sensor changes. Dev/test stay real.

    # Add Gaussian jitter to encourage robustness against tiny variations.
    std = X_train[feature_cols].std(ddof=0).replace(0, 1.0)
    jitter = np.random.default_rng(42).normal(size=X_train.shape) * (std.values * 0.01)
    X_train_jitter = X_train.reset_index(drop=True) + pd.DataFrame(jitter, columns=feature_cols)
    X_train_jitter["machine_status"] = X_train["machine_status"].to_numpy()

    # Monotonic constraints: +1 increasing risk, -1 decreasing risk, 0 unknown.
    # Pressures (+1), motor loads (+1), screw speeds (-1), line speed (-1).
    monotone_constraints = (
        1,  # pvc_screw_pressure_bar
        1,  # color_screw_pressure_bar
        1,  # nylon_screw_pressure_bar
        -1, # pvc_screw_speed_rpm
        -1, # color_screw_speed_rpm
        -1, # nylon_screw_speed_rpm
        1,  # motor_load_amps
        1,  # motor_load_percent
        -1, # line_speed_m_min
        0,  # payoff_tension_n
        0,  # takeup_tension_n
        1,  # post_extrusion_diameter_mm (larger diameter = higher risk)
        0,  # machine_status
    )

    model = XGBClassifier(
        n_estimators=400,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        min_child_weight=30,
        gamma=2.0,
        reg_lambda=2.0,
        objective="binary:logistic",
        eval_metric="logloss",
        n_jobs=4,
        random_state=42,
        monotone_constraints=monotone_constraints,
    )
    model.fit(X_train_jitter, y_train)
    print("Dev report (threshold=0.5):", classification_report(y_dev, model.predict(X_dev), zero_division=0))

    # Evaluation
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]
    report = classification_report(y_test, y_pred, digits=3)
    auc = roc_auc_score(y_test, y_prob) if y_test.nunique() > 1 else None

    print("Features:", feature_cols)
    print("\nClassification Report:\n", report)
    print(f"ROC-AUC: {auc if auc is not None else 'undefined (single-class test set)'}")
    print("Average precision:", average_precision_score(y_test, y_prob) if y_test.sum() else "undefined (no positives)")
    print("Confusion matrix [TN FP; FN TP]:", confusion_matrix(y_test, y_pred, labels=[0, 1]).tolist())

    # Save model
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(MODEL_PATH)
    print(f"\nSaved model to: {MODEL_PATH}")


if __name__ == "__main__":
    main()
