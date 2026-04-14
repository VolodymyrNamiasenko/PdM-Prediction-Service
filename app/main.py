from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from xgboost import XGBClassifier
import xgboost as xgb
import pandas as pd
from pathlib import Path
from math import exp
import os
from datetime import datetime
from pipeline import add_temporal_features, RAW_FEATURES

app = FastAPI(title="PdM Prediction Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Model loading (XGBoost) ----
MODEL_PATH = Path(
    "/Users/volodymyrnamiasenko/Machines_connectivity/models/xgb_cab_ins02_v2.json"
)
FEATURE_COLUMNS_PATH = Path(
    "/Users/volodymyrnamiasenko/Machines_connectivity/models/feature_columns_v2.json"
)

_model = XGBClassifier()
if MODEL_PATH.exists():
    _model.load_model(MODEL_PATH)
else:
    _model = None

if FEATURE_COLUMNS_PATH.exists():
    import json

    FEATURE_COLUMNS = json.loads(FEATURE_COLUMNS_PATH.read_text())
else:
    FEATURE_COLUMNS = []

# ---- Smoothing (EMA) ----
EMA_ALPHA = 0.35
EMA_WARMUP = 5
EMA_RESET_GAP_SEC = 300
_ema_state: dict[str, dict] = {}
_physics_state: dict[str, dict] = {}
_saturation_state: dict[str, dict] = {}
_history: dict[str, list[dict]] = {}
_dq_state: dict[str, dict] = {}
TEMP_SCALING = float(os.getenv("TEMP_SCALING", "2.0"))

RANGE_LIMITS = {
    "pvc_screw_pressure_bar": (0.0, 300.0),
    "color_screw_pressure_bar": (0.0, 300.0),
    "nylon_screw_pressure_bar": (0.0, 300.0),
    "pvc_screw_speed_rpm": (0.0, 600.0),
    "color_screw_speed_rpm": (0.0, 600.0),
    "nylon_screw_speed_rpm": (0.0, 600.0),
    "motor_load_amps": (0.0, 500.0),
    "motor_load_percent": (0.0, 100.0),
    "line_speed_m_min": (0.0, 120.0),
    "payoff_tension_n": (0.0, 2000.0),
    "takeup_tension_n": (0.0, 2000.0),
    "post_extrusion_diameter_mm": (0.0, 20.0),
}
CRITICAL_FIELDS = {
    "pvc_screw_pressure_bar",
    "color_screw_pressure_bar",
    "nylon_screw_pressure_bar",
}

# Minimal OAuth2 password flow (dev-only)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
DEV_USERNAME = "admin"
DEV_PASSWORD = "admin123"
DEV_TOKEN = "devtoken"


class PredictionRequest(BaseModel):
    machine_id: str = Field(..., examples=["CAB-INS02"])
    timestamp: str = Field(..., examples=["2026-03-20T10:00:00Z"])
    features: dict[str, float] = Field(default_factory=dict)


class PredictionResponse(BaseModel):
    machine_id: str
    timestamp: str
    risk_score: float
    raw_margin: float
    smoothed_margin: float
    calibrated_risk_score: float
    severity_index: float
    roc_alerts: list[dict]
    warmup: bool
    data_quality: str
    data_quality_flags: list[str]
    risk_level: str
    model_version: str
    model_type: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/token")
def token(form_data: OAuth2PasswordRequestForm = Depends()):
    if form_data.username != DEV_USERNAME or form_data.password != DEV_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"access_token": DEV_TOKEN, "token_type": "bearer"}


def require_token(token: str = Depends(oauth2_scheme)):
    if token != DEV_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def _reset_machine_state(machine_id: str) -> None:
    _history.pop(machine_id, None)
    _ema_state.pop(machine_id, None)
    _saturation_state.pop(machine_id, None)
    _physics_state.pop(machine_id, None)
    _dq_state.pop(machine_id, None)


