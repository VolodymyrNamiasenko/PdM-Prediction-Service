# PdM Prediction Service

A predictive-maintenance prototype for CAB-INS02 sensor data. FastAPI serves an XGBoost model with temporal features, data-quality checks and a React dashboard.

## Capabilities

- Single-reading and batch inference with per-machine history.
- Rolling statistics, deltas and acceleration features.
- A 60-reading warmup, exponential smoothing and configurable temperature scaling.
- Missing/out-of-range sensor flags, chronological validation and rate-of-change alerts.
- Event-held-out evaluation in `pipeline.py`; a separate raw-feature baseline trainer.

The included model is an experimental artifact. Its output is a model score, not a validated probability of real equipment failure. Heuristic physics overrides and calibration must be validated with representative real data before operational use.

## Run locally

Requires Python 3.11+, Node.js 20.19+ and the included model/feature-list files.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
cd pdm-dashboard
npm ci
npm run dev
```

API docs: http://localhost:8000/docs. Dashboard: http://localhost:5173.
Set private `PDM_USERNAME`, `PDM_PASSWORD` and a strong random `PDM_TOKEN` in the backend environment. No default credentials are supplied; authentication returns 503 until all three are configured. Enter your configured username/password in the dashboard. Do not put credentials in frontend build variables, source code, Postman exports or Git. This single-user password/token mechanism is not production identity management.

## API contract

- `GET /health`: includes model readiness.
- `POST /token`: demo password flow.
- `POST /api/v1/predict`: bearer-token inference.
- `POST /api/v1/predict/batch?reset_history=true`: chronological replay.

Use timezone-aware timestamps and finite numeric sensor values. Future samples are not used to fill missing readings. Out-of-order readings are rejected through data-quality flags. Warmup and hard-failure results must not be interpreted as healthy machinery. `risk_score` is a smoothed **margin**, while `calibrated_risk_score` is the transformed score.

History is held in memory. Use one worker; restarting loses history. This service is not an automated machine-control or safety system.

## Training and checks

```bash
python -m unittest discover -s tests -v
python pipeline.py
# Optional raw-feature baseline; supply your private dataset:
DATASET_PATH=/path/to/data.json python train_xgb_cab_ins02.py
cd pdm-dashboard
npm run build
npm run lint
```

`pipeline.py` reads `ref_data_set/breakdown_*.json` and writes to `models/` (override `PDM_OUTPUT_DIR`). It fits a final model after event-held-out cross-validation; CV used for tuning is not a final independent test. The baseline reserves chronological train/dev/test splits before transformations. Neither script is run automatically by tests, and this polish does not retrain or replace the included model.

See [evaluation guidance](docs/EVALUATION.md).
