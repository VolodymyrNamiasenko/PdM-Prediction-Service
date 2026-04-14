# Data Guard: Validation & Pre-Processing Layer

**PdM Prediction Service for CAB-INS02 Extrusion Line**

| Property | Value |
|---|---|
| Document Version | 1.0 |
| Author | Project Team |
| Status | Draft for Review |
| Applicable Milestones | M1 (MES Polling) → M2 (Feature Engineering) |

---

## 1. Purpose and Rationale

The Data Guard is a mandatory middleware layer within the PdM Prediction Service that sits between the MES data source and the XGBoost inference engine. Its purpose is to guarantee that every data payload reaching the model is structurally valid, statistically plausible, and semantically meaningful.

Manufacturing Execution Systems (MES) in brownfield factory environments often deliver data with structural inconsistencies, intermittent sensor dropouts, out-of-range spikes, and format mismatches. Without a dedicated validation layer, these anomalies propagate directly into the model, producing unreliable risk scores and eroding operator trust in the system.

The Data Guard addresses this by enforcing a strict contract between raw MES output and model input, ensuring that the XGBoost model never receives data it was not trained to interpret.

---

## 2. Scope

The Data Guard handles all data arriving from the MES, regardless of transport mechanism. It supports two ingestion modes:

- **API Mode (JSON):** The MES pushes JSON payloads to the FastAPI endpoint at a defined polling interval.
- **File Mode (CSV):** The MES exports CSV files to a shared landing zone, which a file-watcher service detects and processes.

In both modes, the Data Guard performs identical validation logic. The only difference is the initial parsing step (JSON deserialization vs. CSV read with header mapping).

---

## 3. Three-Stage Pipeline Architecture

The Data Guard operates as a sequential three-stage pipeline. Each stage acts as a filter; data must pass all three stages before reaching the feature engineering module.

### 3.1 Stage A: Structural Adapter

**Objective:** Translate raw MES field names and data formats into the canonical schema expected by the model.

MES systems rarely export data using the same field names or structures that the ML model was trained on. This stage uses the Adapter Pattern to provide a mapping layer that decouples the MES schema from the model schema.

**Key operations:**

- **Field name mapping:** Translates MES-native identifiers (e.g., `SCW_PR_1`) to model-expected names (e.g., `pvc_screw_pressure_bar`) using a configurable mapping dictionary.
- **Type casting:** Converts all incoming values to the data types expected by XGBoost (`float64` for sensor readings, `int` for status flags, ISO 8601 strings for timestamps).
- **Unit normalization:** Converts values to the units used during model training (e.g., PSI to bar, Fahrenheit to Celsius) if the MES reports in different units.
- **CSV header assignment:** In File Mode, assigns canonical column names to positional CSV columns when headers are missing or non-standard.

**Implementation:** Pydantic models define the target schema. Incoming payloads are validated against this schema, and any field that fails type coercion triggers an immediate rejection with a `422 Unprocessable Entity` response (API Mode) or a logged error (File Mode).

### 3.2 Stage B: Data Integrity Sanitizer

**Objective:** Detect and handle data quality issues that pass structural validation but are semantically invalid or statistically implausible.

This stage enforces business rules specific to the CAB-INS02 extrusion line. It addresses sensor errors, transmission artifacts, and intermittent data gaps that are common in industrial environments.

**Validation Rules:**

| Rule | Logic | Action on Failure |
|---|---|---|
| Range validation | Each sensor value must fall within physically possible bounds (e.g., `pvc_screw_pressure_bar`: 0–300 bar; `motor_load_amps`: 0–500 A) | Flag value as Sensor Error; replace with NaN for downstream handling |
| Null / missing value handling | Individual fields missing from a record | Apply forward-fill imputation using the last known good value from the rolling buffer. If no prior value exists, reject the record. |
| Spike detection | A single-sample deviation exceeding 3 standard deviations from the rolling 5-minute mean | Flag as transient spike; apply median filter over a 3-sample window to smooth the anomaly |
| Timestamp continuity | Consecutive records must have timestamps within the expected sampling interval (±2 seconds of the 10-second target) | Log a gap event. If gap exceeds 60 seconds, insert placeholder records marked as interpolated. |
| Duplicate detection | Records with identical timestamps | Retain the first occurrence; discard subsequent duplicates |
| Stale data detection | Identical sensor values across 10+ consecutive readings (sensor freeze) | Flag as Sensor Stale; mark affected fields as unreliable in the data quality metadata |

**Implementation:** Pandera (a DataFrame validation library) enforces column-level statistical checks. Each rule is defined as a Pandera `Check` constraint, making the validation pipeline declarative and auditable.