def _sanitize_features(
    machine_id: str,
    timestamp: str,
    features: dict[str, float],
    lookahead: list[dict[str, float]] | None = None,
    lookahead_index: int | None = None,
) -> tuple[dict[str, float] | None, dict, bool]:
    state = _dq_state.get(
        machine_id,
        {"last_good": {}, "history": [], "last_ts": None, "stale_counts": {}},
    )
    flags: list[str] = []
    status = "OK"

    ts = _parse_ts(timestamp)
    if state["last_ts"] and ts and ts == state["last_ts"]:
        return None, {"status": "HardFail", "flags": ["duplicate_timestamp"]}, True

    if state["last_ts"] and ts:
        gap = (ts - state["last_ts"]).total_seconds()
        if abs(gap - 10) > 2:
            flags.append(f"timestamp_gap:{int(gap)}s")
        if gap > 60:
            flags.append("gap_over_60s")

    sanitized: dict[str, float] = {}
    invalid_fields: set[str] = set()

    def _backfill_from_history(key: str) -> float | None:
        for i in range(1, 4):
            if len(state["history"]) >= i:
                val = state["history"][-i].get(key)
                if val is not None:
                    return float(val)
        return None

    def _forward_fill_from_batch(key: str) -> float | None:
        if lookahead is None or lookahead_index is None:
            return None
        for i in range(1, 4):
            idx = lookahead_index + i
            if idx < len(lookahead):
                val = lookahead[idx].get(key)
                if val is not None:
                    return float(val)
        return None

    for key in RAW_FEATURES:
        val = features.get(key, None)
        if val is None:
            flags.append(f"missing:{key}")
            val = _backfill_from_history(key)
            if val is None and not state["history"]:
                val = _forward_fill_from_batch(key)
                if val is not None:
                    flags.append(f"forward_fill:{key}")
            if val is None:
                invalid_fields.add(key)
        try:
            val = float(val) if val is not None else None
        except Exception:
            flags.append(f"type_error:{key}")
            val = _backfill_from_history(key)
            if val is None and not state["history"]:
                val = _forward_fill_from_batch(key)
                if val is not None:
                    flags.append(f"forward_fill:{key}")
            if val is None:
                invalid_fields.add(key)

        if val is not None:
            min_v, max_v = RANGE_LIMITS.get(key, (None, None))
            if min_v is not None and (val < min_v or val > max_v):
                flags.append(f"out_of_range:{key}")
                val = _backfill_from_history(key)
                if val is None and not state["history"]:
                    val = _forward_fill_from_batch(key)
                    if val is not None:
                        flags.append(f"forward_fill:{key}")
                if val is None:
                    invalid_fields.add(key)

        sanitized[key] = val

    history = state["history"]
    if history:
        window = history[-30:]
        for key in RAW_FEATURES:
            curr = sanitized.get(key)
            if curr is None:
                continue
            vals = [float(r.get(key)) for r in window if r.get(key) is not None]
            if len(vals) < 5:
                continue
            mean = sum(vals) / len(vals)
            std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
            if std > 0 and abs(curr - mean) > 3 * std:
                flags.append(f"spike:{key}")
                recent = vals[-2:] + [curr]
                recent = [v for v in recent if v is not None]
                if recent:
                    recent_sorted = sorted(recent)
                    sanitized[key] = recent_sorted[len(recent_sorted) // 2]

    stale_counts = state.get("stale_counts", {})
    prev_good = state["last_good"]
    for key in RAW_FEATURES:
        curr = sanitized.get(key)
        prev_val = prev_good.get(key)
        if curr is not None and prev_val is not None and abs(curr - prev_val) < 1e-6:
            stale_counts[key] = stale_counts.get(key, 0) + 1
        else:
            stale_counts[key] = 0
        if stale_counts.get(key, 0) >= 10:
            flags.append(f"stale:{key}")

    invalid_ratio = len(invalid_fields) / max(len(RAW_FEATURES), 1)
    critical_missing = any(k in invalid_fields for k in CRITICAL_FIELDS)
    if invalid_ratio > 0.30 or critical_missing:
        return None, {"status": "HardFail", "flags": flags + ["hard_fail"]}, True

    if flags:
        status = "Degraded"

    for key, val in sanitized.items():
        if val is not None:
            state["last_good"][key] = val
    state["history"] = (state["history"] + [sanitized])[-120:]
    state["last_ts"] = ts
    state["stale_counts"] = stale_counts
    _dq_state[machine_id] = state

    return sanitized, {"status": status, "flags": flags}, False


def _build_feature_vector(machine_id: str, timestamp: str, features: dict[str, float]):
    history = _history.setdefault(machine_id, [])
    ts = _parse_ts(timestamp)
    if history and ts:
        last_ts = _parse_ts(history[-1]["timestamp"])
        if last_ts and ts < last_ts:
            _reset_machine_state(machine_id)
            history = _history.setdefault(machine_id, [])
    row = {"timestamp": timestamp, "machine_id": machine_id}
    row.update({k: float(features.get(k, 0.0)) for k in RAW_FEATURES})
    history.append(row)
    # keep only last 120 records (20 minutes) to control memory
    if len(history) > 120:
        history[:] = history[-120:]

    if len(history) < 60:
        return None

    df = pd.DataFrame(history)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.sort_values("timestamp").reset_index(drop=True)
    enriched = add_temporal_features(df)
    latest = enriched.iloc[-1]
    X = pd.DataFrame([latest[FEATURE_COLUMNS].values], columns=FEATURE_COLUMNS)
    return X


def _xgb_margin(machine_id: str, timestamp: str, features: dict[str, float]) -> float | None:
    if _model is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model not loaded",
        )
    if not FEATURE_COLUMNS:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Feature column list missing",
        )
    X = _build_feature_vector(machine_id, timestamp, features)
    if X is None:
        return None
    dmat = xgb.DMatrix(X, feature_names=FEATURE_COLUMNS)
    margin = float(_model.get_booster().predict(dmat, output_margin=True)[0])
    return margin


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _ema(machine_id: str, current: float, timestamp: str) -> float:
    state = _ema_state.get(machine_id)
    ts = _parse_ts(timestamp)
    if state and ts and state.get("last_ts"):
        if (ts - state["last_ts"]).total_seconds() > EMA_RESET_GAP_SEC:
            state = None

    if state is None:
        # Initialize with first actual reading
        _ema_state[machine_id] = {
            "ema": current,
            "count": 1,
            "sma_sum": current,
            "last_ts": ts,
        }
        return current

    state["count"] += 1
    state["sma_sum"] += current
    state["last_ts"] = ts

    # Burn-in: use simple moving average for the first N points
    if state["count"] <= EMA_WARMUP:
        state["ema"] = state["sma_sum"] / state["count"]
        return state["ema"]

    # Variable-span EMA: adapt faster on large gaps
    diff = abs(current - state["ema"])
    if diff > 6:
        alpha = 0.8
    elif diff > 3:
        alpha = 0.6
    else:
        alpha = EMA_ALPHA

    state["ema"] = alpha * current + (1 - alpha) * state["ema"]
    return state["ema"]


