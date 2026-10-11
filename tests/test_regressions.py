import unittest
import json
import secrets
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from app import main
from pipeline import RAW_FEATURES, add_temporal_features
from train_xgb_cab_ins02 import chronological_splits


class RegressionTests(unittest.TestCase):
    def setUp(self):
        for name in ("DEV_USERNAME", "DEV_PASSWORD", "DEV_TOKEN"):
            setting = patch.object(main, name, secrets.token_urlsafe(32))
            setting.start()
            self.addCleanup(setting.stop)
        main._reset_machine_state("test")
        self.features = {key: 10.0 for key in RAW_FEATURES}

    def test_timestamp_and_finite_validation(self):
        for timestamp in ("bad", "2026-01-01T00:00:00"):
            with self.assertRaises(ValueError):
                main.PredictionRequest(machine_id="test", timestamp=timestamp, features=self.features)
        with self.assertRaises(ValueError):
            main.PredictionRequest(machine_id="test", timestamp="2026-01-01T00:00:00Z", features={"motor_load_amps": float("nan")})

    def test_missing_noncritical_sensor_fails_closed(self):
        del self.features["payoff_tension_n"]
        sanitized, metadata, hard_fail = main._sanitize_features("test", "2026-01-01T00:00:00Z", self.features)
        self.assertTrue(hard_fail)
        self.assertIsNone(sanitized)

    def test_no_future_fill_or_time_reversal(self):
        missing = dict(self.features)
        del missing["pvc_screw_pressure_bar"]
        result = main._sanitize_features("test", "2026-01-01T00:00:00Z", missing, [missing, self.features], 0)
        self.assertTrue(result[2])
        main._sanitize_features("test", "2026-01-01T00:00:10Z", self.features)
        self.assertIn("out_of_order_timestamp", main._sanitize_features("test", "2026-01-01T00:00:00Z", self.features)[1]["flags"])

    def test_prediction_generates_step_alert(self):
        main._physics_sanity("test", self.features, 0.2)
        changed = dict(self.features, pvc_screw_pressure_bar=12.0)
        request = main.PredictionRequest(machine_id="test", timestamp="2026-01-01T00:00:10Z", features=changed)
        with patch.object(main, "_xgb_margin", return_value=0.1):
            result = main.predict(request, main.DEV_TOKEN)
        self.assertTrue(any(a["window"] == "10s" for a in result["roc_alerts"]))

    def test_calibration_extremes(self):
        self.assertEqual(main._calibrate(-10000), 0.0)
        self.assertEqual(main._calibrate(10000), 1.0)

    def test_auth_fails_closed_without_configuration(self):
        with patch.object(main, "DEV_TOKEN", ""):
            response = TestClient(main.app).post("/token", data={"username": main.DEV_USERNAME, "password": main.DEV_PASSWORD})
        self.assertEqual(response.status_code, 503)

    def test_splits_are_real_and_chronological(self):
        df = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=20, freq="10s", tz="UTC"), "row_id": range(20)})
        train, dev, test = chronological_splits(df)
        self.assertEqual((len(train), len(dev), len(test)), (12, 4, 4))
        self.assertLess(train.timestamp.max(), dev.timestamp.min())
        self.assertLess(dev.timestamp.max(), test.timestamp.min())
        self.assertEqual(test.row_id.tolist(), [16, 17, 18, 19])

    def test_temporal_features_are_causal(self):
        df = pd.DataFrame({key: np.arange(150, dtype=float) for key in RAW_FEATURES})
        before = add_temporal_features(df).iloc[:100]
        df.iloc[100:] = 10000
        after = add_temporal_features(df).iloc[:100]
        pd.testing.assert_frame_equal(before, after)

    def test_model_paths_work_from_checkout(self):
        self.assertTrue(main.MODEL_PATH.exists())
        self.assertIsNotNone(main._model)
        self.assertEqual(TestClient(main.app).get("/health").json()["status"], "ok")

    def test_large_gap_discards_stale_machine_history(self):
        main._sanitize_features("test", "2026-01-01T00:00:00Z", self.features)
        main._history["test"] = [{"timestamp": "2026-01-01T00:00:00Z"}]
        result = main._sanitize_features("test", "2026-01-01T01:00:00Z", self.features)
        self.assertIn("history_reset", result[1]["flags"])
        self.assertNotIn("test", main._history)

    def test_included_fixture_infers_without_network(self):
        path = next((Path(__file__).resolve().parents[1] / "ref_data_set").glob("breakdown_*.json"))
        records = json.loads(path.read_text())[:125]
        with TestClient(main.app) as client:
            response = client.post("/api/v1/predict/batch?reset_history=true", json=records, headers={"Authorization": "Bearer " + main.DEV_TOKEN})
        self.assertEqual(response.status_code, 200, response.text[:300])
        results = response.json()
        self.assertEqual(len(results), len(records))
        self.assertTrue(any(not r["warmup"] and r["data_quality"] != "HardFail" for r in results))
        self.assertTrue(all(np.isfinite(r["calibrated_risk_score"]) for r in results))


if __name__ == "__main__":
    unittest.main()
