#!/usr/bin/env python3
"""
Generate synthetic telemetry dataset for cable insulation machine CAB-INS02.

Period: 2026-02-01 to 2026-03-01 (28 days)
Hours: 06:00 - 22:00 daily (16h operating window)
Interval: 10 seconds
Breakdown: 1 per day with 30-min degradation before and 30-min offline after.
"""

import json
import random
import math
from datetime import datetime, timedelta

# ─── Configuration ───────────────────────────────────────────────────────────
MACHINE_ID = "CAB-INS02"
START_DATE = datetime(2026, 2, 1)
END_DATE = datetime(2026, 3, 1)  # exclusive
WORK_START_HOUR = 6
WORK_END_HOUR = 22
INTERVAL_SEC = 10
DEGRADATION_MINUTES = 30
RECOVERY_MINUTES = 30
OUTPUT_FILE = "/mnt/user-data/outputs/cab_ins02_dataset.json"

# ─── Normal operating ranges (center, jitter) ───────────────────────────────
NORMAL = {
    "pvc_screw_pressure_bar":    (145.0, 3.0),
    "color_screw_pressure_bar":  (133.0, 2.5),
    "nylon_screw_pressure_bar":  (128.0, 2.5),
    "pvc_screw_speed_rpm":       (310, 5),
    "color_screw_speed_rpm":     (295, 4),
    "nylon_screw_speed_rpm":     (280, 4),
    "motor_load_amps":           (12.4, 0.5),
    "motor_load_percent":        (68.5, 2.0),
    "line_speed_m_min":          (42.5, 1.0),
    "payoff_tension_n":          (220, 5),
    "takeup_tension_n":          (215, 5),
    "post_extrusion_diameter_mm":(8.2, 0.05),
}

# At breakdown moment: how far each parameter shifts from normal center
# positive = increase, negative = decrease
BREAKDOWN_DELTA = {
    "pvc_screw_pressure_bar":    +35.0,   # pressure spikes
    "color_screw_pressure_bar":  +30.0,
    "nylon_screw_pressure_bar":  +28.0,
    "pvc_screw_speed_rpm":       -60,     # speed drops
    "color_screw_speed_rpm":     -55,
    "nylon_screw_speed_rpm":     -50,
    "motor_load_amps":           +8.0,    # motor overloaded
    "motor_load_percent":        +28.0,
    "line_speed_m_min":          -15.0,   # line slows
    "payoff_tension_n":          +60,     # tension spikes
    "takeup_tension_n":          +55,
    "post_extrusion_diameter_mm":+0.8,    # diameter goes off spec
}

random.seed(42)


def normal_value(key: str) -> float:
    """Generate a normal operating value with small random jitter."""
    center, jitter = NORMAL[key]
    return center + random.uniform(-jitter, jitter)


def degraded_value(key: str, progress: float) -> float:
    """
    Generate a degrading value.
    progress: 0.0 = just started degrading, 1.0 = at breakdown.
    Uses an exponential curve so degradation accelerates toward the end.
    """
    center, jitter = NORMAL[key]
    delta = BREAKDOWN_DELTA[key]
    # Exponential ramp: slow start, fast finish
    factor = (math.exp(2.0 * progress) - 1.0) / (math.e ** 2 - 1.0)
    base = center + delta * factor
    # Jitter increases as we approach failure
    current_jitter = jitter * (1.0 + 1.5 * progress)
    return base + random.uniform(-current_jitter, current_jitter)


def offline_value(key: str) -> float:
    """Machine is off — values drop to idle / zero."""
    idle = {
        "pvc_screw_pressure_bar": 0.0,
        "color_screw_pressure_bar": 0.0,
        "nylon_screw_pressure_bar": 0.0,
        "pvc_screw_speed_rpm": 0,
        "color_screw_speed_rpm": 0,
        "nylon_screw_speed_rpm": 0,
        "motor_load_amps": 0.0,
        "motor_load_percent": 0.0,
        "line_speed_m_min": 0.0,
        "payoff_tension_n": 0,
        "takeup_tension_n": 0,
        "post_extrusion_diameter_mm": 0.0,
    }
    return idle[key]