def _physics_sanity(
    machine_id: str,
    features: dict[str, float],
    calibrated: float,
) -> float:
    """
    Physics-based override:
    If core health indicators improve simultaneously, risk should not increase.
    """
    prev = _physics_state.get(machine_id)
    history = (prev or {}).get("history", [])
    history = (history + [features])[-120:]
    _physics_state[machine_id] = {
        "features": features,
        "calibrated": calibrated,
        "history": history,
    }
    if prev is None:
        return calibrated

    prev_f = prev["features"]
    prev_c = prev["calibrated"]

    def dec(key):
        return features.get(key, 0.0) < prev_f.get(key, 0.0)

    def inc(key):
        return features.get(key, 0.0) > prev_f.get(key, 0.0)

    pressures_improved = (
        dec("pvc_screw_pressure_bar")
        and dec("color_screw_pressure_bar")
        and dec("nylon_screw_pressure_bar")
    )
    load_improved = dec("motor_load_percent") or dec("motor_load_amps")
    speeds_improved = (
        inc("pvc_screw_speed_rpm")
        and inc("color_screw_speed_rpm")
        and inc("nylon_screw_speed_rpm")
        and inc("line_speed_m_min")
    )

    if pressures_improved and load_improved and speeds_improved:
        return min(calibrated, prev_c)

    return calibrated


def _severity_index(
    machine_id: str,
    features: dict[str, float],
    calibrated: float,
    raw_margin: float,
) -> float:
    """
    Secondary severity index for saturation zone.
    Tracks drift beyond the point where calibrated risk first hit the ceiling.
    Returns a non-negative value (higher = worse).
    """
    SAT_THRESHOLD = 0.97
    RAW_MARGIN_TRIGGER = 3.0
    state = _saturation_state.get(machine_id)

    if calibrated >= SAT_THRESHOLD or raw_margin >= RAW_MARGIN_TRIGGER:
        if state is None:
            _saturation_state[machine_id] = {
                "baseline": features,
                "active": True,
            }
            return 0.0

    if state is None or not state.get("active"):
        return 0.0

    baseline = state["baseline"]
    deltas = []
    for key in RAW_FEATURES:
        base = float(baseline.get(key, 0.0))
        curr = float(features.get(key, 0.0))
        denom = abs(base) if abs(base) > 1e-6 else 1.0
        deltas.append(abs(curr - base) / denom)
    return round(sum(deltas) / len(deltas), 4)


