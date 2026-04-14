# Product Requirements Document

## Predictive Maintenance (PdM) Prediction Service

### MES-Integrated Machine Breakdown Prediction — Cable Manufacturing Plant

| Field | Detail |
|---|---|
| **Version:** | 2.0 |
| **Date:** | March 20, 2026 |
| **Status:** | Draft |
| **Supersedes:** | v1.0 (IIoT-Based PdM PRD) |
| **Confidentiality:** | Internal Use Only |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Change Log from v1.0](#2-change-log-from-v10)
3. [Problem Statement](#3-problem-statement)
4. [Product Vision and Objectives](#4-product-vision-and-objectives)
5. [Scope](#5-scope)
6. [Target Machines and Sensor Inventory](#6-target-machines-and-sensor-inventory)
7. [Technical Architecture](#7-technical-architecture)
8. [User Stories](#8-user-stories)
9. [Non-Functional Requirements](#9-non-functional-requirements)
10. [Implementation Timeline](#10-implementation-timeline)
11. [Success Metrics and KPIs](#11-success-metrics-and-kpis)
12. [Risks and Mitigations](#12-risks-and-mitigations)
13. [MES Integration Responsibilities](#13-mes-integration-responsibilities)
14. [Approvals](#14-approvals)

---

## 1. Executive Summary

This Product Requirements Document (v2.0) defines the scope, objectives, and technical design for the Predictive Maintenance (PdM) Prediction Service at the Cable Manufacturing Plant. This version supersedes PRD v1.0 and reflects a fundamental architectural change: the MES (Manufacturing Execution System) is now recognized as the authoritative source and owner of all machine sensor data.

Rather than building a standalone data ingestion pipeline, this product operates as a prediction microservice that consumes sensor data from the MES via REST API, runs ML-based failure predictions, and delivers results through three output channels: API response back to MES, a standalone web dashboard, and WhatsApp push notifications.

The initial deployment targets three critical work centers: Extrusion Lines (CAB-INS02), HV CV Line (CAB-CVL-HV), and Drum Twister Assembly (CAB-ASM4000). The system is expected to reduce unplanned downtime by 30–40% and improve Overall Equipment Effectiveness (OEE) by 25–35%.

---

## 2. Change Log from v1.0

The following table summarizes the key changes between PRD v1.0 and v2.0.

| Area | v1.0 (Previous) | v2.0 (Current) |
|---|---|---|
| Data Source | Self-managed IIoT ingestion pipeline (Kafka/MQTT) | MES provides data via REST API |
| Data Storage | Own TimescaleDB/InfluxDB time-series database | MES owns raw data storage; PdM stores only feature vectors and predictions |
| Data Pipeline | Full pipeline: ingestion, storage, feature engineering | Simplified: API read, feature engineering, prediction |
| Output Channels | Grafana dashboard + SMS/Email + CMMS work orders | MES API response + Web dashboard + WhatsApp notifications |
| Infrastructure | Kafka, TimescaleDB, Grafana, Airflow stack | Lightweight FastAPI service + React dashboard |
| CMMS Integration | Direct REST API integration for work orders | Delegated to MES (MES handles downstream CMMS actions) |
| Scope of Ownership | End-to-end from sensors to alerts | Prediction layer only: data in, predictions out |

---

## 3. Problem Statement

The cable manufacturing plant currently operates under a reactive and time-based maintenance regime. Machines are either repaired after failure or serviced on fixed schedules regardless of actual condition. This leads to unplanned breakdowns that halt production lines, costly emergency repairs, unnecessary preventive maintenance on healthy equipment, and an inability to plan production schedules around maintenance windows.

The plant's MES system already captures and stores real-time sensor data from all machines with IIoT connectivity. The raw data exists, but the plant lacks the analytical intelligence layer to convert sensor readings into actionable breakdown predictions. This product fills that gap as a dedicated prediction service that reads from the MES and returns machine health insights.

---

## 4. Product Vision and Objectives

### 4.1 Vision

Deliver a lightweight, MES-integrated prediction service that continuously analyzes machine sensor data, detects degradation patterns before they cause failure, and delivers timely predictions to the MES, plant operators, and maintenance teams through multiple channels.

### 4.2 Objectives

1. Predict machine breakdowns 4–24 hours in advance with at least 85% accuracy.
2. Reduce unplanned downtime by 30–40% within six months of deployment.
3. Improve OEE by 25–35% through optimized maintenance scheduling.
4. Return prediction results to the MES via API for downstream workflow automation.
5. Provide a standalone web dashboard with machine risk scores and actionable insights.
6. Push critical alerts to maintenance teams via WhatsApp notifications.

---

## 5. Scope

### 5.1 In Scope

- Three pilot machines: CAB-INS02 (BW/LV Extrusion), CAB-CVL-HV (HV CV Line), CAB-ASM4000 (Drum Twister Assembly).
- MES API integration for reading sensor data at configured frequencies.
- Feature engineering engine to transform raw sensor data into ML-ready feature vectors.
- ML model training, validation, and deployment (XGBoost primary, LSTM secondary).
- Three output channels: (1) Prediction API back to MES, (2) Web dashboard, (3) WhatsApp notifications.
- Model monitoring, retraining pipeline, and accuracy tracking.

### 5.2 Out of Scope

- Raw sensor data collection, storage, or management (owned by MES).
- Plant-wide rollout beyond the initial three machines (Phase 2).
- Remaining Useful Life (RUL) regression modeling (future enhancement).
- Automated machine shutdown or control actions (human-in-the-loop only).
- CMMS work order creation (delegated to MES based on predictions returned via API).
- ERP/MRP integration for production scheduling.

---

## 6. Target Machines and Sensor Inventory

The following sections describe the three pilot machines and the sensor parameters that the MES will provide via API for each. All data is sourced from the MES; this product does not connect directly to sensors or the IIoT gateway.

### 6.1 CAB-INS02 — BW/LV Extrusion Line

This is the core production bottleneck. Screw and heater failures cost $15K–$50K+ per incident. Over 20 sensors per line provide rich multivariate data for model training.

| Sensor Parameter | Unit | PdM Relevance |
|---|---|---|
| PVC / Color / Nylon Screw Pressure | bar | Pressure spikes predict screw blockage |
| Screw Speeds (PVC, Color, Nylon) | RPM | Speed drops indicate jams or wear |
| Motor Loads | amps / % load | Load spikes signal bearing/seizure risk |
| Line Speed | m/min | Deviations indicate process instability |
| Tensions (Payoff, Take-up) | N | Tension anomalies predict cable defects |
| Diameters (Post-extrusion) | mm | Diameter drift signals die or tooling wear |
| Machine Status | enum | Event labels for training data |

### 6.2 CAB-CVL-HV — HV CV Line

Multi-extruder high-voltage line. Overloads predict crosslink failures; temperature and pressure drifts indicate insulation defects leading to downtime.

| Sensor Parameter | Unit | PdM Relevance |
|---|---|---|
| Extruder Pressures (3 units) | bar | Multi-unit pressure divergence flags faults |
| RPMs (3 extruders) | RPM | Speed imbalance across extruders |
| Current Loads (3 extruders) | amps | Overload detection per extruder |
| Cooling Temperature | °C | Temperature drift indicates cooling failure |
| Preheater Power | kW | Power anomalies signal element degradation |
| Accumulator Tension | N | Tension loss predicts cable misalignment |
| Line Speed | m/s | Speed deviations correlate with faults |

### 6.3 CAB-ASM4000 — Drum Twister Assembly

Complex rotating mechanics prone to imbalance and tension faults. Critical for multi-core cable production. Sensor coverage is lighter, so augmentation with vibration/motor data from MES is recommended.

| Sensor Parameter | Unit | PdM Relevance |
|---|---|---|
| Actual / Set Line Speed | m/min | Speed deviations signal drive faults |
| Actual Total Length | m | Length anomalies indicate bobbin jams |
| Machine Status | enum | Event labels for training data |

---

## 7. Technical Architecture

This section defines the end-to-end architecture for the PdM Prediction Service, reflecting the MES-integrated design where this product is a consumer of MES data and a provider of predictions.

### 7.1 Solution Architecture Overview

The solution follows a three-layer architecture, simplified from v1.0 by removing the data ingestion and storage layers (now owned by MES).

| Layer | Component | Technology | Update Cycle |
|---|---|---|---|
| 1. Data Read | MES API consumer | Python + Requests / httpx | Configurable (e.g., every 5 min) |
| 2. Processing + Inference | Feature engineering + ML prediction | Python + Pandas + XGBoost + FastAPI | Every 5 minutes |
| 3. Output | MES API return + Dashboard + WhatsApp | FastAPI + React + WhatsApp Business API | Real-time on prediction |

### 7.2 Data Flow

The data flow is as follows: The PdM service calls the MES REST API at a configured frequency (default: every 5 minutes) to retrieve the latest sensor readings for each pilot machine. The MES API returns a JSON payload containing timestamped sensor values for the requested machine and time window. The Feature Engine computes statistical features (rolling mean, standard deviation, min, max, trend slope) over a 60-minute sliding window from the retrieved data, producing a feature vector of approximately 50 dimensions per machine. The feature vector is passed to the ML inference engine, which returns a risk probability score (0.0 to 1.0). The prediction result is then dispatched to the three output channels simultaneously.

### 7.3 MES API Integration (Data Input)

This is the primary data interface. The MES system exposes REST API endpoints that this product consumes.

#### 7.3.1 API Contract (Expected from MES)

| Endpoint | Method | Description | Frequency |
|---|---|---|---|
| `/api/v1/machines/{id}/sensors` | GET | Returns latest sensor readings for a machine within a specified time window | Every 5 min |
| `/api/v1/machines/{id}/history` | GET | Returns historical sensor data for training (bulk export) | On demand |
| `/api/v1/machines/{id}/status` | GET | Returns current machine status (running, idle, fault) | Every 5 min |
| `/api/v1/machines/{id}/maintenance-logs` | GET | Returns maintenance/breakdown records for labeling | On demand |

#### 7.3.2 Data Format

The MES API is expected to return JSON payloads with the following structure: `machine_id` (string), `timestamp` (ISO 8601 UTC), `sensor_tag` (string identifier), `value` (float), `unit` (string), and `machine_status` (enum). The PdM service will validate incoming data for completeness and flag missing or malformed sensor readings.

#### 7.3.3 Polling Configuration

The service polls the MES API at a configurable frequency, defaulting to every 5 minutes. The polling interval is adjustable per machine if the MES can support higher or lower frequencies for specific work centers. A circuit breaker pattern will be implemented to handle MES API downtime gracefully, with exponential backoff and a fallback to the last known feature vector if the API is temporarily unavailable.

### 7.4 Feature Engineering

The feature engine processes the raw sensor data received from the MES API. It computes statistical aggregations over a 60-minute sliding window for each machine. Features include rolling mean, standard deviation, minimum, maximum, and trend (slope of linear regression) for each sensor. Additionally, cross-sensor ratios (e.g., pressure-to-speed ratio), delta features (rate of change per hour), and categorical encodings of machine status transitions are computed. The resulting feature vector of approximately 50 dimensions per machine is passed directly to the inference engine. Feature vectors and prediction results are stored locally for model monitoring and retraining purposes.

### 7.5 Machine Learning Model Design

This section defines a multi-algorithm comparison framework for the PdM Prediction Service. Rather than pre-selecting a single model, the system trains and evaluates multiple algorithms in parallel across two processing tracks: a Feature-Based Track that consumes engineered feature vectors, and a Sequence-Based Track that consumes raw time-series windows. All candidate models are benchmarked against a unified evaluation protocol, and the best-performing model per machine is promoted to production. An unsupervised anomaly detection layer runs independently alongside both tracks.

#### 7.5.1 Comparison Framework Overview

The framework operates on the principle that different machines may exhibit different failure signatures, and no single algorithm is guaranteed to be optimal across all work centers. All candidate models receive the same labeled data, are evaluated under the same time-series aware cross-validation protocol, and are scored against the same metrics. The framework outputs a per-machine model ranking and a recommended production model for each work center.

| Component | Detail |
|---|---|
| Processing Tracks | Track A: Feature-Based (engineered vectors); Track B: Sequence-Based (raw time-series windows) |
| Candidate Models | XGBoost, LightGBM, Random Forest (Track A); LSTM, GRU (Track B) |
| Evaluation Protocol | Unified time-series aware 5-fold cross-validation with identical train/test splits across all models |
| Scoring Metrics | F1-score (primary), Precision, Recall, AUC-ROC, inference latency |
| Selection Criteria | Highest F1-score on held-out test set per machine; ties broken by inference latency |
| Comparison Cadence | Full comparison at initial training; re-comparison at each monthly retraining cycle |

#### 7.5.2 Track A: Feature-Based Models

Track A models consume the 50-dimension engineered feature vectors produced by the Feature Engine (Section 7.4). These models are well-suited for tabular sensor data and benefit from the statistical aggregations, cross-sensor ratios, and trend features already computed. Three gradient-boosted and ensemble algorithms are trained in parallel.

**XGBoost Classifier.** XGBoost is a gradient-boosted decision tree algorithm with proven performance on tabular sensor data. It natively handles class imbalance via `scale_pos_weight`, provides built-in feature importance for model interpretability, and has extensive industry adoption in predictive maintenance applications.

| Parameter | Configuration |
|---|---|
| Objective | binary:logistic (probability of failure) |
| Class Imbalance Handling | scale_pos_weight = 6 (inverse of positive class ratio) |
| Cross-Validation | Time-series aware 5-fold (no future data leakage) |
| Expected F1-Score | 85–92% on held-out test set |

**LightGBM Classifier.** LightGBM is a gradient-boosted framework that uses histogram-based splitting and leaf-wise tree growth, resulting in significantly faster training times on large datasets compared to XGBoost. Given the estimated training volume of ~78M rows for the 6-month historical dataset, LightGBM's speed advantage is operationally significant. It supports native categorical feature handling and offers comparable or superior accuracy to XGBoost on structured data.

| Parameter | Configuration |
|---|---|
| Objective | binary (probability of failure) |
| Class Imbalance Handling | is_unbalance = true; alternatively, scale_pos_weight = 6 |
| Boosting Type | GBDT (Gradient Boosted Decision Trees) |
| Expected F1-Score | 85–93% on held-out test set |

**Random Forest Classifier.** Random Forest serves as a robust ensemble baseline. It is less prone to overfitting than boosted methods due to bagging and feature subsampling, and requires less hyperparameter tuning. While it typically underperforms gradient-boosted models on structured sensor data, it provides a valuable performance floor: if XGBoost or LightGBM only marginally outperform Random Forest, the simpler model may be preferred for production stability.

| Parameter | Configuration |
|---|---|
| Estimators | 500 trees (configurable) |
| Class Imbalance Handling | class_weight = "balanced" |
| Max Features | sqrt (default for classification) |
| Expected F1-Score | 80–88% on held-out test set |

#### 7.5.3 Track B: Sequence-Based Models

Track B models consume raw 60-minute multivariate sensor sequences directly, bypassing the Feature Engine. These models are designed to capture temporal dependencies, sequential degradation patterns, and transient anomalies that may be lost in statistical aggregation. Two recurrent neural network architectures are trained in parallel.

**LSTM Network (Long Short-Term Memory).** The LSTM accepts 60-minute sequences of multivariate sensor readings and outputs a failure probability. Its gated architecture is designed to learn long-range temporal dependencies in sensor streams, making it effective for detecting gradual degradation patterns that unfold over minutes to hours.

| Parameter | Configuration |
|---|---|
| Input Shape | 60-minute window × N sensor channels per machine |
| Architecture | 2-layer stacked LSTM with dropout (0.2–0.3) |
| Output | Sigmoid activation (failure probability 0.0–1.0) |
| Expected F1-Score | 88–94% on held-out test set |

**GRU Network (Gated Recurrent Unit).** The GRU is a streamlined variant of LSTM with fewer parameters (two gates instead of three), resulting in faster training and lower inference latency. It is included as a direct comparison to LSTM: if GRU achieves comparable accuracy with lower computational cost, it is preferred for production deployment, particularly in edge inference scenarios where latency matters.

| Parameter | Configuration |
|---|---|
| Input Shape | 60-minute window × N sensor channels per machine |
| Architecture | 2-layer stacked GRU with dropout (0.2–0.3) |
| Output | Sigmoid activation (failure probability 0.0–1.0) |
| Expected F1-Score | 86–93% on held-out test set |

#### 7.5.4 Anomaly Detection Layer (Unsupervised)

An Isolation Forest model runs in parallel as an unsupervised anomaly detector, independent of both Track A and Track B. This layer serves three purposes: (1) safety net for novel failure modes not represented in historical training data; (2) early warning capability during the cold-start period before sufficient labeled failures accumulate for supervised training; (3) supplementary anomaly signal that can be incorporated as an additional feature for supervised models. The Isolation Forest does not participate in the model comparison rankings, as it addresses a fundamentally different objective (unsupervised anomaly detection vs. supervised failure prediction).

#### 7.5.5 Model Evaluation Protocol

All candidate models (Track A and Track B) are evaluated under a unified protocol to ensure fair and reproducible comparison. The evaluation is performed per machine, recognizing that different work centers may favor different algorithms based on their sensor profiles and failure characteristics.

| Evaluation Component | Specification |
|---|---|
| Cross-Validation | Time-series aware 5-fold; temporal ordering preserved; no future data leakage; identical folds used across all models |
| Primary Metric | F1-score on held-out test set (minimum threshold: 85%) |
| Secondary Metrics | Precision, Recall, AUC-ROC, inference latency (ms per prediction) |
| Statistical Significance | Paired t-test or Wilcoxon signed-rank test across folds; p < 0.05 required to declare one model superior |
| Alert if Accuracy Degrades | Trigger re-comparison if any production model's F1 drops below 80% on rolling 30-day evaluation window |
| Retraining Cadence | Monthly, or triggered by accuracy degradation below threshold; full re-comparison across all candidate models at each retraining cycle |

#### 7.5.6 Model Selection and Promotion

After each evaluation cycle, the framework produces a per-machine model ranking. The top-performing model for each machine is promoted to production. The selection and promotion process follows these rules: the model with the highest F1-score on the held-out test set is selected; if two models are within 1% F1, the model with lower inference latency is preferred; if a Track B model (LSTM/GRU) is selected, it must outperform the best Track A model by at least 2% F1 to justify the additional computational overhead of sequence processing; model promotion requires validation on a minimum of 2 weeks of unseen production data before replacing the current production model; the previous production model is retained as a rollback candidate for 30 days.

| Machine | Track A Winner | Track B Winner | Production Model | F1-Score |
|---|---|---|---|---|
| CAB-INS02 | Determined at training | Determined at training | Best overall | ≥ 85% target |
| CAB-CVL-HV | Determined at training | Determined at training | Best overall | ≥ 85% target |
| CAB-ASM4000 | Determined at training | Determined at training | Best overall | ≥ 85% target |

#### 7.5.7 Labeling Strategy

Training labels are derived from historical maintenance logs and breakdown records obtained from the MES API. A binary target variable is created: 1 if a breakdown occurred within the next 4–24 hours of the observation window, 0 otherwise. Historical data of 3–6 months from MES is required for initial model training. The same labeled dataset is used across all candidate models in both Track A and Track B to ensure fair comparison.

#### 7.5.8 Technology Requirements

The multi-algorithm framework requires the following additions to the technology stack defined in Section 7.8: LightGBM (Python `lightgbm` package) for Track A; GRU implementation via PyTorch (already included for LSTM); scikit-learn Random Forest (already included via scikit-learn). No additional infrastructure is required, as all models operate on the same feature vectors or sensor sequences and are served through the same FastAPI inference endpoint. The inference endpoint implements a model router that loads the promoted model per machine at startup and supports hot-swapping models on promotion events.

### 7.6 Output Channels

The PdM Prediction Service delivers results through three parallel output channels. Each prediction cycle produces a result that is dispatched simultaneously to all enabled channels.

#### 7.6.1 Channel 1: Prediction API (Return to MES)

The primary output channel returns prediction results to the MES via a REST API response or webhook callback. This allows the MES to incorporate machine health predictions into its own workflows, including production scheduling adjustments, automated CMMS work order generation, and operator notifications through MES-native interfaces.

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/predictions/{machine_id}` | GET | Returns the latest prediction for a specific machine |
| `/api/v1/predictions/all` | GET | Returns predictions for all monitored machines |
| `/api/v1/predictions/history/{machine_id}` | GET | Returns prediction history with outcomes for auditing |
| `/webhook/predictions` | POST (callback) | Pushes new predictions to a MES-configured endpoint |

The prediction payload includes: `machine_id`, `timestamp`, `risk_score` (0.0–1.0), `risk_level` (Healthy / Warning / Critical), `predicted_failure_window` (hours), top contributing sensors with importance scores, and model version used.

#### 7.6.2 Channel 2: Web Dashboard

A standalone web dashboard provides plant operators and managers with visual access to predictions and machine health trends. Unlike v1.0 which specified Grafana, this version uses a custom React-based dashboard for a tailored user experience without requiring Grafana infrastructure.

**Plant Overview:** Risk heat map across all three pilot machines with color-coded status indicators (green/yellow/red). Click-through to machine detail.

**Machine Detail:** Risk score trend over time (5-minute intervals), top contributing sensors with feature importance, predicted failure window countdown, historical prediction accuracy for the machine.

**Alert Log:** Chronological log of all warnings and critical alerts with outcome tracking (was the prediction correct?).

**Reports:** Weekly/monthly summary of predictions vs. actual outcomes, OEE trends, and downtime reduction metrics.

The dashboard refreshes every 5 minutes in sync with the prediction cycle. It does not display live sensor data (that remains in the MES); it shows only prediction outputs and derived insights.

#### 7.6.3 Channel 3: WhatsApp Notifications

Critical and warning-level predictions are pushed to designated WhatsApp groups or individual contacts via the WhatsApp Business API. This provides immediate mobile-accessible alerts to maintenance teams without requiring them to monitor a dashboard.

| Risk Level | WhatsApp Action | Content |
|---|---|---|
| Healthy (0.0–0.3) | No notification | N/A |
| Warning (0.3–0.7) | Message to maintenance group | Machine ID, risk score, top 3 contributing sensors, suggested inspection window |
| Critical (>0.7) | Message to group + individual on-call technician | Machine ID, risk score, predicted failure in X hours, contributing sensors, urgency flag |

WhatsApp messages are sent via the WhatsApp Business API (Meta Cloud API). Message templates must be pre-approved by Meta. The service supports configurable recipient lists per machine and per risk level. A daily summary message can also be configured.

### 7.7 Alert Threshold Logic

The prediction engine evaluates each risk score against a three-tier threshold system that drives all three output channels.

| Risk Score | Status | Dashboard | MES API | WhatsApp |
|---|---|---|---|---|
| 0.0 – 0.3 | Healthy | Green indicator | Normal status returned | No notification |
| 0.3 – 0.7 | Warning | Yellow indicator + sensor spotlight | Warning status + details | Group message |
| > 0.7 | Critical | Red indicator + failure countdown | Critical status + urgency | Group + individual alert |

Thresholds are configurable per machine and will be calibrated during the pilot phase based on observed precision/recall trade-offs.

### 7.8 Technology Stack

| Component | Technology |
|---|---|
| MES API Client | Python (httpx / requests) with circuit breaker |
| Feature Engineering | Python, Pandas, NumPy |
| ML Training | XGBoost, scikit-learn, PyTorch (LSTM) |
| Model Serving / API | FastAPI (REST endpoints for MES + dashboard) |
| Web Dashboard | React + Tailwind CSS + Recharts |
| WhatsApp Integration | WhatsApp Business API (Meta Cloud API) |
| Task Scheduling | APScheduler (polling + retraining) or cron |
| Local Storage | SQLite or PostgreSQL (feature vectors, predictions, model metadata) |
| Monitoring | Prometheus + Grafana (service health and model accuracy) |
| Containerization | Docker + Docker Compose |

### 7.9 Infrastructure and Deployment

The service is deployed as a lightweight containerized application. Since raw data storage is handled by MES, infrastructure requirements are significantly reduced from v1.0.

| Option | Description | Estimated Cost | Inference Latency |
|---|---|---|---|
| Edge (Recommended) | Docker container on on-premise server near MES | ~$2K one-time | < 10 ms |
| Cloud | Cloud VM (AWS/Azure) connecting to MES API | ~$500/month | 50–200 ms (network) |
| Hybrid | Edge inference + cloud for training and dashboard hosting | ~$800/month | < 10 ms inference |

### 7.10 Data Requirements (from MES)

| Requirement | Detail |
|---|---|
| Historical Sensor Data | Minimum 3 months, recommended 6 months at 10-second intervals (via MES bulk export API) |
| Breakdown / Maintenance Logs | Timestamped records with failure type and affected machine (via MES API) |
| Real-Time Sampling Rate | MES API provides latest readings; polling default every 5 minutes |
| Estimated Training Volume | ~1M rows/week/machine; ~78M rows for 6-month training set |
| PdM Local Storage | Feature vectors + predictions only (~500 MB/year for 3 machines) |

---

## 8. User Stories

### 8.1 Machine Operator

As a machine operator, I want to see a color-coded risk indicator for each machine on the web dashboard so that I can prioritize attention on machines approaching failure. I want to receive a WhatsApp message when a machine enters critical status so I can respond even when away from the dashboard or shop floor.

### 8.2 Maintenance Technician

As a maintenance technician, I want to receive a WhatsApp alert with the predicted failure type and top contributing sensors so I can prepare the correct tools and parts before arriving at the machine. I want to see feature importance for each prediction on the dashboard so I understand why the model is flagging a machine.

### 8.3 Plant Manager

As a plant manager, I want a weekly summary on the dashboard and via WhatsApp of predictions versus actual outcomes so I can track model performance and ROI. I want to see OEE improvement trends and downtime reduction metrics.

### 8.4 MES System / Production Planner

As the MES system (or a production planner using MES), I want to receive prediction results via API so I can automatically adjust production schedules, trigger CMMS work orders, and incorporate machine health into the overall production plan without leaving the MES interface.

---

## 9. Non-Functional Requirements

| Requirement | Specification |
|---|---|
| Availability | 99.5% uptime for prediction service and dashboard |
| Latency | < 10 ms inference; < 5 sec dashboard refresh; < 30 sec WhatsApp delivery |
| MES API Dependency | Graceful degradation if MES API is unavailable; use last known feature vector with staleness indicator |
| Scalability | Support 20+ machines without re-architecture (Phase 2) |
| Security | TLS encryption for MES API communication; API key or OAuth2 authentication; role-based dashboard access |
| Data Retention | Feature vectors and predictions retained for 12 months locally; raw data owned by MES |
| Model Accuracy | Minimum 85% F1; alert if accuracy degrades below 80% |
| Maintainability | Automated retraining pipeline with model versioning and rollback |
| WhatsApp Compliance | Message templates approved by Meta; opt-in/opt-out management for recipients |

---

## 10. Implementation Timeline

| Phase | Deliverable | Duration | Milestone |
|---|---|---|---|
| Week 1–2 | MES API integration + data validation + initial feature engineering | 10 days | Successful data pull from MES for all 3 machines |
| Week 3 | Train prototype XGBoost model on historical data from MES | 5 days | 85% F1 accuracy achieved |
| Week 4 | Deploy prediction service on pilot machines + MES API return | 5 days | First live predictions returned to MES |
| Month 2 | Web dashboard development + WhatsApp integration | 4 weeks | All 3 output channels operational |
| Month 3–4 | LSTM model + model monitoring + threshold calibration | 8 weeks | Full production system |
| Month 5–6 | Scale to 20 machines + RUL modeling | 8 weeks | 30% downtime reduction verified |

---

## 11. Success Metrics and KPIs

| Metric | Baseline (Current) | Target (6 Months) |
|---|---|---|
| Unplanned Downtime | Current plant average | 30–40% reduction |
| OEE | Current plant OEE | 25–35% improvement |
| Model F1-Score | N/A (no model) | ≥ 85% on test data |
| False Positive Rate | N/A | < 15% (operator trust) |
| Alert Lead Time | 0 (reactive) | 4–24 hours advance warning |
| Maintenance Cost | Current spend | 20% cost reduction |
| MES API Uptime | N/A | > 99% successful data pulls |
| WhatsApp Delivery Rate | N/A | > 95% message delivery within 30 seconds |

---

## 12. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| MES API unavailability or latency | Medium | High | Circuit breaker pattern with exponential backoff; fallback to last known feature vector; staleness alerts on dashboard |
| MES API data format changes | Medium | High | API versioning contract with MES team; schema validation on every data pull; automated alerts on format drift |
| Insufficient labeled failures in historical data | Medium | High | Deploy Isolation Forest for cold-start; use anomaly detection until enough labels accumulate |
| High false positive rate erodes operator trust | Medium | High | Tune thresholds during pilot; provide feature importance explanations; implement snooze on dashboard |
| WhatsApp Business API rate limits or downtime | Low | Medium | Message queuing with retry logic; fallback to email/SMS if WhatsApp unavailable |
| Model drift over time | High | Medium | Automated retraining pipeline with accuracy monitoring and rollback capability |
| Resistance to adoption by operators | Low | Medium | Involve operators in pilot; show feature importance for transparency; gradual rollout |

---

## 13. MES Integration Responsibilities

This section clarifies the division of responsibilities between the MES team and the PdM Prediction Service team.

| Responsibility | Owner | Notes |
|---|---|---|
| Raw sensor data collection from machines | MES | IIoT gateway and sensor connectivity |
| Raw sensor data storage and retention | MES | Time-series storage and archival policies |
| REST API endpoints for sensor data access | MES | Must support machine-level queries with time windowing |
| REST API endpoints for maintenance logs | MES | Required for model training labels |
| API authentication and rate limiting | MES | API key or OAuth2 credentials provided to PdM team |
| API uptime SLA (target: 99.5%) | MES | Agreed SLA with graceful degradation on PdM side |
| Feature engineering from raw data | PdM Service | Consumes MES API, computes ML features |
| ML model training, deployment, monitoring | PdM Service | Full model lifecycle management |
| Prediction API (for MES to consume) | PdM Service | Webhook or polling endpoint |
| Web dashboard development and hosting | PdM Service | Standalone application |
| WhatsApp integration and message delivery | PdM Service | WhatsApp Business API management |
| CMMS work order creation from predictions | MES | MES consumes prediction API and triggers CMMS actions |

---

## 14. Approvals

This PRD requires review and sign-off from the following stakeholders prior to implementation.

| Role | Name | Date | Signature |
|---|---|---|---|
| Plant Manager | | | |
| Maintenance Manager | | | |
| IT / OT Lead | | | |
| MES System Owner | | | |
| Data Science Lead | | | |
| Finance / Budget Owner | | | |