def round_val(key: str, val: float) -> float:
    """Round values to appropriate precision."""
    int_keys = {
        "pvc_screw_speed_rpm", "color_screw_speed_rpm", "nylon_screw_speed_rpm",
        "payoff_tension_n", "takeup_tension_n",
    }
    if key in int_keys:
        return int(round(val))
    if "diameter" in key:
        return round(val, 2)
    return round(val, 1)


def generate_day(date: datetime, breakdown_time: datetime) -> list[dict]:
    """Generate all records for a single operating day."""
    day_start = date.replace(hour=WORK_START_HOUR, minute=0, second=0, microsecond=0)
    day_end = date.replace(hour=WORK_END_HOUR, minute=0, second=0, microsecond=0)

    degrade_start = breakdown_time - timedelta(minutes=DEGRADATION_MINUTES)
    recovery_end = breakdown_time + timedelta(minutes=RECOVERY_MINUTES)

    records = []
    current = day_start

    while current < day_end:
        ts = current.strftime("%Y-%m-%dT%H:%M:%SZ")

        if current == breakdown_time:
            # ── Breakdown record ──
            features = {}
            for key in NORMAL:
                features[key] = round_val(key, degraded_value(key, 1.0))
            features["machine_status"] = 1
            features["maintenance_required"] = 1
            features["brake_down"] = 1

        elif degrade_start <= current < breakdown_time:
            # ── Degradation window (30 min before) ──
            total_sec = DEGRADATION_MINUTES * 60
            elapsed = (current - degrade_start).total_seconds()
            progress = elapsed / total_sec
            features = {}
            for key in NORMAL:
                features[key] = round_val(key, degraded_value(key, progress))
            features["machine_status"] = 1
            features["maintenance_required"] = 1
            features["brake_down"] = 0

        elif breakdown_time < current <= recovery_end:
            # ── Recovery / offline window (30 min after) ──
            features = {}
            for key in NORMAL:
                features[key] = round_val(key, offline_value(key))
            features["machine_status"] = 0
            features["maintenance_required"] = 0
            features["brake_down"] = 0

        else:
            # ── Normal operation ──
            features = {}
            for key in NORMAL:
                features[key] = round_val(key, normal_value(key))
            features["machine_status"] = 1
            features["maintenance_required"] = 0
            features["brake_down"] = 0

        records.append({
            "machine_id": MACHINE_ID,
            "timestamp": ts,
            "features": features,
        })

        current += timedelta(seconds=INTERVAL_SEC)

    return records


def pick_breakdown_time(date: datetime) -> datetime:
    """
    Pick a random breakdown time within work hours, ensuring
    the 30-min degradation and 30-min recovery fit inside the window.
    """
    earliest = date.replace(hour=WORK_START_HOUR, minute=0, second=0) + timedelta(minutes=DEGRADATION_MINUTES)
    latest = date.replace(hour=WORK_END_HOUR, minute=0, second=0) - timedelta(minutes=RECOVERY_MINUTES)

    range_sec = int((latest - earliest).total_seconds())
    offset = random.randint(0, range_sec // INTERVAL_SEC) * INTERVAL_SEC
    bd_time = earliest + timedelta(seconds=offset)
    return bd_time


def main():
    all_records = []
    current_date = START_DATE
    day_count = 0

    while current_date < END_DATE:
        bd_time = pick_breakdown_time(current_date)
        day_records = generate_day(current_date, bd_time)
        all_records.extend(day_records)
        day_count += 1
        print(f"  Day {day_count:>2}: {current_date.strftime('%Y-%m-%d')} | "
              f"Breakdown at {bd_time.strftime('%H:%M:%S')} | "
              f"{len(day_records):,} records")
        current_date += timedelta(days=1)

    print(f"\nTotal records: {len(all_records):,}")
    print(f"Writing to {OUTPUT_FILE} ...")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(all_records, f, indent=2)

    # File size
    import os
    size_mb = os.path.getsize(OUTPUT_FILE) / (1024 * 1024)
    print(f"Done! File size: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
