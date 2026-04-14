# PdM Prediction Service — Technical Specification

**Technical Specification aligned to PRD v2.0 (MES‑Integrated PdM Prediction Service)**

This document describes the current technical scope of the PdM Prediction Service implementation, aligned with PRD v2.0. It covers architecture, interfaces, data flow, model behavior layers, and the operational safeguards added so far. Sensitive data such as credentials, file system secrets, and environment‑specific paths are intentionally excluded.

---

## 1. Purpose and Scope

The PdM Prediction Service provides a lightweight, MES‑integrated prediction microservice that:

- Ingests sensor data via API (JSON payloads representing MES sensor data).
- Runs XGBoost inference with stability layers (monotonicity, regularization, jitter training).
- Applies post‑prediction smoothing and physics sanity checks.
- Returns risk scores and auxiliary diagnostics via REST API.
- Exposes a web dashboard for operators and engineers.

Current implementation focuses on the **prediction layer** and **operator‑facing visibility**, matching PRD v2.0 scope for the pilot phase.

---

## 2. Alignment with PRD v2.0

**PRD Areas Covered**

- **Data Input**: API‑based ingestion (JSON payloads represent MES sensor data).
- **Model Inference**: XGBoost model integrated.
- **Output Channels**: REST API responses + Web dashboard.
- **Early‑warning behavior**: Implemented via risk scoring and smoothing layers.

**PRD Areas Not Yet Implemented**

- Full MES polling integration (live REST polling).
- LSTM/GRU comparison track.
- WhatsApp notification channel.
- Monitoring/observability stack (Prometheus + Grafana).
- Persistent storage for features/predictions.

---

## 3. System Architecture (Current)

**Components**

1. **Prediction API (FastAPI)**
   - Provides `/predict` and `/predict/batch`.
   - OAuth2 token flow (dev‑only).
   - Returns raw margin, calibrated risk, smoothed values, and operational diagnostics.

2. **Web Dashboard (React + Vite + ECharts)**
   - Token retrieval and batch submission.
   - Risk trend chart (calibrated vs raw margin).
   - Correlation view with multi‑series chart + correlation matrix.
   - Click‑through from chart to the exact input/response pair.

3. **API Test Collection (Postman)**
   - Token, single prediction, and batch prediction requests.

---

## 4. API Specification (Current)

### 4.1 Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/token` | POST | OAuth2 token (dev stub) |
| `/api/v1/predict` | POST | Single prediction |
| `/api/v1/predict/batch` | POST | Batch prediction (supports `reset_history=true`) |

### 4.2 Request Schema (Single)

```json
{
  "machine_id": "CAB-INS02",
  "timestamp": "2026-03-20T10:00:00Z",
  "features": {
    "pvc_screw_pressure_bar": 145.2,
    "color_screw_pressure_bar": 132.8,
    "nylon_screw_pressure_bar": 128.4,
    "pvc_screw_speed_rpm": 310,
    "color_screw_speed_rpm": 295,
    "nylon_screw_speed_rpm": 280,
    "motor_load_amps": 12.4,
    "motor_load_percent": 68.5,
    "line_speed_m_min": 42.7,
    "payoff_tension_n": 220,
    "takeup_tension_n": 215,
    "post_extrusion_diameter_mm": 8.2,
    "machine_status": 1,
    "maintenance_required": 0,
    "brake_down": 0
  }
}
```

### 4.3 Request Schema (Batch)

```json
[
  { "machine_id": "...", "timestamp": "...", "features": { ... } },
  { "machine_id": "...", "timestamp": "...", "features": { ... } }
]
```

### 4.4 Response Schema (Current)

```json
{
  "machine_id": "CAB-INS02",
  "timestamp": "2026-03-20T10:00:00Z",
  "risk_score": 1.234,
  "raw_margin": 1.567,
  "smoothed_margin": 1.234,
  "calibrated_risk_score": 0.73,
  "severity_index": 0.08,
  "roc_alerts": [
    { "parameter": "line_speed_m_min", "rate_change": -0.0412, "threshold": 0.03, "window": "10s" }
  ],
  "warmup": false,
  "risk_level": "Warning",
  "model_version": "xgb-cab-ins02-v2",
  "model_type": "xgboost"
}
```

**Notes**
- `risk_score` now represents the **smoothed margin** (log‑odds). It is not bounded to 0–1.
- `calibrated_risk_score` is the operator‑friendly 0–1 score (temperature‑scaled sigmoid).
- `severity_index` increases when the model saturates (calibrated ≥ 0.97 **or** raw_margin ≥ 3.0) and parameters keep drifting.
- `roc_alerts` flag rapid parameter changes even if risk is flat, across 10s / 1m / 5m windows.
- `warmup` indicates that temporal features are not yet valid (first 60 records / 10 minutes).
- `data_quality` and `data_quality_flags` describe Data Guard Stage B outcomes.

---

## 5. Feature Keys (Aligned to PRD — CAB‑INS02)

