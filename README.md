# PdM Prediction Service

FastAPI prediction API + React/Vite operator dashboard for CAB-INS02.

## Repo Layout

- `app/` FastAPI backend (`app/main.py`)
- `models/` XGBoost model + feature column list
- `pipeline.py` Feature engineering pipeline (training/inference helpers)
- `pdm-dashboard/` React/Vite dashboard
- `docs/` Technical docs and PRD sections
- `ref_data_set/` Extracted pre-breakdown windows (reference dataset)

## Backend (FastAPI)

Run locally (example):

```bash
cd /Users/volodymyrnamiasenko/Machines_connectivity
uvicorn app.main:app --reload --port 8000
```

Endpoints:

- `POST /token` (dev token)
- `POST /api/v1/predict`
- `POST /api/v1/predict/batch` (supports `reset_history=true`)

## Frontend (Dashboard)

```bash
cd /Users/volodymyrnamiasenko/Machines_connectivity/pdm-dashboard
npm install
npm run dev
```
