# AgriSense — AI-Powered Smart Agriculture & Soil Telemetry Platform

**AgriSense** is an end-to-end IoT and Machine Learning platform engineered to assist farmers, agronomists, and agricultural researchers in making data-driven crop and soil management decisions. By streaming calibrated soil and microclimate telemetry from ESP32 edge nodes to a Flask backend powered by a **Random Forest Classifier**, AgriSense delivers crop compatibility scores across 22 species, automated soil health advisories, persistent long-term sensor diagnostics, and interactive "What-If" scenario testing.

---

## 📋 Table of Contents
- [Architecture & Tech Stack](#-architecture--tech-stack)
- [Key Features](#-key-features)
- [Hardware Wiring & Sensor Justification](#-hardware-wiring--sensor-justification)
- [Sensor Calibration & Validation Protocol](#-sensor-calibration--validation-protocol)
- [ESP32 Firmware](#-esp32-firmware)
- [API Reference](#-api-reference)
- [Machine Learning Model & Reproducible Tuning](#-machine-learning-model--reproducible-tuning)
- [Real-World Agricultural Benefits](#-real-world-agricultural-benefits)
- [Quick Start Guide](#-quick-start-guide)

---

## 🛠 Architecture & Tech Stack

```
┌─────────────────────────────────────────────────────────────┐
│                 FRONTEND & VISUALIZATION                    │
│      HTML5 • Vanilla CSS3 (Glassmorphism) • Chart.js        │
└──────────────────────────────▲──────────────────────────────┘
                               │ JSON REST API
┌──────────────────────────────▼──────────────────────────────┐
│                    BACKEND WEB SERVER                       │
│            Python 3.13 • Flask • Werkzeug Auth              │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
┌──────────────▼──────────────┐┌──────────────▼───────────────┐
│    MACHINE LEARNING ENGINE  ││     DATABASE & STORAGE       │
│  Scikit-Learn (RandomForest)││   SQLite3 (agrisense.db)     │
│   Pandas • NumPy • Pickle   ││   Telemetry • Calibrations   │
└─────────────────────────────┘│   Validations • crops.json   │
                               └──────────────────────────────┘
               ▲
               │ HTTP POST /api/sensor-data
┌──────────────┴──────────────────────────────────────────────┐
│                    HARDWARE EDGE NODE                       │
│    ESP32 MCU • DHT22 • Capacitive Soil v1.2 • MQ-135        │
└─────────────────────────────────────────────────────────────┘
```

| Layer | Technology Used | Description |
| :--- | :--- | :--- |
| **Hardware & IoT Edge** | ESP-WROOM-32, DHT22 (AM2302), Capacitive Soil v1.2, MQ-135 | Real-time environmental and soil telemetry acquisition with median ADC filtering |
| **Microcontroller Firmware** | C++ (Arduino Framework), HTTPClient, ArduinoJson | Wi-Fi JSON telemetry transmission (`firmware/esp32_agrisense/esp32_agrisense.ino`) |
| **Backend API** | Python 3.13, Flask, Flask-CORS, Werkzeug | RESTful server, user authentication, calibration engine, and telemetry persistence |
| **Machine Learning** | Scikit-Learn, Pandas, NumPy, Pickle | `RandomForestClassifier` predicting 22 crop species (`ml/train_and_evaluate.py`) |
| **Database & Knowledge Base** | SQLite3 (`agrisense.db`), JSON (`data/crops.json`) | Persistent users, sensor telemetry, calibrations, reference validations, and crop profiles |
| **Frontend & UI** | HTML5, Vanilla CSS3 (Bento Grid, Glassmorphism), Chart.js, ES6 JS | Live gauges, NPK charts, long-term reliability summary, and calibration controls |

---

## ✨ Key Features

1. **Real-Time IoT Telemetry Ingestion & Persistence**: `/api/sensor-data` ingests ESP32 field telemetry, applies device-specific soil and climate calibrations, checks physical operating bounds, and persists readings in SQLite (`sensor_readings`).
2. **AI Crop Prediction Engine**: Evaluates Nitrogen ($N$), Phosphorus ($P$), Potassium ($K$), Temperature, Humidity, and pH to compute compatibility probabilities across **22 crop species**.
3. **Sensor Calibration & Reference Validation**: Built-in `/api/calibration` and `/api/validate-sensor` workflows support two-point capacitive soil calibration, soil-texture compensation, DHT22 offset tuning, and MAE/RMSE validation against reference instruments.
4. **Long-Term Reliability Diagnostics**: `/api/reliability` tracks total persisted readings, hardware vs. simulated samples, valid telemetry rates, and multi-site coverage.
5. **Automated Agronomic Advisory & 'What-If' Simulator**: Generates actionable guidance for pH remediation, irrigation timing, and balanced NPK fertilization, plus interactive pre-planting scenario analysis.

---

## ⚡ Hardware Wiring & Sensor Justification

### Pin Mapping Table

| Component | Pin | ESP32 Pin | Voltage Level | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Power Supply** | USB / 5V Adapter | **VIN (5V)** | 5.0V DC | Main power input for ESP32 & MQ-135 |
| **DHT22 (AM2302)** | VCC | **3.3V** | 3.3V DC | Digital Temperature & Humidity Sensor |
| **DHT22 (AM2302)** | GND | **GND** | 0V | Common Ground |
| **DHT22 (AM2302)** | DATA | **GPIO 4** | 3.3V Signal | Digital 1-Wire Data Pin |
| **Soil Moisture v1.2** | VCC | **3.3V** | 3.3V DC | Analog Capacitive Soil Moisture Sensor |
| **Soil Moisture v1.2** | GND | **GND** | 0V | Common Ground |
| **Soil Moisture v1.2** | AOUT | **GPIO 34** | 0–3.3V Analog | ADC1_CH6 Input Pin |
| **MQ-135 Gas Sensor** | VCC (5V) | **VIN (5V)** | 5.0V DC | **Requires 5V** for internal heater coil |
| **MQ-135 Gas Sensor** | GND | **GND** | 0V | Common Ground |
| **MQ-135 Gas Sensor** | AOUT | **GPIO 32** | 0–3.3V Analog | ADC1_CH4 Input Pin for Air Quality / Ammonia |

### Why DHT22 (AM2302) Over DHT11

AgriSense standardizes on the **DHT22 (AM2302)** rather than the lower-cost DHT11 to ensure agricultural telemetry reliability across field microclimates:

| Specification | DHT11 | DHT22 (AM2302 — Used in AgriSense) |
| :--- | :--- | :--- |
| **Temperature Range & Accuracy** | 0 to 50 °C (±2.0 °C) | -40 to 80 °C (**±0.5 °C**) |
| **Humidity Range & Accuracy** | 20–80% RH (±5% RH) | 0–100% RH (**±2–5% RH**) |
| **Resolution** | 1 °C / 1% RH | 0.1 °C / 0.1% RH |
| **Field Suitability** | Limited under high-humidity irrigation or frost | Covers full agricultural temperature and condensation-prone humidity regimes |

---

## 🧪 Sensor Calibration & Validation Protocol

1. **Capacitive Soil Moisture v1.2 Two-Point & Texture Calibration**:
   - Capacitive sensing avoids electrolytic probe corrosion inherent in resistive sensors during multi-week soil burial.
   - Each probe is calibrated in open dry air ($ADC_{\text{dry}} \approx 3200$) and water immersion to the depth mark ($ADC_{\text{wet}} \approx 1300$) using 5-sample median ADC filtering:
     $$M_{\%} = \text{clamp}\!\left(\frac{ADC_{\text{dry}} - ADC_{\text{raw}}}{ADC_{\text{dry}} - ADC_{\text{wet}}} \times 100 \times k_{\text{soil}},\; 0,\; 100\right)$$
   - Because dielectric permittivity varies with soil texture, `backend/app.py` applies configurable soil-texture factors (`sand: 1.04`, `loam: 1.00`, `silt: 0.98`, `clay: 0.94`, `peat: 0.92`) stored per device in SQLite (`sensor_calibrations`) and configurable from the **Profile** page.
2. **Reference-Instrument Validation**:
   - Temperature and relative humidity from the DHT22 are cross-checked against a calibrated reference thermo-hygrometer, and soil moisture is verified against gravimetric oven-dry soil samples ($105\,^\circ\text{C}$ for 24 hours).
   - Validation pairs are logged via `/api/validate-sensor` to compute **MAE**, **RMSE**, **maximum error**, and **mean bias** per channel, visible on the **History** page.

---

## 💻 ESP32 Firmware

Production edge firmware is stored in [esp32_agrisense.ino](file:///c:/Users/gchet/OneDrive/Desktop/agrisense/firmware/esp32_agrisense/esp32_agrisense.ino). Key improvements over basic polling sketches:
- Configures 12-bit ADC resolution (`0–4095`) and reads a **5-sample median** on GPIO 34 and GPIO 32 to suppress switching noise.
- Retries DHT22 reads up to 3 times with a 2-second interval and reports `sensor_ok: false` if invalid rather than substituting fabricated placeholder readings.
- Transmits `raw_moisture_adc`, `site_name`, and `soil_type` so server-side calibration profiles update moisture calculations without reflashing field nodes.

---

## 📡 API Reference

| Endpoint | Method | Auth | Purpose |
| :--- | :--- | :--- | :--- |
| `/api/sensor-data` | `POST` | No (device ingest) | Ingest ESP32 telemetry, apply node calibration, persist to `sensor_readings` |
| `/api/soil` | `GET` | Session | Return latest live hardware reading (within 120 s) or simulated telemetry |
| `/api/history` | `GET` | Session | Return the latest 30 persisted or session sensor records |
| `/api/recommend` | `GET` | Session | Run Random Forest prediction and agronomic advisory on latest soil state |
| `/api/analyze` | `POST` | Session | Run "What-If" ML analysis on custom NPK, temperature, humidity, and pH inputs |
| `/api/calibration` | `GET`, `POST` | Session | Fetch or update `dry_adc`, `wet_adc`, `soil_type`, `site_name`, and DHT22 offsets |
| `/api/validate-sensor` | `GET`, `POST` | Session | Log reference-instrument checks and compute MAE / RMSE / bias metrics |
| `/api/reliability` | `GET` | Session | Retrieve persisted reading counts, valid telemetry rates, and site coverage |
| `/api/model-info` | `GET` | Public | Return verified Random Forest hyperparameters and feature importances |

---

## 🧠 Machine Learning Model & Reproducible Tuning

AgriSense uses a Scikit-Learn `RandomForestClassifier` trained across **6 input features** (`['N', 'P', 'K', 'temperature', 'humidity', 'ph']`) to classify **22 crop species**:
*Apple, Banana, Blackgram, Chickpea, Coconut, Coffee, Cotton, Grapes, Jute, Kidneybeans, Lentil, Maize, Mango, Mothbeans, Mungbean, Muskmelon, Orange, Papaya, Pigeonpeas, Pomegranate, Rice, Watermelon.*

### Verified Model Parameters (`models/crop_model.pkl` & `models/model_metadata.json`)

| Parameter | Value | Description |
| :--- | :--- | :--- |
| `n_estimators` | `100` | Number of decision trees in the forest ensemble |
| `criterion` | `'gini'` | Impurity metric used for node splitting |
| `max_depth` | `None` | Nodes expand until leaves are pure or `< min_samples_split` |
| `min_samples_split` | `2` | Minimum samples required to split an internal node |
| `min_samples_leaf` | `1` | Minimum samples required at a leaf node |
| `max_features` | `'sqrt'` | Features considered at each split ($\sqrt{6} \approx 2$) |
| `bootstrap` | `True` | Bootstrap sampling enabled for tree diversity |
| `random_state` | `42` | Fixed seed for deterministic reproducibility |

**Inspected Feature Importances**: Humidity (`0.2605`), Potassium (`0.2199`), Phosphorus (`0.1827`), Nitrogen (`0.1373`), Temperature (`0.1169`), and pH (`0.0828`).

### Reproducible Split & Hyperparameter Tuning

Use [train_and_evaluate.py](file:///c:/Users/gchet/OneDrive/Desktop/agrisense/ml/train_and_evaluate.py) to reproduce stratified 80/20 splitting, 5-fold `StratifiedKFold` `GridSearchCV` hyperparameter tuning (strictly on the training partition), and test-set evaluation:

```bash
# Inspect existing model artifact and export verified metadata
python ml/train_and_evaluate.py --inspect-existing

# Train, tune with 5-fold StratifiedKFold GridSearchCV, and evaluate on 80/20 split
python ml/train_and_evaluate.py --dataset path/to/crop_dataset.csv --test-size 0.2 --cv 5
```

---

## 🌱 Real-World Agricultural Benefits

- **Water Conservation**: Continuous soil-moisture thresholds prevent unnecessary irrigation when moisture remains adequate and alert growers before drought stress occurs.
- **Precision Nutrient Management**: NPK telemetry combined with crop-specific matching discourages blind over-fertilization, lowering input costs and mitigating nitrate/phosphate runoff.
- **Soil Health & Yield Protection**: Early detection of acidic (`pH < 6.0`) or alkaline (`pH > 7.5`) drift enables timely lime or sulfur remediation, improving nutrient bioavailability.
- **Accessible Smallholder Decision Support**: Built on commodity ESP32/DHT22 hardware and a lightweight local Flask server, reducing adoption barriers for resource-constrained farms.

---

## 🚀 Quick Start Guide

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Application
```bash
python backend/app.py
```

### 3. Run Automated Tests
```bash
python -m unittest discover -s tests -v
```

### 4. Access Dashboard
Open your browser and navigate to:
```
http://localhost:5000
```