def _roc_alerts(machine_id: str, features: dict[str, float]) -> list[dict]:
    """
    Rate-of-change alerts on underlying parameters.
    """
    state = _physics_state.get(machine_id, {})
    prev = state.get("features")
    history = state.get("history", [])
    if prev is None:
        return []

    alerts = []
    thresholds_step = {
        "pvc_screw_pressure_bar": 0.03,
        "color_screw_pressure_bar": 0.03,
        "nylon_screw_pressure_bar": 0.03,
        "motor_load_percent": 0.03,
        "line_speed_m_min": 0.03,
    }
    thresholds_1m = {k: 0.015 for k in thresholds_step}
    thresholds_5m = {k: 0.01 for k in thresholds_step}

    def _rate(curr_v: float, base_v: float) -> float:
        denom = abs(base_v) if abs(base_v) > 1e-6 else 1.0
        return (curr_v - base_v) / denom

    for key, thresh in thresholds_step.items():
        prev_v = float(prev.get(key, 0.0))
        curr_v = float(features.get(key, 0.0))
        rate = _rate(curr_v, prev_v)
        if abs(rate) >= thresh:
            alerts.append(
                {
                    "parameter": key,
                    "rate_change": round(rate, 4),
                    "threshold": thresh,
                    "window": "10s",
                }
            )

    if len(history) >= 6:
        base_1m = history[-6]
        for key, thresh in thresholds_1m.items():
            base_v = float(base_1m.get(key, 0.0))
            curr_v = float(features.get(key, 0.0))
            rate = _rate(curr_v, base_v)
            if abs(rate) >= thresh:
                alerts.append(
                    {
                        "parameter": key,
                        "rate_change": round(rate, 4),
                        "threshold": thresh,
                        "window": "1m",
                    }
                )

    if len(history) >= 30:
        base_5m = history[-30]
        for key, thresh in thresholds_5m.items():
            base_v = float(base_5m.get(key, 0.0))
            curr_v = float(features.get(key, 0.0))
            rate = _rate(curr_v, base_v)
            if abs(rate) >= thresh:
                alerts.append(
                    {
                        "parameter": key,
                        "rate_change": round(rate, 4),
                        "threshold": thresh,
                        "window": "5m",
                    }
                )
    return alerts


@app.post("/api/v1/predict", response_model=PredictionResponse)
def predict(req: PredictionRequest, _token: str = Depends(require_token)):
    sanitized, dq_meta, hard_fail = _sanitize_features(
        req.machine_id, req.timestamp, req.features
    )
    if hard_fail or sanitized is None:
        return {
            "machine_id": req.machine_id,
            "timestamp": req.timestamp,
            "risk_score": 0.0,
            "raw_margin": 0.0,
            "smoothed_margin": 0.0,
            "calibrated_risk_score": 0.0,
            "severity_index": 0.0,
            "roc_alerts": [],
            "warmup": False,
            "data_quality": dq_meta["status"],
            "data_quality_flags": dq_meta["flags"],
            "risk_level": "Inconclusive — Sensor Data Error",
            "model_version": "xgb-cab-ins02-v2",
            "model_type": "xgboost",
        }
    raw_margin = _xgb_margin(req.machine_id, req.timestamp, sanitized)
    if raw_margin is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Warmup required: need at least 60 records (10 minutes) before inference.",
        )
    smoothed_margin = _ema(req.machine_id, raw_margin, req.timestamp)
    calibrated = 1 / (1 + exp(-smoothed_margin / TEMP_SCALING))

    calibrated = _physics_sanity(req.machine_id, sanitized, calibrated)

    severity_index = _severity_index(
        req.machine_id, sanitized, calibrated, raw_margin
    )
    roc_alerts = _roc_alerts(req.machine_id, sanitized)

    if calibrated <= 0.3:
        risk_level = "Healthy"
    elif calibrated <= 0.7:
        risk_level = "Warning"
    else:
        risk_level = "Critical"
    return {
        "machine_id": req.machine_id,
        "timestamp": req.timestamp,
        "risk_score": smoothed_margin,
        "raw_margin": raw_margin,
        "smoothed_margin": smoothed_margin,
        "calibrated_risk_score": calibrated,
        "severity_index": severity_index,
        "roc_alerts": roc_alerts,
        "warmup": False,
        "data_quality": dq_meta["status"],
        "data_quality_flags": dq_meta["flags"],
        "risk_level": risk_level,
        "model_version": "xgb-cab-ins02-v2",
        "model_type": "xgboost",
    }


