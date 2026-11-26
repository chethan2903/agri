import json
import os
import tempfile
import unittest

import pandas as pd

from backend import app as backend_app
from ml import train_and_evaluate


class AgriSenseReviewFeaturesTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_db_fd, self.tmp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.tmp_db_fd)
        self.orig_db = backend_app.DATABASE
        backend_app.DATABASE = self.tmp_db_path
        backend_app._user_histories.clear()
        backend_app.init_db()

        backend_app.app.config["TESTING"] = True
        self.client = backend_app.app.test_client()

        # Register and log in a test user
        self.client.post(
            "/register",
            data={
                "username": "tester",
                "password": "password123",
                "confirm": "password123",
                "farm_name": "Trial Site Alpha",
                "location": "Region A",
            },
        )
        self.client.post(
            "/login",
            data={"username": "tester", "password": "password123"},
        )
        res = self.client.get("/api/user")
        self.device_id = res.get_json()["device_id"]

    def tearDown(self):
        backend_app.DATABASE = self.orig_db
        backend_app._user_histories.clear()
        if os.path.exists(self.tmp_db_path):
            os.remove(self.tmp_db_path)

    def test_calibration_and_moisture_ingest_persistence(self):
        # Update calibration to clay soil and custom dry/wet ADC baselines
        cal_res = self.client.post(
            "/api/calibration",
            json={
                "site_name": "Trial-Site-03",
                "soil_type": "clay",
                "dry_adc": 3000,
                "wet_adc": 1000,
                "temp_offset": -0.5,
                "humidity_offset": 1.5,
            },
        )
        self.assertEqual(cal_res.status_code, 200)
        self.assertEqual(cal_res.get_json()["calibration"]["soil_type"], "clay")

        # Invalid calibration (dry <= wet) must return 400
        bad_cal = self.client.post(
            "/api/calibration",
            json={"dry_adc": 1000, "wet_adc": 2000, "soil_type": "loam"},
        )
        self.assertEqual(bad_cal.status_code, 400)

        # Post raw ADC hardware telemetry
        ingest_res = self.client.post(
            "/api/sensor-data",
            json={
                "device_id": self.device_id,
                "raw_moisture_adc": 2000,  # 50% normalized * 0.94 clay factor = 47.0%
                "temperature": 27.0,
                "humidity": 65.0,
                "ph": 6.5,
                "nitrogen": 90.0,
                "phosphorus": 42.0,
                "potassium": 43.0,
            },
        )
        self.assertEqual(ingest_res.status_code, 200)
        reading = ingest_res.get_json()["reading"]
        self.assertEqual(reading["moisture"], 47.0)
        self.assertEqual(reading["temperature"], 26.5)
        self.assertEqual(reading["humidity"], 66.5)

        # /api/soil should serve the fresh hardware reading
        soil_res = self.client.get("/api/soil")
        self.assertEqual(soil_res.status_code, 200)
        self.assertEqual(soil_res.get_json()["data"]["source"], "hardware")

        # /api/reliability should reflect persisted reading
        rel_res = self.client.get("/api/reliability")
        self.assertEqual(rel_res.status_code, 200)
        rel = rel_res.get_json()["reliability"]
        self.assertEqual(rel["total_persisted_readings"], 1)
        self.assertEqual(rel["hardware_readings"], 1)
        self.assertEqual(rel["valid_reading_rate_pct"], 100.0)

    def test_sensor_validation_metrics(self):
        r1 = self.client.post(
            "/api/validate-sensor",
            json={
                "sensor_type": "dht22_temp",
                "measured_value": 25.4,
                "reference_value": 25.0,
                "notes": "Reference thermo-hygrometer check 1",
            },
        )
        self.assertEqual(r1.status_code, 200)
        self.assertAlmostEqual(r1.get_json()["abs_error"], 0.4, places=3)

        r2 = self.client.post(
            "/api/validate-sensor",
            json={
                "sensor_type": "dht22_temp",
                "measured_value": 26.2,
                "reference_value": 26.0,
            },
        )
        self.assertEqual(r2.status_code, 200)

        summary_res = self.client.get("/api/validate-sensor")
        self.assertEqual(summary_res.status_code, 200)
        dht_summary = summary_res.get_json()["summary"]["dht22_temp"]
        self.assertEqual(dht_summary["count"], 2)
        self.assertAlmostEqual(dht_summary["mae"], 0.3, places=3)

    def test_model_info_and_inspect_existing(self):
        res = self.client.get("/api/model-info")
        self.assertEqual(res.status_code, 200)
        model = res.get_json()["model"]
        self.assertEqual(model["model_type"], "RandomForestClassifier")
        self.assertEqual(model["n_classes"], 22)
        self.assertEqual(model["hyperparameters"]["n_estimators"], 100)

        inspected = train_and_evaluate.inspect_existing_model()
        self.assertEqual(inspected["n_features"], 6)
        self.assertEqual(inspected["hyperparameters"]["random_state"], 42)

    def test_train_and_tune_pipeline_split(self):
        # Create small synthetic dataset with 2 classes (25 samples each) to verify split & GridSearchCV
        rows = []
        for i in range(25):
            rows.append({"N": 90 + i % 5, "P": 40, "K": 40, "temperature": 22, "humidity": 80, "ph": 6.5, "label": "rice"})
            rows.append({"N": 20 + i % 5, "P": 60, "K": 20, "temperature": 28, "humidity": 55, "ph": 6.8, "label": "maize"})

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "sample_crops.csv")
            meta_path = os.path.join(tmpdir, "meta.json")
            pd.DataFrame(rows).to_csv(csv_path, index=False)

            meta = train_and_evaluate.train_and_tune(
                dataset_path=csv_path,
                test_size=0.2,
                cv_folds=5,
                save_model=False,
                metadata_path=meta_path,
                param_grid={"n_estimators": [10, 20], "max_depth": [None, 5]},
            )
            self.assertEqual(meta["dataset"]["total_samples"], 50)
            self.assertEqual(meta["dataset"]["train_samples"], 40)
            self.assertEqual(meta["dataset"]["test_samples"], 10)
            self.assertTrue(os.path.exists(meta_path))

    def test_field_coverage_page_and_plans_api(self):
        # Page route renders and includes nav + key headings/disclaimer
        page_res = self.client.get("/field-coverage")
        self.assertEqual(page_res.status_code, 200)
        html = page_res.get_data(as_text=True)
        self.assertIn("Field Coverage Planner", html)
        self.assertIn("AgriSense Monitoring Node", html)
        self.assertIn("Approximate dimensions assuming a square-shaped field.", html)
        self.assertIn("/static/js/field_coverage.js", html)

        # Verify required sensor node estimation examples via API
        expected = [
            (0.25, "acres", 2),
            (0.5, "acres", 3),
            (1.0, "acres", 5),
            (1.5, "acres", 8),
            (2.0, "acres", 10),
            (3.0, "acres", 15),
            (5.0, "acres", 25),
            (10.0, "acres", 50),
            (4046.8564224, "sqm", 5),
            (0.40468564224, "hectares", 5),
            (43560.0, "sqft", 5),
        ]
        created_ids = []
        for area_val, unit, expected_nodes in expected:
            res = self.client.post(
                "/api/field-plans",
                json={
                    "field_name": f"Plot {area_val} {unit}",
                    "area_input": area_val,
                    "unit": unit,
                    "density_per_acre": 5,
                },
            )
            self.assertEqual(res.status_code, 200)
            plan = res.get_json()["plan"]
            self.assertEqual(plan["estimated_nodes"], expected_nodes)
            created_ids.append(plan["id"])

        # Reject invalid inputs
        self.assertEqual(
            self.client.post("/api/field-plans", json={"area_input": -1, "unit": "acres"}).status_code,
            400,
        )
        self.assertEqual(
            self.client.post("/api/field-plans", json={"area_input": 0, "unit": "acres"}).status_code,
            400,
        )
        self.assertEqual(
            self.client.post("/api/field-plans", json={"area_input": 1, "unit": "invalid"}).status_code,
            400,
        )

        # List and delete saved field plans
        list_res = self.client.get("/api/field-plans")
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(len(list_res.get_json()["plans"]), len(expected))

        del_res = self.client.delete(f"/api/field-plans/{created_ids[0]}")
        self.assertEqual(del_res.status_code, 200)
        self.assertEqual(self.client.delete(f"/api/field-plans/{created_ids[0]}").status_code, 404)

    def test_single_sensor_check_one_at_a_time(self):
        dash_res = self.client.get("/dashboard")
        self.assertEqual(dash_res.status_code, 200)
        html = dash_res.get_data(as_text=True)
        for sensor_key in ["dht22_temp", "dht22_humidity", "mq135", "soil_moisture", "soil_ph", "npk"]:
            self.assertIn(f'data-sensor-check="{sensor_key}"', html)

        # Simulated check returns only the requested sensor's fields
        expected_fields = {
            "dht22_temp": {"temperature"},
            "dht22_humidity": {"humidity"},
            "mq135": {"air_quality"},
            "soil_moisture": {"moisture", "raw_moisture_adc"},
            "soil_ph": {"ph"},
            "npk": {"nitrogen", "phosphorus", "potassium"},
        }
        for key, fields in expected_fields.items():
            res = self.client.post("/api/sensor-check", json={"sensor": key})
            self.assertEqual(res.status_code, 200)
            body = res.get_json()
            self.assertEqual(body["sensor"], key)
            self.assertEqual(set(body["values"].keys()), fields)

        # Hardware telemetry should surface per-sensor with source == "hardware"
        self.client.post(
            "/api/sensor-data",
            json={
                "device_id": self.device_id,
                "raw_moisture_adc": 2250,
                "temperature": 24.3,
                "humidity": 71.2,
                "air_quality": 44.0,
                "ph": 6.4,
                "nitrogen": 88.0,
                "phosphorus": 46.0,
                "potassium": 52.0,
            },
        )
        hw_res = self.client.get("/api/sensor-check?sensor=dht22_temp")
        self.assertEqual(hw_res.status_code, 200)
        hw_body = hw_res.get_json()
        self.assertEqual(hw_body["source"], "hardware")
        self.assertEqual(hw_body["values"], {"temperature": 24.3})

        # Invalid sensor key rejected
        bad_res = self.client.post("/api/sensor-check", json={"sensor": "unknown_sensor"})
        self.assertEqual(bad_res.status_code, 400)
        self.assertIn("supported_sensors", bad_res.get_json())

    def test_sequential_multi_node_collection_and_edge_cases(self):
        # 1. Default sample field auto-provisions 5 nodes (AGRI-001..AGRI-005)
        fields_res = self.client.get("/api/fields")
        self.assertEqual(fields_res.status_code, 200)
        fields = fields_res.get_json()["fields"]
        self.assertEqual(len(fields), 1)
        field_id = fields[0]["id"]

        nodes_res = self.client.get(f"/api/fields/{field_id}/nodes")
        self.assertEqual(nodes_res.status_code, 200)
        nodes = nodes_res.get_json()["nodes"]
        self.assertEqual([n["node_id"] for n in nodes], ["AGRI-001", "AGRI-002", "AGRI-003", "AGRI-004", "AGRI-005"])

        # 2. Dynamic scaling > 5 nodes (8 nodes on the field)
        sync_res = self.client.post(f"/api/fields/{field_id}/nodes", json={"sync_count": 8})
        self.assertEqual(sync_res.status_code, 200)
        self.assertEqual(len(sync_res.get_json()["nodes"]), 8)

        # 3. Hardware telemetry ingest with missing NPK/pH (must stay None, never 0)
        p1 = self.client.post(
            "/api/sensor-data",
            json={
                "node_id": "AGRI-001",
                "moisture": 62.0,
                "temperature": 28.0,
                "humidity": 72.0,
                "mq135": 120.0,
            },
        )
        self.assertEqual(p1.status_code, 200)
        self.assertIsNone(p1.get_json()["reading"]["nitrogen"])
        self.assertIsNone(p1.get_json()["reading"]["ph"])

        # 4. AGRI-002 posts full reading including low moisture (triggers zone attention)
        self.client.post(
            "/api/sensor-data",
            json={
                "node_id": "AGRI-002",
                "moisture": 28.0,
                "temperature": 29.0,
                "humidity": 68.0,
                "nitrogen": 85.0,
                "phosphorus": 45.0,
                "potassium": 50.0,
                "ph": 6.5,
                "mq135": 110.0,
            },
        )

        # 5. AGRI-003 posts stale telemetry (>300s old)
        from datetime import datetime, timedelta
        stale_ts = (datetime.now() - timedelta(seconds=600)).isoformat(timespec="seconds")
        self.client.post(
            "/api/sensor-data",
            json={
                "node_id": "AGRI-003",
                "moisture": 55.0,
                "temperature": 27.0,
                "humidity": 65.0,
                "mq135": 95.0,
                "timestamp": stale_ts,
            },
        )

        # 6. AGRI-004 posts sensor fault (sensor_ok = False)
        self.client.post(
            "/api/sensor-data",
            json={
                "node_id": "AGRI-004",
                "moisture": 50.0,
                "temperature": 26.0,
                "humidity": 60.0,
                "sensor_ok": False,
            },
        )
        # AGRI-005..AGRI-008 have no readings -> Offline

        # Sequential per-node checks
        n1 = self.client.get(f"/api/nodes/AGRI-001/latest?field_id={field_id}").get_json()
        self.assertEqual(n1["fetch_status"], "Fetched")
        self.assertEqual(n1["reading"]["reading_source"], "hardware")
        self.assertIsNone(n1["reading"]["nitrogen"])

        n3 = self.client.get(f"/api/nodes/AGRI-003/latest?field_id={field_id}").get_json()
        self.assertEqual(n3["fetch_status"], "Stale Data")
        self.assertTrue(n3["is_stale"])

        n4 = self.client.get(f"/api/nodes/AGRI-004/latest?field_id={field_id}").get_json()
        self.assertEqual(n4["fetch_status"], "Failed")

        n5 = self.client.get(f"/api/nodes/AGRI-005/latest?field_id={field_id}").get_json()
        self.assertEqual(n5["fetch_status"], "Offline")
        self.assertIsNone(n5["reading"])

        # Node history endpoint
        hist_res = self.client.get("/api/nodes/AGRI-001/history")
        self.assertEqual(hist_res.status_code, 200)
        self.assertEqual(len(hist_res.get_json()["history"]), 1)

        # Simulation mode clearly labeled simulated
        sim_res = self.client.get(f"/api/nodes/AGRI-005/latest?field_id={field_id}&simulate=1").get_json()
        self.assertEqual(sim_res["fetch_status"], "Fetched")
        self.assertEqual(sim_res["reading"]["reading_source"], "simulated")

        # Combined field summary aggregates valid readings only and captures spread & attention
        sum_res = self.client.get(f"/api/fields/{field_id}/summary")
        self.assertEqual(sum_res.status_code, 200)
        summary = sum_res.get_json()["summary"]
        self.assertEqual(summary["total_nodes"], 8)
        self.assertEqual(summary["nodes_fetched"], 2)  # AGRI-001, AGRI-002
        self.assertEqual(summary["nodes_stale"], 1)    # AGRI-003
        # Valid moisture across AGRI-001 (62), AGRI-002 (28), AGRI-003 (55) -> avg = 48.33, spread = 34.0
        self.assertAlmostEqual(summary["averages"]["moisture"], 48.33, places=2)
        self.assertAlmostEqual(summary["moisture_differences"]["spread_pct"], 34.0, places=2)
        # Missing pH on AGRI-001 & AGRI-003 excluded: average pH uses only AGRI-002 (6.5)
        self.assertAlmostEqual(summary["averages"]["ph"], 6.5, places=2)

    def test_existing_crop_recommend_and_auth_preserved(self):
        rec_res = self.client.get("/api/recommend")
        self.assertEqual(rec_res.status_code, 200)
        self.assertGreater(len(rec_res.get_json()["recommendations"]), 0)

        an_res = self.client.post(
            "/api/analyze",
            json={"nitrogen": 90, "phosphorus": 42, "potassium": 43, "temperature": 21, "humidity": 82, "ph": 6.5},
        )
        self.assertEqual(an_res.status_code, 200)
        self.assertEqual(an_res.get_json()["recommendations"][0]["crop"], "rice")

        self.client.get("/logout")
        self.assertEqual(self.client.get("/api/fields").status_code, 401)
