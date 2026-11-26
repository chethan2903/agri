# AgriSense Technical Review Comments — Detailed Responses & Updated Project Specifications

This document provides complete, point-by-point technical responses and implementation details addressing **Review Comments 1 (Items 1–7)** and **Review Comments 2 (Items 1–5)** for the **AgriSense** IoT and Machine Learning Smart Agriculture platform.

> **Verification Note:** All software modules, endpoints, hyperparameters, feature importances, and test results cited below are directly implemented and verified in this repository. Items marked `[INSERT YOUR FIELD DATA]` denote physical trial measurements or private dataset records that reside outside the code repository and should be filled from your experimental logs before final submission.

---

## Part A: Point-by-Point Technical Responses

### Review Comments 1

#### 1. Dataset Size, Training Samples, and Testing Conditions (97.6% Reported Accuracy)
- **Reviewer Concern:** *The reported 97.6% accuracy is not supported by sufficient details about dataset size, training samples, and testing conditions.*
- **Detailed Response & Project Implementation:**
  - The deployed AgriSense classifier ([crop_model.pkl](file:///c:/Users/gchet/OneDrive/Desktop/agrisense/models/crop_model.pkl)) predicts **22 crop species** (`apple`, `banana`, `blackgram`, `chickpea`, `coconut`, `coffee`, `cotton`, `grapes`, `jute`, `kidneybeans`, `lentil`, `maize`, `mango`, `mothbeans`, `mungbean`, `muskmelon`, `orange`, `papaya`, `pigeonpeas`, `pomegranate`, `rice`, `watermelon`) from **6 physicochemical input features** (`N`, `P`, `K`, `temperature`, `humidity`, `ph`).
  - To make dataset partitioning, sample counts, and evaluation conditions fully auditable, we implemented [train_and_evaluate.py](file:///c:/Users/gchet/OneDrive/Desktop/agrisense/ml/train_and_evaluate.py). It enforces an explicit **stratified 80/20 train–test split** (`test_size=0.2`, `random_state=42`, `stratify=y`), logs exact `total_samples`, `train_samples`, and `test_samples`, and exports per-class precision, recall, F1-score, macro-F1, and weighted-F1 into [model_metadata.json](file:///c:/Users/gchet/OneDrive/Desktop/agrisense/models/model_metadata.json).
  - **Standard Benchmark / Expected Split Details:**
    - Total dataset size: **[VERIFY: 2,200 samples across 22 balanced classes (100 samples/class), or INSERT YOUR EXACT SAMPLE COUNT]**
    - Training partition (80% stratified): **[1,760 samples]**
    - Hold-out test partition (20% stratified): **[440 samples]**
    - Testing conditions: Strictly isolated hold-out test split evaluated after cross-validated tuning on the training split only, complemented by live/simulated node scenario testing across `[INSERT AMBIENT TEMP/HUMIDITY/SOIL RANGE]`.

---

#### 2. Limited Trial Sites (Eight Sites) Across Soil Types & Agricultural Conditions
- **Reviewer Concern:** *The system was tested at only eight trial sites, which is insufficient to prove its reliability across different soil types and agricultural conditions.*
- **Detailed Response & Project Implementation:**
  - We acknowledge that evaluation across **eight trial sites** establishes initial feasibility rather than universal agro-climatic generalization. This scope limitation is now stated explicitly in the manuscript and Conclusion.
  - To mitigate cross-soil dielectric variance in software, [app.py](file:///c:/Users/gchet/OneDrive/Desktop/agrisense/backend/app.py#L46-L52) introduces configurable **soil-texture compensation factors** (`SOIL_TEXTURE_FACTORS`: `sand: 1.04`, `loam: 1.00`, `silt: 0.98`, `clay: 0.94`, `peat: 0.92`) stored per device/plot in SQLite (`sensor_calibrations`) and configurable via `/api/calibration` and the **Profile** page.
  - Additionally, the new **Field Coverage Planner** and **Sequential Multi-Node Collection** system (`/field-coverage`, `sensor_nodes` table, `AGRI-001`..`AGRI-00N`) enables scalable multi-zone monitoring (`GET /api/fields/<id>/summary`) to compare spatial moisture spread across field zones.
  - **Recommended Manuscript Table (Fill with Field Records):**

| Site ID | Soil Texture | pH Range | Climate / Season | Crop Tested | Duration | Valid Packet Rate (%) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Site 1–8 | `[INSERT YOUR FIELD DATA]` | `[INSERT]` | `[INSERT]` | `[INSERT]` | `[INSERT]` | `[INSERT]` |

---

#### 3. Long-Term Sensor Reliability and System Performance Evidence
- **Reviewer Concern:** *The study does not provide sufficient experimental evidence to demonstrate long-term sensor reliability and system performance.*
- **Detailed Response & Project Implementation:**
  - Previously, telemetry history resided only in volatile Python memory (`_user_histories`), preventing longitudinal reliability audits across server restarts.
  - [app.py](file:///c:/Users/gchet/OneDrive/Desktop/agrisense/backend/app.py) now persists every hardware packet in SQLite (`sensor_readings`, indexed on `(node_id, recorded_at)` and `(device_id, recorded_at)`), tracks `sensor_ok` physical-bounds flags, separates `hardware` vs. `simulated` readings (`reading_source`), and exposes **`GET /api/reliability`** (total persisted readings, hardware reading count, valid reading rate %, observation start/end timestamps, and distinct trial sites).
  - In [esp32_agrisense.ino](file:///c:/Users/gchet/OneDrive/Desktop/agrisense/firmware/esp32_agrisense/esp32_agrisense.ino), 5-sample median ADC filtering suppresses transient switching spikes, and DHT22 retry loops (3 attempts, 2 s interval) flag read faults (`sensor_ok: false`) rather than substituting fake defaults.
  - **Long-Term Experimental Metrics Template:** Observation window `[INSERT WEEKS/MONTHS]`, total packets logged `[INSERT]`, valid packet rate `[INSERT %]`, mean drift rate `[INSERT %/month]`.

---

#### 4. Accuracy & Calibration Procedures of Soil Moisture and DHT22 (Addressing DHT11 Mention)
- **Reviewer Concern:** *The accuracy and calibration procedures of the soil moisture and DHT11 sensors need better explanation.*
- **Detailed Response & Project Implementation:**
  - **Clarification on DHT22 vs. DHT11:** The AgriSense platform standardizes on the **DHT22 (AM2302)** rather than the DHT11 because agricultural microclimates frequently exceed 80% relative humidity (outside the DHT11's rated 20–80% RH window) and require tighter accuracy (`±0.5 °C`, `±2–5% RH`, `-40 to 80 °C` vs. DHT11's `±2.0 °C`, `±5% RH`, `0–50 °C`).
  - **Capacitive Soil Moisture v1.2 Calibration:** Uses a 5-sample median ADC reading (12-bit ESP32 ADC: `0–4095`, sensing-section insertion depth approximately **8–10 cm**) normalized via two-point dry-air (`dry_adc = 3200`) and saturated-water (`wet_adc = 1300`) baselines plus soil-texture factor $k_{\text{soil}}$:
    $$M_{\%} = \text{clamp}\!\left(\frac{ADC_{\text{dry}} - ADC_{\text{raw}}}{ADC_{\text{dry}} - ADC_{\text{wet}}} \times 100 \times k_{\text{soil}},\; 0,\; 100\right)$$
  - **Software Support:** Both two-point ADC calibration (`/api/calibration`) and reference-instrument error logging (`/api/validate-sensor` computing MAE, RMSE, max error, and mean bias) are integrated into the backend and **Profile** / **History** pages.

---

#### 5. Random Forest Model Parameters and Tuning Methods
- **Reviewer Concern:** *Random Forest model parameters and tuning methods are not clearly presented.*
- **Detailed Response & Project Implementation:**
  - Direct inspection of `models/crop_model.pkl` via [train_and_evaluate.py](file:///c:/Users/gchet/OneDrive/Desktop/agrisense/ml/train_and_evaluate.py) confirms the exact deployed hyperparameters (also exposed live at `GET /api/model-info`):
    - `n_estimators = 100`
    - `criterion = 'gini'`
    - `max_depth = None`
    - `min_samples_split = 2`
    - `min_samples_leaf = 1`
    - `max_features = 'sqrt'`
    - `bootstrap = True`
    - `random_state = 42`
  - **Inspected Feature Importances:** Humidity (`0.2605`), Potassium (`0.2199`), Phosphorus (`0.1827`), Nitrogen (`0.1373`), Temperature (`0.1169`), and pH (`0.0828`).
  - **Tuning Methodology:** [train_and_evaluate.py](file:///c:/Users/gchet/OneDrive/Desktop/agrisense/ml/train_and_evaluate.py) implements exhaustive `GridSearchCV` using 5-fold `StratifiedKFold` cross-validation strictly on the training split over `n_estimators` (`[50, 100, 150, 200]`), `criterion` (`['gini', 'entropy']`), `max_depth` (`[None, 10, 20]`), `min_samples_split` (`[2, 5]`), `min_samples_leaf` (`[1, 2]`), and `max_features` (`['sqrt', 'log2']`).

---

#### 6. Combined Conclusion & Future Work (Single Paragraph, 250–300 Words)
- **Reviewer Concern:** *It is recommended to revise the Conclusion section by combining the conclusion and future work into a single paragraph, consisting of 250–300 words.*
- **Revised Single-Paragraph Conclusion & Future Work (Verified Word Count: 250–300 Words):**

In this study, the AgriSense IoT and machine learning platform was designed, implemented, and evaluated to deliver real-time soil telemetry, automated agronomic advisories, and data-driven crop recommendations across twenty-two crop species. By integrating an ESP32 edge node equipped with a high-precision DHT22 temperature–humidity sensor, a two-point calibrated capacitive soil moisture probe, and an MQ-135 air-quality module with a Flask server running a tuned Random Forest classifier, the system bridges low-cost field sensing and actionable farm intelligence. Evaluation on a clearly defined stratified train–test split with five-fold cross-validation hyperparameter tuning demonstrated strong predictive performance across nitrogen, phosphorus, potassium, temperature, humidity, and pH inputs, while persistent SQLite telemetry logging, soil-texture compensation factors, and reference-instrument validation endpoints strengthen measurement transparency and operational reliability. From a practical agricultural perspective, real-time moisture thresholds, soil pH remediation alerts, and balanced macronutrient recommendations provide tangible field benefits by conserving irrigation water, preventing fertilizer over-application and nutrient runoff, lowering seasonal input costs, and empowering smallholder farmers to evaluate pre-planting scenarios affordably. Nevertheless, evaluating the prototype across eight trial sites remains insufficient to guarantee universal generalization across diverse soil mineralogies, regional cropping patterns, and multi-season climate variability, and short-term observations cannot fully characterize multi-year sensor drift, probe fouling, or hardware aging under harsh field conditions. Future work will therefore expand multi-regional and multi-seasonal trials across sandy, loamy, and clay soils to capture long-term sensor degradation curves, automate periodic gravimetric and thermo-hygrometer recalibration workflows, integrate inline solid-state NPK and pH sensing modules, and deploy solar-powered LoRaWAN edge nodes with automated drift-detection pipelines for scalable, autonomous precision agriculture.

---

#### 7. Minor Language & Consistency Revisions
- **Reviewer Concern:** *Some minor language mistakes should be revised.*
- **Detailed Response:**
  - Proofread [README.md](file:///c:/Users/gchet/OneDrive/Desktop/agrisense/README.md), dashboard UI text, firmware comments, and all drafted paper sections for grammar, punctuation, consistent terminology (`DHT22`, `Capacitive Soil Moisture Sensor v1.2`, `MQ-135`), and clear distinction between hardware-measured and simulated values (`reading_source`, `measured_fields`).

---

## Part B: Review Comments 2 — Detailed Responses

1. **Real-World Agricultural Benefits Discussion:**
   - **Water-Use Efficiency:** Real-time moisture thresholds (`40–85%` target window) alert growers before wilting stress and discourage over-irrigation.
   - **Balanced Fertilization & Runoff Prevention:** Crop-matched NPK compatibility and excess-nitrogen warnings (`N > 140 kg/ha`) help reduce unnecessary urea/DAP/MOP input costs and mitigate nitrate/phosphate leaching.
   - **pH Remediation:** Early acidic (`pH < 6.0`) and alkaline (`pH > 7.5`) alerts guide targeted lime or sulfur application to protect nutrient bioavailability.
   - **Affordable Multi-Zone Planning:** The **Field Coverage Planner** (configurable `5 nodes/acre` baseline) and **Sequential Multi-Node Collection** (`AGRI-001`..`AGRI-00N`) demonstrate how low-cost ESP32 nodes can map spatial variability across farm zones without expensive proprietary stations.

2. **How Many Samples Were Used for Training?**
   - Under the standard 22-crop benchmark dataset (`2,200` total samples, `100` per crop) with a stratified 80/20 split, **`1,760` samples** are allocated to training and **`440` samples** to testing. Replace `[VERIFY]` in Section A.1 if your manuscript uses a custom sample count, and re-run `python ml/train_and_evaluate.py --dataset <your_dataset.csv>` to record exact figures in [model_metadata.json](file:///c:/Users/gchet/OneDrive/Desktop/agrisense/models/model_metadata.json).

3. **DHT11 / DHT22 Measurement Accuracy Validation:**
   - Clarified the upgrade from DHT11 (`±2.0 °C`, `±5% RH`) to **DHT22** (`±0.5 °C`, `±2–5% RH`) and implemented `/api/validate-sensor` (`sensor_validations` table) to record paired sensor vs. calibrated reference thermo-hygrometer checks and compute MAE, RMSE, max error, and mean bias.

4. **Training and Testing Split Clarification:**
   - Clarified in [train_and_evaluate.py](file:///c:/Users/gchet/OneDrive/Desktop/agrisense/ml/train_and_evaluate.py): `train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)` preserves equal class proportions across all 22 crop classes; 5-fold `StratifiedKFold` `GridSearchCV` executes exclusively on `X_train, y_train`, keeping `X_test, y_test` unseen until final evaluation.

5. **Soil-Moisture Sensor Calibration Justification:**
   - Capacitive sensing isolates probe electrodes from wet soil, avoiding the rapid electrolytic corrosion and drift of resistive probes. Two-point air/water normalization compensates for unit-to-unit ADC variance, while soil-texture scaling (`sand`, `loam`, `silt`, `clay`, `peat`) accounts for dielectric permittivity differences across mineral textures and can be cross-checked against oven-dry gravimetric samples via `/api/validate-sensor`.

---

## Part C: Verification Summary in Repository
- Automated test suite ([test_app.py](file:///c:/Users/gchet/OneDrive/Desktop/agrisense/tests/test_app.py)): **8/8 tests passing (`OK`)**, verifying calibration/ingest persistence, reference validation MAE/RMSE, model metadata inspection, reproducible `train_and_tune` split/CV, single-sensor check (`/api/sensor-check`), Field Coverage Planner calculations, and sequential multi-node collection (`AGRI-001..AGRI-008`, missing channels preserved as `NULL`, stale/offline/fault handling).
