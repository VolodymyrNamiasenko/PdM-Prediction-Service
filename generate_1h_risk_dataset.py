#!/usr/bin/env python3
"""
Generate a 1-hour synthetic dataset for CAB-INS02 that matches the
existing dataset structure (no top-level risk_score).
"""

import json
import random
from datetime import datetime, timedelta


MACHINE_ID = "CAB-INS02"
START_TIME = datetime(2026, 3, 20, 10, 0, 0)
DURATION_MIN = 60
INTERVAL_SEC = 10
OUTPUT_FILE = "/Users/volodymyrnamiasenko/Machines_connectivity/training data/cab_ins02_1h_risk.json"

# Normal operating ranges (center, jitter)
NORMAL = {
    "pvc_screw_pressure_bar": (145.0, 1.5),
    "color_screw_pressure_bar": (133.0, 1.2),
    "nylon_screw_pressure_bar": (128.0, 1.2),
    "pvc_screw_speed_rpm": (310, 3),
    "color_screw_speed_rpm": (295, 3),
    "nylon_screw_speed_rpm": (280, 3),
    "motor_load_amps": (12.4, 0.2),
    "motor_load_percent": (68.5, 0.8),
    "line_speed_m_min": (42.5, 0.4),
    "payoff_tension_n": (220, 2),
    "takeup_tension_n": (215, 2),
    "post_extrusion_diameter_mm": (8.2, 0.02),
}

# Drift deltas over the hour (soft trend toward risk)
DRIFT = {
    "pvc_screw_pressure_bar": +12.0,
    "color_screw_pressure_bar": +10.0,
    "nylon_screw_pressure_bar": +9.0,
    "pvc_screw_speed_rpm": -20,
    "color_screw_speed_rpm": -18,
    "nylon_screw_speed_rpm": -16,
    "motor_load_amps": +2.0,
    "motor_load_percent": +8.0,
    "line_speed_m_min": -4.0,
    "payoff_tension_n": +15,
    "takeup_tension_n": +14,
    "post_extrusion_diameter_mm": +0.12,
}

random.seed(7)


def smoothstep(x: float) -> float:
    """Smooth 0..1 curve with gentle start and end."""
    return x * x * (3 - 2 * x)


def round_val(key: str, val: float) -> float:
    int_keys = {
        "pvc_screw_speed_rpm",
        "color_screw_speed_rpm",
        "nylon_screw_speed_rpm",
        "payoff_tension_n",
        "takeup_tension_n",
    }
    if key in int_keys:
        return int(round(val))
    if "diameter" in key:
        return round(val, 2)
    return round(val, 1)


def generate() -> list[dict]:
    records = []
    total_steps = int((DURATION_MIN * 60) / INTERVAL_SEC)
    for step in range(total_steps):
        progress = step / (total_steps - 1)
        curve = smoothstep(progress)

        features = {}
        for key, (center, jitter) in NORMAL.items():
            drift = DRIFT[key] * curve
            val = center + drift + random.uniform(-jitter, jitter)
            features[key] = round_val(key, val)

        # Machine is running
        features["machine_status"] = 1
        # Match original structure
        features["maintenance_required"] = 0
        features["brake_down"] = 0

        ts = (START_TIME + timedelta(seconds=step * INTERVAL_SEC)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        records.append(
            {
                "machine_id": MACHINE_ID,
                "timestamp": ts,
                "features": features,
            }
        )
    return records


def main() -> None:
    records = generate()
    with open(OUTPUT_FILE, "w") as f:
        json.dump(records, f, indent=2)
    print(f"Wrote {len(records)} records to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
