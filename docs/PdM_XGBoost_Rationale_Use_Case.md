# PdM XGBoost Rationale — Use Case and Explanation

**Comprehensive narrative for the CAB‑INS02 prediction behavior, aligned with the current implementation**

This document captures the **use case**, the **observed behavior**, the **doubts raised**, and the **technical explanation** for why small feature changes can lead to large jumps in the XGBoost risk score. It is intended for business and engineering stakeholders who need clarity on model behavior during early integration.

---

## 1. Use Case Context

We are building a **Predictive Maintenance (PdM) Prediction Service** for the CAB‑INS02 extrusion line. The service ingests sensor data (pressures, speeds, motor load, line speed, tension, diameter) and predicts **maintenance_required** risk.

At this stage:
- A **trained XGBoost model** is used for inference.
- The API accepts JSON payloads and returns `risk_score` and `risk_level`.
- The UI shows a risk score trend and parameter correlation view.

The model was trained on historical synthetic + labeled data with the **30‑minute warning horizon** logic. The output is a probability of entering a failure‑risk state.

---

## 2. Observed Behavior

Two consecutive inputs (10 seconds apart) produced dramatically different risk scores:

### Example 1 (Risk ≈ 0.30, Warning)
```json
{
  "timestamp": "2026-03-20T10:19:40Z",
  "features": {
    "pvc_screw_pressure_bar": 147.2,
    "color_screw_pressure_bar": 136.6,
    "nylon_screw_pressure_bar": 129.9,
    "pvc_screw_speed_rpm": 306,
    "color_screw_speed_rpm": 292,
    "nylon_screw_speed_rpm": 278,
    "motor_load_amps": 12.9,
    "motor_load_percent": 70.2,
    "line_speed_m_min": 41.5,
    "payoff_tension_n": 222,
    "takeup_tension_n": 220,
    "post_extrusion_diameter_mm": 8.22
  }
}
```

### Example 2 (Risk ≈ 0.99997, Critical)
```json
{
  "timestamp": "2026-03-20T10:19:50Z",
  "features": {
    "pvc_screw_pressure_bar": 149.1,
    "color_screw_pressure_bar": 135.0,
    "nylon_screw_pressure_bar": 130.0,
    "pvc_screw_speed_rpm": 303,
    "color_screw_speed_rpm": 290,
    "nylon_screw_speed_rpm": 274,
    "motor_load_amps": 12.7,
    "motor_load_percent": 70.9,
    "line_speed_m_min": 41.3,
    "payoff_tension_n": 223,
    "takeup_tension_n": 218,
    "post_extrusion_diameter_mm": 8.23
  }
}
```

### Doubt Raised
> “Minor changes in values cause a major change in risk_score — why?”

---

## 3. Explanation (Why the Jump Happens)

XGBoost is **not linear**. It is a **tree‑based model**.

Each decision tree in XGBoost uses threshold splits such as:

```
if pvc_screw_pressure_bar > 148.5 and
   pvc_screw_speed_rpm < 304 and
   line_speed_m_min < 41.4
then add +2.1 to score
```

So small numerical shifts can **cross decision thresholds**, activating multiple branches across many trees. The effect compounds because XGBoost adds tree outputs together in log‑odds space.

That means:
- One or two feature thresholds crossed can trigger **several tree votes**.
- The combined logit can move from slightly negative to strongly positive.
- The probability jumps sharply (sigmoid of logit).

**Key insight: XGBoost outputs are not smooth curves — they are step‑wise jumps.**

This is normal and expected behavior for tree ensembles, especially when multiple features are close to split boundaries.

---

## 4. Internal Explanation Evidence

For these exact two examples, the model’s internal contribution analysis showed:

### Example 1 (Risk ≈ 0.30)
Top contributions (logit space):
- `color_screw_pressure_bar` **+4.84**
- bias **−3.61**
- `post_extrusion_diameter_mm` **−0.76**
- `line_speed_m_min` **−0.38**
- `nylon_screw_pressure_bar` **−0.23**

Net result: logit ≈ −0.84 → probability ≈ 0.30

### Example 2 (Risk ≈ 0.99997)
Top contributions:
- `pvc_screw_pressure_bar` **+4.33**
- `pvc_screw_speed_rpm` **+1.98**
- `nylon_screw_speed_rpm` **+1.92**
- `line_speed_m_min` **+1.86**
- `color_screw_speed_rpm` **+1.84**
- `motor_load_percent` **+1.41**

Net result: logit ≈ +10.44 → probability ≈ 0.99997

This demonstrates that **a few small shifts aligned with high‑impact splits** can move the total logit significantly.

---

## 5. Challenges Highlighted

1. **Interpretability**
   Tree models are harder to interpret than linear models. The “why” behind each prediction is not visually obvious.

2. **Threshold Sensitivity**
   Slight sensor variation can cross split boundaries. This can feel unstable unless explained or smoothed.

3. **Operator Trust**
   If the system “jumps” from Warning to Critical without an obvious physical change, trust can erode.

4. **Synthetic Data Effects**
   If training data has tight clusters, the model learns **sharp boundaries** that exaggerate jumps.

---

## 6. How This Can Be Addressed

To make model behavior smoother and more transparent:

1. **Probability calibration** (Platt or isotonic)
   Makes outputs more realistic and less extreme.

2. **Temporal smoothing**
   Use rolling average of last N risk scores.

3. **Monotonic constraints**
   Force certain features to only increase/decrease risk, improving stability.

4. **SHAP explanations**
   Return per‑feature contributions in the API response so the UI shows “why.”

---

## 7. Practical Takeaway

The sharp jump is **not a bug**, but a natural result of:

- Tree‑based thresholds
- Multiple features crossing splits simultaneously
- Logit accumulation in XGBoost

**This behavior is expected — but it can and should be explained in the UI or smoothed for operator trust.**

---

## 8. Status in Current System

✅ XGBoost model loaded in API
✅ Predicts risk_score and risk_level
✅ UI supports visualization
⛔ No explanation per prediction yet (next step if required)

---

**End of Document**