> **Additional Recommendation: Adaptive Thresholds.**
> Static range thresholds become stale as equipment ages or operating conditions change. The Data Guard should support a periodic recalibration mechanism that updates validation bounds based on a rolling 30-day statistical profile of each sensor. This ensures that the validation rules remain aligned with the actual operating envelope of the machine, rather than relying solely on theoretical limits defined at commissioning.

### 3.3 Stage C: Operational Context Gate

**Objective:** Prevent the model from generating predictions when the machine is in a state where predictions are meaningless.

The XGBoost model was trained on data from active production runs. Feeding it data from idle, startup, or shutdown states produces predictions that are not only inaccurate but actively misleading. This stage acts as a binary gate.

**Gate logic:**

| Condition | Action |
|---|---|
| `machine_status = 0` (Off) | Bypass model entirely. Return `risk_score: 0`, `risk_level: "Machine Off"` |
| `line_speed_m_min = 0` (Idle) | Bypass model. Return `risk_score: 0`, `risk_level: "Line Idle"` |
| `line_speed_m_min` < minimum production threshold | Bypass model. Return `risk_level: "Startup/Shutdown — Not Predictive"` |
| Elapsed time since startup < warm-up period (configurable, default 10 min) | Bypass model. Return `risk_level: "Warm-Up Phase — Not Predictive"` |
| All gate conditions passed | Proceed to Feature Engineering pipeline |

> **Additional Recommendation: Transition State Handling.**
> Extrusion lines exhibit transient sensor behavior during startup and shutdown that does not follow steady-state patterns. Rather than a simple on/off gate, the Data Guard should implement a warm-up buffer. After the machine transitions from Off to On, the system should accumulate data for a configurable warm-up period (default: 10 minutes) before permitting predictions. This prevents false alarms triggered by normal startup transients.

---

## 4. Error Handling and Observability

Data quality failures are inevitable in manufacturing environments. The Data Guard must handle failures gracefully, without crashing the service, and must provide operators with clear visibility into data health.

### 4.1 Failure Response Strategy

| Failure Severity | Condition | System Response |
|---|---|---|
| Soft failure | 1–2 individual sensor values out of range or missing | Impute or smooth affected values; proceed with prediction; attach `data_quality: "Degraded"` flag to the response |
| Hard failure | Critical sensors missing (e.g., `pvc_screw_pressure_bar`), or >30% of fields invalid | Do not predict. Return `risk_level: "Inconclusive — Sensor Data Error"` with a list of affected sensors |
| Structural failure | Payload cannot be parsed (malformed JSON, corrupt CSV) | Reject with HTTP 422. Log the raw payload to a quarantine store for debugging |

### 4.2 Quarantine Log

Every rejected or degraded payload is persisted to a quarantine data store (a dedicated database table or file-based log, depending on infrastructure). The quarantine log captures the raw payload, the timestamp of receipt, the specific validation rules that failed, and the action taken. This log serves two purposes: it provides a debugging trail for the data engineering team, and it generates a data quality report that can be reviewed with the MES team to drive improvements at the source.

### 4.3 Dashboard Integration

The operator-facing dashboard must reflect data health status in real time. When the Data Guard downgrades a prediction due to data quality, the dashboard should display the current risk score alongside a clear indicator that the score is based on degraded data. When the Data Guard blocks prediction entirely, the dashboard should show a distinct "Inconclusive" state rather than displaying the last known score, which could mislead the operator into thinking the system is still monitoring normally.

---

## 5. CSV Ingestion: File Mode Considerations

When the MES is limited to CSV export (no real-time API), the Data Guard includes an additional file ingestion service that introduces several CSV-specific handling requirements.

| Challenge | Technical Solution |
|---|---|
| Partial writes (MES still writing when reader triggers) | Implement a file stability check: monitor file size at 2-second intervals; proceed only after size is unchanged for two consecutive checks |
| Missing or inconsistent headers | Use a positional column map defined in the adapter configuration; validate column count before applying the map |
| Cumulative files (MES appends to the same file) | Track the last processed timestamp in a lightweight state store (SQLite or Redis). On each read, filter to rows with timestamps after the last processed mark. |
| Encoding issues | Default to UTF-8 with fallback to ISO-8859-1; log encoding detection results |
| File archival | After successful processing, move the CSV to an `/archive/` directory with a processing timestamp suffix to prevent reprocessing |

> **Additional Recommendation: Checksum Verification.**
> If the MES supports it, request that a checksum or row count is included in the CSV filename or as a companion metadata file. This allows the Data Guard to verify file integrity before processing, catching truncated exports or network transfer errors that would otherwise produce silent data loss.

---

## 6. Data Quality Metrics and Reporting