def _stub_infer(features: dict[str, float]) -> tuple[float, str]:
    if features:
        avg_abs = sum(abs(v) for v in features.values()) / len(features)
        risk_score = max(0.0, min(1.0, avg_abs / 100.0))
    else:
        risk_score = 0.1

    if risk_score <= 0.3:
        risk_level = "Healthy"
    elif risk_score <= 0.7:
        risk_level = "Warning"
    else:
        risk_level = "Critical"

    return risk_score, risk_level


@app.post("/api/v1/predict/batch", response_model=list[PredictionResponse])
def predict_batch(
    items: list[PredictionRequest],
    reset_history: bool = Query(False, description="Reset per-machine state before processing"),
    _token: str = Depends(require_token),
):
    if reset_history:
        machine_ids = {req.machine_id for req in items}
        for mid in machine_ids:
            _reset_machine_state(mid)
    lookahead_by_machine: dict[str, list[dict[str, float]]] = {}
    index_by_machine: dict[str, int] = {}
    for req in items:
        lookahead_by_machine.setdefault(req.machine_id, []).append(req.features)
    results = []
    for req in items:
        idx = index_by_machine.get(req.machine_id, 0)
        sanitized, dq_meta, hard_fail = _sanitize_features(
            req.machine_id,
            req.timestamp,
            req.features,
            lookahead_by_machine.get(req.machine_id),
            idx,
        )
        index_by_machine[req.machine_id] = idx + 1
        if hard_fail or sanitized is None:
            results.append(
                {
                    "machine_id": req.machine_id,
                    "timestamp": req.timestamp,
                    "risk_score": 0.0,
                    "raw_margin": 0.0,
                    "smoothed_margin": 0.0,
                    "calibrated_risk_score": 0.0,
                    "severity_index": 0.0,
                    "roc_alerts": [],
                    "warmup": False,
                    "data_quality": dq_meta["status"],
                    "data_quality_flags": dq_meta["flags"],
                    "risk_level": "Inconclusive — Sensor Data Error",
                    "model_version": "xgb-cab-ins02-v2",
                    "model_type": "xgboost",
                }
            )
            continue
        raw_margin = _xgb_margin(req.machine_id, req.timestamp, sanitized)
        if raw_margin is None:
            results.append(
                {
                    "machine_id": req.machine_id,
                    "timestamp": req.timestamp,
                    "risk_score": 0.0,
                    "raw_margin": 0.0,
                    "smoothed_margin": 0.0,
                    "calibrated_risk_score": 0.0,
                    "severity_index": 0.0,
                    "roc_alerts": [],
                    "warmup": True,
                    "data_quality": dq_meta["status"],
                    "data_quality_flags": dq_meta["flags"],
                    "risk_level": "Warmup",
                    "model_version": "xgb-cab-ins02-v2",
                    "model_type": "xgboost",
                }
            )
            continue
        smoothed_margin = _ema(req.machine_id, raw_margin, req.timestamp)
        calibrated = 1 / (1 + exp(-smoothed_margin / TEMP_SCALING))

        calibrated = _physics_sanity(req.machine_id, sanitized, calibrated)

        severity_index = _severity_index(
            req.machine_id, sanitized, calibrated, raw_margin
        )
        roc_alerts = _roc_alerts(req.machine_id, sanitized)

        if calibrated <= 0.3:
            risk_level = "Healthy"
        elif calibrated <= 0.7:
            risk_level = "Warning"
        else:
            risk_level = "Critical"
        results.append(
            {
                "machine_id": req.machine_id,
                "timestamp": req.timestamp,
                "risk_score": smoothed_margin,
                "raw_margin": raw_margin,
                "smoothed_margin": smoothed_margin,
                "calibrated_risk_score": calibrated,
                "severity_index": severity_index,
                "roc_alerts": roc_alerts,
                "warmup": False,
                "data_quality": dq_meta["status"],
                "data_quality_flags": dq_meta["flags"],
                "risk_level": risk_level,
                "model_version": "xgb-cab-ins02-v2",
                "model_type": "xgboost",
            }
        )
    return results
