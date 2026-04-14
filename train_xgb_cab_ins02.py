import json
from pathlib import Path

import pandas as pd
import numpy as np
from sklearn.metrics import classification_report, roc_auc_score
from xgboost import XGBClassifier


DATA_PATH = Path(
    "/Users/volodymyrnamiasenko/Machines_connectivity/training data/cab_ins02_dataset.json"
)
MODEL_PATH = Path(
    "/Users/volodymyrnamiasenko/Machines_connectivity/models/xgb_cab_ins02.json"
)

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

    # Ensure timestamp sorting for time-aware split
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Feature columns (drop label + leakage fields)
    drop_cols = {"maintenance_required", "brake_down", "timestamp", "machine_id"}
    feature_cols = FEATURE_COLUMNS

    X = df[feature_cols]
    y = df["maintenance_required"].astype(int)

    # Synthetic boundary cases: enforce "improving" signals -> normal behavior.
    sample = X.sample(n=min(2000, len(X)), random_state=7).copy()
    for col in [
        "pvc_screw_pressure_bar",
        "color_screw_pressure_bar",
        "nylon_screw_pressure_bar",
        "motor_load_amps",
        "motor_load_percent",
    ]:
        sample[col] = sample[col] * 0.98
    for col in [
        "pvc_screw_speed_rpm",
        "color_screw_speed_rpm",
        "nylon_screw_speed_rpm",
        "line_speed_m_min",
    ]:
        sample[col] = sample[col] * 1.02
    sample["post_extrusion_diameter_mm"] = sample["post_extrusion_diameter_mm"] * 0.99
    X = pd.concat([X, sample], ignore_index=True)
    y = pd.concat([y, pd.Series([0] * len(sample))], ignore_index=True)

    # Time-based split: last 20% for test
    split_idx = int(len(df) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    # Add Gaussian jitter to encourage robustness against tiny variations.
    std = X_train[feature_cols].std(ddof=0).replace(0, 1.0)
    jitter = np.random.normal(size=X_train.shape) * (std.values * 0.01)
    X_train_jitter = X_train + pd.DataFrame(jitter, columns=feature_cols)

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
        monotone_constraints=monotone_constraints,
    )
    model.fit(X_train_jitter, y_train)

    # Evaluation
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]
    report = classification_report(y_test, y_pred, digits=3)
    auc = roc_auc_score(y_test, y_prob)

    print("Features:", feature_cols)
    print("\nClassification Report:\n", report)
    print(f"AUC: {auc:.3f}")

    # Save model
    model.save_model(MODEL_PATH)
    print(f"\nSaved model to: {MODEL_PATH}")


if __name__ == "__main__":
    main()