- `pvc_screw_pressure_bar`
- `color_screw_pressure_bar`
- `nylon_screw_pressure_bar`
- `pvc_screw_speed_rpm`
- `color_screw_speed_rpm`
- `nylon_screw_speed_rpm`
- `motor_load_amps`
- `motor_load_percent`
- `line_speed_m_min`
- `payoff_tension_n`
- `takeup_tension_n`
- `post_extrusion_diameter_mm`
- `machine_status`
- `maintenance_required` (label in training data)
- `brake_down` (event marker in training data)

---

## 6. Model & Stability Layers

### 6.1 XGBoost Inference
- Primary model: XGBoost classifier.
- Outputs raw margin (log‑odds) using `output_margin=True`.
- Calibrated to 0–1 using temperature‑scaled sigmoid.
  - Temperature can be configured via `TEMP_SCALING` env var.

### 6.2 Monotonic Constraints
To enforce physical consistency:
- Pressures: monotone **+1**
- Motor loads: monotone **+1**
- Screw speeds + line speed: monotone **−1**
- Diameter: monotone **+1**

### 6.3 Regularization + Jitter
- Higher `min_child_weight`, non‑zero `gamma`, reduced `max_depth`.
- Gaussian jitter (1% of feature std) added during training for robustness.

### 6.4 EMA Smoothing
- EMA initialized with first real reading.
- Short SMA burn‑in (first 5 samples).
- Variable‑span EMA adapts faster when raw/smoothed gap is large.
- Resets if time gap exceeds a configurable threshold.
- Per‑machine history resets automatically if timestamps move backwards.

### 6.5 Physics Sanity Check
If core health indicators improve simultaneously (pressures drop, loads drop, speeds rise), risk is **not allowed to increase**.

### 6.6 Saturation Visibility
- **Severity Index** tracks drift once calibrated risk is high or raw margin is extreme.
- **Rate‑of‑Change Alerts** trigger on 10s, 1m, and 5m parameter shifts even if risk is flat.
  - Thresholds: 3% (10s), 1.5% (1m), 1% (5m).

### 6.7 Data Guard Stage B (Integrity Sanitizer)

Implemented in the online inference path (`main.py`) and applied to both `/predict` and `/predict/batch`.

- **Range validation:** Sensor values must be within configured physical bounds; out‑of‑range values are replaced via imputation or trigger hard fail.
- **Missing values:** Uses short‑window imputation.
  - If the first record in a batch is missing a field, it looks ahead up to **3 future records** (T+10s/T+20s/T+30s). If still missing → hard fail.
  - Otherwise it backfills from the last **3 records** (T‑10s/T‑20s/T‑30s). If still missing → hard fail.
- **Spike detection:** If a value deviates by >3σ from the rolling 5‑minute mean (30 samples), it is flagged and smoothed via a 3‑sample median filter.
- **Timestamp continuity:** Flags gaps outside 10s ±2s; gaps >60s are flagged as `gap_over_60s`.
- **Duplicate detection:** Identical timestamps are rejected (hard fail).
- **Stale detection:** Identical values across 10+ consecutive readings are flagged as `stale:<field>`.
- **Hard fail conditions:** >30% invalid fields or missing critical pressure sensors → `risk_level: "Inconclusive — Sensor Data Error"`.

---

## 7. Dashboard UI (Current)

The dashboard provides:

- Token retrieval (OAuth2 dev flow).
- Batch submission to `/predict/batch`.
- Risk trend chart showing **Calibrated Risk (0–1)** and **Raw Margin (log‑odds)** on separate axes.
- Correlation View tab:
  - Multi‑series chart with all parameters + calibrated risk + raw margin.
  - Correlation matrix (heatmap) for selected parameters.
  - Toggle controls to show/hide parameters.
- Click‑through from chart points to exact input/response pair.
- Warmup banner when any response item has `warmup: true`.

---

## 8. Warmup & State Management

- Temporal features require **60 records (10 minutes)** of history per machine.
- First 60 records return `warmup: true` and zeroed scores.
- `/api/v1/predict/batch?reset_history=true` forces a clean per‑machine state before processing.

---

## 8. Non‑Functional Considerations (Current)

| Area | Current State | PRD Target |
|---|---|---|
| Auth | OAuth2 dev flow | OAuth2 / API key |
| Persistence | None | Feature & prediction storage |
| Monitoring | None | Prometheus + Grafana |
| Latency | Local dev | < 10 ms inference |
| Availability | Local dev | 99.5% |

---

## 9. Known Gaps vs PRD

- No MES API polling integration.
- No LSTM/GRU comparison track.
- No WhatsApp notifications.
- No model monitoring/retraining pipeline.
- No database persistence.

---

## 10. Next Technical Milestones (Aligned to PRD)

1. Integrate MES API polling layer (PRD Section 7.3).
2. Implement rolling feature engineering (60‑minute window).
3. Add persistence for predictions + feature vectors.
4. Add monitoring endpoints and dashboards.
5. Expand to multi‑machine model registry.

---

## 11. Artifacts

- Backend API: `app/main.py`
- Training script: `train_xgb_cab_ins02.py`
- Dashboard UI: `pdm-dashboard/src/App.jsx`
- Postman collection: `PdM_postman_collection.json`

---

**End of Specification**