The Data Guard should emit the following metrics at regular intervals (per polling cycle and aggregated daily) to support ongoing system health monitoring and continuous improvement:

- **Records received:** Total number of raw records ingested in the period.
- **Records accepted:** Records that passed all three stages and were forwarded to the feature engineering pipeline.
- **Records imputed:** Records where one or more fields were corrected via forward-fill, median filter, or other imputation method.
- **Records rejected:** Records that triggered a hard or structural failure.
- **Sensor-level error rates:** Per-sensor breakdown of out-of-range, null, stale, and spike events, enabling targeted maintenance or recalibration of specific sensors.
- **Gate bypass count:** Number of records filtered by the Operational Context Gate (machine off, idle, warm-up).

These metrics should be accessible via a `/data-guard/health` API endpoint and visualized on an administrative section of the dashboard.

---

## 7. Configuration Management

All Data Guard parameters must be externalized to a configuration file or environment variables, not hardcoded. This allows the operations team to adjust validation behavior without redeploying the service.

**Configurable parameters:**

| Parameter | Default Value | Description |
|---|---|---|
| `sensor_range_limits` | (per sensor) | Min/max physically valid range for each sensor field |
| `spike_std_threshold` | 3.0 | Number of standard deviations for spike detection |
| `spike_window_seconds` | 300 | Rolling window duration for spike detection baseline |
| `forward_fill_max_gap` | 60 seconds | Maximum gap duration for which forward-fill imputation is applied |
| `warm_up_duration` | 600 seconds | Post-startup period during which predictions are suppressed |
| `min_production_speed` | 0.5 m/min | Minimum line speed threshold to consider the line in active production |
| `hard_failure_threshold` | 0.30 | Fraction of invalid fields that triggers a hard failure (no prediction) |
| `csv_stability_interval` | 2 seconds | File size polling interval for partial write detection |
| `quarantine_retention_days` | 90 | Duration for retaining quarantine log entries |

---

## 8. Non-Functional Requirements

| Requirement | Target | Rationale |
|---|---|---|
| Processing latency (per record) | < 5 ms | Must not consume more than half of the 10 ms total inference budget defined in the PRD |
| Availability | 99.5% uptime | Data Guard failure means the entire prediction pipeline is blind |
| Graceful degradation | Soft failures do not block predictions | Partial data is better than no data, provided degradation is clearly flagged |
| Idempotency | Reprocessing the same record produces identical output | Required for CSV replay scenarios and debugging |
| Testability | Each stage independently unit-testable | Validation logic must be verifiable in isolation from the pipeline |

---

## 9. Integration with Technical Specification

The Data Guard inserts into the existing data flow as follows:

1. **Milestone 1 (MES Polling / CSV Ingestion):** Raw data arrives via API or file watcher.
2. **Data Guard Stage A (Structural Adapter):** Maps and casts raw data to canonical schema.
3. **Data Guard Stage B (Integrity Sanitizer):** Validates, cleans, and flags data quality issues.
4. **Data Guard Stage C (Operational Context Gate):** Filters non-predictive machine states.
5. **Milestone 2 (Feature Engineering):** Clean, validated data enters the rolling buffer and statistical feature computation.
6. **Milestone 3 (XGBoost Inference):** Model receives features derived exclusively from validated data.

This placement ensures that the feature engineering pipeline and the XGBoost model are fully isolated from raw data quality issues. Any data anomaly that reaches the model is, by definition, a Data Guard defect and can be traced through the quarantine log.

---

## 10. Appendix: Sample Adapter Mapping (CAB-INS02)

The following table illustrates the field mapping for the CAB-INS02 extrusion line. Actual mappings will be finalized during integration testing with the MES vendor.

| MES Field Name | Canonical Model Field | Data Type | Valid Range |
|---|---|---|---|
| `SCW_PR_1` | `pvc_screw_pressure_bar` | float64 | 0 – 300 bar |
| `SCW_PR_2` | `pvc_screw_pressure_2_bar` | float64 | 0 – 300 bar |
| `MTR_LD` | `motor_load_amps` | float64 | 0 – 500 A |
| `MTR_LD_PCT` | `motor_load_percent` | float64 | 0 – 100 % |
| `LN_SPD` | `line_speed_m_min` | float64 | 0 – 50 m/min |
| `MCH_ST` | `machine_status` | int | 0 or 1 |
| `TS` | `timestamp` | ISO 8601 string | — |
| `EXT_TMP_1` | `extruder_temp_zone_1_c` | float64 | 0 – 350 °C |
| `EXT_TMP_2` | `extruder_temp_zone_2_c` | float64 | 0 – 350 °C |
| `COOL_TMP` | `cooling_water_temp_c` | float64 | 5 – 60 °C |

---

*End of Data Guard PRD Section*
