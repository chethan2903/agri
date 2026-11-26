import sys
import json
import random
import math
import time
import sqlite3
import hashlib
import os
import uuid
import pickle
import pandas as pd
from datetime import datetime, timedelta
from functools import wraps
from flask import (
    Flask, jsonify, render_template, request,
    redirect, url_for, session
)
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

# ── Force UTF-8 stdout on Windows ─────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, os.pardir))

app = Flask(__name__)
CORS(app)

# ── Persistent secret key (sessions survive restarts) ─────────────────────────
_KEY_FILE = os.path.join(PROJECT_ROOT, "secret.key")
if os.path.exists(_KEY_FILE):
    with open(_KEY_FILE, "rb") as _f:
        app.secret_key = _f.read()
else:
    _key = os.urandom(32)
    with open(_KEY_FILE, "wb") as _f:
        _f.write(_key)
    app.secret_key = _key

# ── Database ───────────────────────────────────────────────────────────────────
DATABASE = os.path.join(PROJECT_ROOT, "agrisense.db")
MODEL_METADATA_PATH = os.path.join(PROJECT_ROOT, "models", "model_metadata.json")

SOIL_TEXTURE_FACTORS = {
    "sand": 1.04,
    "loam": 1.00,
    "clay": 0.94,
    "silt": 0.98,
    "peat": 0.92,
}


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT    UNIQUE NOT NULL,
            password    TEXT    NOT NULL,
            farm_name   TEXT    DEFAULT 'My Farm',
            device_id   TEXT    NOT NULL,
            location    TEXT    DEFAULT 'Unknown',
            created_at  TEXT    NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sensor_calibrations (
            device_id       TEXT PRIMARY KEY,
            site_name       TEXT NOT NULL DEFAULT 'Primary Trial Plot',
            soil_type       TEXT NOT NULL DEFAULT 'loam',
            dry_adc         INTEGER NOT NULL DEFAULT 3200,
            wet_adc         INTEGER NOT NULL DEFAULT 1300,
            temp_offset     REAL NOT NULL DEFAULT 0.0,
            humidity_offset REAL NOT NULL DEFAULT 0.0,
            vwc_slope       REAL NOT NULL DEFAULT 0.45,
            vwc_intercept   REAL NOT NULL DEFAULT 0.0,
            updated_at      TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sensor_readings (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER,
            device_id        TEXT NOT NULL,
            site_name        TEXT DEFAULT 'Primary Trial Plot',
            soil_type        TEXT DEFAULT 'loam',
            raw_moisture_adc INTEGER,
            moisture         REAL NOT NULL,
            ph               REAL NOT NULL,
            nitrogen         REAL NOT NULL,
            phosphorus       REAL NOT NULL,
            potassium        REAL NOT NULL,
            temperature      REAL NOT NULL,
            humidity         REAL NOT NULL,
            air_quality      REAL DEFAULT 50.0,
            is_simulated     INTEGER NOT NULL DEFAULT 0,
            sensor_ok        INTEGER NOT NULL DEFAULT 1,
            recorded_at      TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sensor_validations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            device_id       TEXT NOT NULL,
            sensor_type     TEXT NOT NULL,
            measured_value  REAL NOT NULL,
            reference_value REAL NOT NULL,
            abs_error       REAL NOT NULL,
            soil_type       TEXT DEFAULT 'loam',
            notes           TEXT DEFAULT '',
            validated_at    TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS field_plans (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER NOT NULL,
            field_name       TEXT NOT NULL DEFAULT 'My Field',
            location_name    TEXT DEFAULT '',
            latitude         REAL,
            longitude        REAL,
            area_input       REAL NOT NULL,
            unit             TEXT NOT NULL,
            area_acres       REAL NOT NULL,
            density_per_acre REAL NOT NULL,
            estimated_nodes  INTEGER NOT NULL,
            created_at       TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sensor_nodes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id     TEXT NOT NULL,
            field_id    INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            zone_name   TEXT NOT NULL,
            node_name   TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'Pending',
            created_at  TEXT NOT NULL,
            UNIQUE(field_id, node_id),
            FOREIGN KEY (field_id) REFERENCES field_plans(id) ON DELETE CASCADE
        )
    """)

    # Safe lossless migration for sensor_readings (allow NULL for missing/unmeasured
    # channels and add node_id, mq135, reading_source, measured_fields)
    sr_cols = {
        row["name"]: dict(row) for row in conn.execute("PRAGMA table_info(sensor_readings)").fetchall()
    }
    needs_rebuild = (
        "node_id" not in sr_cols
        or "mq135" not in sr_cols
        or "reading_source" not in sr_cols
        or "measured_fields" not in sr_cols
        or sr_cols.get("moisture", {}).get("notnull", 0) == 1
        or sr_cols.get("nitrogen", {}).get("notnull", 0) == 1
    )
    if needs_rebuild:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sensor_readings_v2 (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          INTEGER,
                device_id        TEXT NOT NULL,
                node_id          TEXT,
                site_name        TEXT DEFAULT 'Primary Trial Plot',
                soil_type        TEXT DEFAULT 'loam',
                raw_moisture_adc INTEGER,
                moisture         REAL,
                ph               REAL,
                nitrogen         REAL,
                phosphorus       REAL,
                potassium        REAL,
                temperature      REAL,
                humidity         REAL,
                air_quality      REAL,
                mq135            REAL,
                reading_source   TEXT NOT NULL DEFAULT 'hardware',
                measured_fields  TEXT DEFAULT '[]',
                is_simulated     INTEGER NOT NULL DEFAULT 0,
                sensor_ok        INTEGER NOT NULL DEFAULT 1,
                recorded_at      TEXT NOT NULL
            )
        """)
        existing_cols = set(sr_cols.keys())
        node_expr = "node_id" if "node_id" in existing_cols else "NULL"
        mq_expr = "mq135" if "mq135" in existing_cols else "air_quality"
        src_expr = (
            "reading_source"
            if "reading_source" in existing_cols
            else "CASE WHEN is_simulated = 1 THEN 'simulated' ELSE 'hardware' END"
        )
        mf_expr = "measured_fields" if "measured_fields" in existing_cols else "'[]'"
        conn.execute(f"""
            INSERT INTO sensor_readings_v2 (
                id, user_id, device_id, node_id, site_name, soil_type, raw_moisture_adc,
                moisture, ph, nitrogen, phosphorus, potassium,
                temperature, humidity, air_quality, mq135, reading_source, measured_fields,
                is_simulated, sensor_ok, recorded_at
            )
            SELECT
                id, user_id, device_id, {node_expr}, site_name, soil_type, raw_moisture_adc,
                moisture, ph, nitrogen, phosphorus, potassium,
                temperature, humidity, air_quality, {mq_expr}, {src_expr}, {mf_expr},
                is_simulated, sensor_ok, recorded_at
            FROM sensor_readings
        """)
        conn.execute("DROP TABLE sensor_readings")
        conn.execute("ALTER TABLE sensor_readings_v2 RENAME TO sensor_readings")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_sensor_nodes_field_id ON sensor_nodes(field_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sensor_nodes_node_id ON sensor_nodes(node_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sensor_readings_node_id ON sensor_readings(node_id, recorded_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sensor_readings_device_id ON sensor_readings(device_id, recorded_at)")
    conn.commit()
    conn.close()


init_db()

# ── Auth decorators ────────────────────────────────────────────────────────────
def login_required(f):
    """Redirect unauthenticated users to /login."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def api_login_required(f):
    """Return 401 JSON for unauthenticated API calls."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"status": "error", "message": "Not authenticated"}), 401
        return f(*args, **kwargs)
    return decorated

def get_current_user():
    if "user_id" not in session:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    conn.close()
    return user

def short_device_id(device_id):
    return "AGR-" + device_id[:4].upper() + "-" + device_id[4:8].upper()

# ── Crop knowledge base & Models ───────────────────────────────────────────────
with open(os.path.join(PROJECT_ROOT, "data", "crops.json"), "r", encoding="utf-8") as f:
    CROPS = json.load(f)

with open(os.path.join(PROJECT_ROOT, "models", "crop_model.pkl"), "rb") as f:
    CROP_MODEL = pickle.load(f)

with open(os.path.join(PROJECT_ROOT, "models", "crop_labels.pkl"), "rb") as f:
    CROP_LABELS = pickle.load(f)

# ── Per-user in-memory sensor history ─────────────────────────────────────────
_user_histories: dict = {}   # { user_id: [reading, ...] }

def _device_phase(device_id: str) -> float:
    """Unique numeric phase offset per device (0–1000)."""
    h = hashlib.md5(device_id.encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF * 1000.0

def _simulate_reading(device_id: str, time_offset: float = 0.0) -> dict:
    """Generate realistic, device-unique sinusoidal soil sensor data."""
    t     = time.time() + time_offset
    phase = _device_phase(device_id)

    moisture    = round(55 + 20 * math.sin((t + phase) / 30)       + random.uniform(-3,   3),   1)
    ph          = round(6.5 + 0.8 * math.sin((t + phase) / 45 + 1) + random.uniform(-0.1, 0.1), 2)
    nitrogen    = round(75 + 25 * math.sin((t + phase) / 60 + 2)   + random.uniform(-5,   5),   1)
    phosphorus  = round(55 + 15 * math.sin((t + phase) / 50 + 3)   + random.uniform(-3,   3),   1)
    potassium   = round(65 + 20 * math.sin((t + phase) / 55 + 4)   + random.uniform(-4,   4),   1)
    temperature = round(26 + 6  * math.sin((t + phase) / 40 + 5)   + random.uniform(-1,   1),   1)
    humidity    = round(62 + 18 * math.sin((t + phase) / 35 + 6)   + random.uniform(-2,   2),   1)
    air_quality = round(48 + 18 * math.sin((t + phase) / 42 + 7)   + random.uniform(-4,   4),   1)

    return {
        "timestamp":   (datetime.now() + timedelta(seconds=time_offset)).strftime("%H:%M:%S"),
        "moisture":    max(10,  min(100, moisture)),
        "ph":          max(4.0, min(9.0, ph)),
        "nitrogen":    max(5,   min(200, nitrogen)),
        "phosphorus":  max(5,   min(150, phosphorus)),
        "potassium":   max(5,   min(200, potassium)),
        "temperature": max(5,   min(50,  temperature)),
        "humidity":    max(10,  min(100, humidity)),
        "air_quality": max(10,  min(500, air_quality)),
    }

def _build_history(device_id: str) -> list:
    hist = []
    for i in range(29, -1, -1):
        r = _simulate_reading(device_id, time_offset=-(i * 5))
        r["timestamp"] = (datetime.now() - timedelta(seconds=i * 5)).strftime("%H:%M:%S")
        hist.append(r)
    return hist

def get_device_calibration(device_id: str) -> dict:
    """Fetch stored calibration profile for a device, or return defaults."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM sensor_calibrations WHERE device_id = ?", (device_id,)
    ).fetchone()
    conn.close()
    if row:
        return dict(row)
    return {
        "device_id": device_id,
        "site_name": "Primary Trial Plot",
        "soil_type": "loam",
        "dry_adc": 3200,
        "wet_adc": 1300,
        "temp_offset": 0.0,
        "humidity_offset": 0.0,
        "vwc_slope": 0.45,
        "vwc_intercept": 0.0,
        "updated_at": None,
    }


def calibrate_soil_moisture(
    raw_adc: float,
    dry_adc: int = 3200,
    wet_adc: int = 1300,
    soil_type: str = "loam",
) -> float:
    """Convert raw capacitive ADC reading to calibrated moisture percentage (0-100%)."""
    span = dry_adc - wet_adc
    if span <= 0:
        return 0.0
    normalized = ((dry_adc - raw_adc) / span) * 100.0
    factor = SOIL_TEXTURE_FACTORS.get(soil_type.lower(), 1.00)
    return round(max(0.0, min(100.0, normalized * factor)), 1)


def apply_dht22_calibration(
    temperature: float,
    humidity: float,
    temp_offset: float = 0.0,
    humidity_offset: float = 0.0,
) -> tuple[float, float]:
    """Apply node-level DHT22 offset corrections and enforce physical bounds."""
    cal_temp = round(max(-40.0, min(80.0, temperature + temp_offset)), 2)
    cal_hum = round(max(0.0, min(100.0, humidity + humidity_offset)), 2)
    return cal_temp, cal_hum


def validate_reading_bounds(reading: dict) -> bool:
    """Return True if all non-null sensor values fall within physical operating ranges."""
    t = reading.get("temperature")
    h = reading.get("humidity")
    m = reading.get("moisture")
    ph = reading.get("ph")
    if t is not None and not (-40.0 <= t <= 80.0):
        return False
    if h is not None and not (0.0 <= h <= 100.0):
        return False
    if m is not None and not (0.0 <= m <= 100.0):
        return False
    if ph is not None and not (0.0 <= ph <= 14.0):
        return False
    return True


def persist_sensor_reading(
    user_id: int | None,
    device_id: str,
    reading: dict,
    is_simulated: int = 0,
    sensor_ok: int = 1,
    node_id: str | None = None,
) -> int:
    """Persist a telemetry sample to SQLite and return the inserted reading_id."""
    reading_source = reading.get("reading_source") or ("simulated" if is_simulated else "hardware")
    measured_fields = reading.get("measured_fields")
    if isinstance(measured_fields, list):
        measured_fields_json = json.dumps(measured_fields)
    elif isinstance(measured_fields, str):
        measured_fields_json = measured_fields
    else:
        measured_fields_json = json.dumps([])

    mq135_val = reading.get("mq135", reading.get("air_quality"))

    conn = get_db()
    cur = conn.execute(
        """
        INSERT INTO sensor_readings (
            user_id, device_id, node_id, site_name, soil_type, raw_moisture_adc,
            moisture, ph, nitrogen, phosphorus, potassium,
            temperature, humidity, air_quality, mq135, reading_source, measured_fields,
            is_simulated, sensor_ok, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            device_id,
            node_id or reading.get("node_id"),
            reading.get("site_name", "Primary Trial Plot"),
            reading.get("soil_type", "loam"),
            reading.get("raw_moisture_adc"),
            reading.get("moisture"),
            reading.get("ph"),
            reading.get("nitrogen"),
            reading.get("phosphorus"),
            reading.get("potassium"),
            reading.get("temperature"),
            reading.get("humidity"),
            mq135_val,
            mq135_val,
            reading_source,
            measured_fields_json,
            is_simulated,
            sensor_ok,
            reading.get("recorded_at", datetime.now().isoformat(timespec="seconds")),
        ),
    )
    reading_id = cur.lastrowid
    conn.commit()
    conn.close()
    return reading_id


def get_user_history(user_id: int, device_id: str) -> list:
    conn = get_db()
    rows = conn.execute(
        """
        SELECT moisture, ph, nitrogen, phosphorus, potassium,
               temperature, humidity, air_quality, site_name, soil_type,
               raw_moisture_adc, is_simulated, recorded_at
        FROM sensor_readings
        WHERE user_id = ? OR device_id = ?
        ORDER BY id DESC LIMIT 30
        """,
        (user_id, device_id),
    ).fetchall()
    conn.close()

    if rows:
        db_hist = []
        for row in reversed(rows):
            item = dict(row)
            item["timestamp"] = item["recorded_at"][11:19] if len(item["recorded_at"]) >= 19 else item["recorded_at"]
            db_hist.append(item)
        return db_hist

    if user_id not in _user_histories:
        _user_histories[user_id] = _build_history(device_id)
    return _user_histories[user_id]

# ── Crop scoring engine ────────────────────────────────────────────────────────
def _get_ml_recommendations(soil: dict) -> list:
    # Model features: ['N', 'P', 'K', 'temperature', 'humidity', 'ph']
    features_df = pd.DataFrame([{
        "N": soil["nitrogen"],
        "P": soil["phosphorus"],
        "K": soil["potassium"],
        "temperature": soil["temperature"],
        "humidity": soil["humidity"],
        "ph": soil["ph"]
    }])
    
    probs = CROP_MODEL.predict_proba(features_df)[0]
    
    results = []
    for label, prob in zip(CROP_LABELS, probs):
        if prob > 0:
            crop_info = next((c for c in CROPS if c["name"].lower() == label.lower()), None)
            score = round(float(prob * 100), 1)
            probability = round(float(prob), 4)
            name = crop_info["name"] if crop_info else label.capitalize()
            
            item = {
                "crop": label.lower(),
                "name": name,
                "probability": probability,
                "score": score,
                "data": {
                    "desc": crop_info["description"] if crop_info else "Recommended by AI model.",
                    "season": crop_info["season"] if crop_info else "Any",
                    "waterRequirement": crop_info["waterRequirement"] if crop_info else "Unknown",
                    "growthDuration": crop_info["growthDuration"] if crop_info else "Unknown",
                    "tags": crop_info.get("tags", []) if crop_info else []
                }
            }
            if crop_info:
                item.update(crop_info)
                item["score"] = score
                item["name"] = name
            else:
                item.update({
                    "image": "",
                    "season": "Any",
                    "description": "Recommended by AI model.",
                    "waterRequirement": "Unknown",
                    "growthDuration": "Unknown"
                })
            results.append(item)
    
    return sorted(results, key=lambda x: x["score"], reverse=True)

def _build_advisory(soil: dict, top_crops: list) -> list:
    tips = []
    ph = soil["ph"]
    if ph < 6.0:
        tips.append(f"Soil is acidic (pH {ph:.1f}). Apply agricultural lime to raise pH and improve nutrient availability.")
    elif ph > 7.5:
        tips.append(f"Soil is alkaline (pH {ph:.1f}). Add elemental sulfur or acidic compost to lower pH.")
    else:
        tips.append(f"Soil pH ({ph:.1f}) is in the ideal range for most crops — no correction needed.")

    m = soil["moisture"]
    if m < 40:
        tips.append(f"Soil moisture critically low ({m:.0f}%). Irrigate immediately to prevent crop stress.")
    elif m > 85:
        tips.append(f"Soil is waterlogged ({m:.0f}%). Improve field drainage to prevent root rot.")
    else:
        tips.append(f"Soil moisture ({m:.0f}%) is adequate for healthy plant growth.")

    if soil["nitrogen"]   < 40:
        tips.append(f"Low nitrogen ({soil['nitrogen']:.0f} kg/ha). Apply split-dose urea or ammonium nitrate to minimize leaching.")
    elif soil["nitrogen"] > 140:
        tips.append(f"High nitrogen ({soil['nitrogen']:.0f} kg/ha). Hold nitrogen fertilization to avoid nutrient runoff and groundwater contamination.")

    if soil["phosphorus"] < 30:
        tips.append(f"Phosphorus deficiency ({soil['phosphorus']:.0f} kg/ha). Apply superphosphate or DAP near the root zone.")
    if soil["potassium"]  < 30:
        tips.append(f"Low potassium ({soil['potassium']:.0f} kg/ha). Apply muriate of potash (MOP) to strengthen drought tolerance.")

    if top_crops:
        b = top_crops[0]
        tips.append(f"Best crop match: {b['name']} with {b['score']:.0f}% compatibility — ideal for {b['season']} season ({b.get('waterRequirement', 'Moderate')} water demand).")
    return tips

# ── Weather simulation ─────────────────────────────────────────────────────────
_WEATHER = [
    {"condition": "Sunny",         "icon": "sunny",  "base_temp": 30},
    {"condition": "Partly Cloudy", "icon": "partly", "base_temp": 26},
    {"condition": "Cloudy",        "icon": "cloudy", "base_temp": 22},
    {"condition": "Rainy",         "icon": "rainy",  "base_temp": 20},
    {"condition": "Thunderstorm",  "icon": "storm",  "base_temp": 18},
]

def _generate_weather() -> list:
    today = datetime.now()
    forecast, prev = [], random.randint(0, 4)
    for i in range(7):
        idx  = max(0, min(4, prev + random.randint(-1, 1)))
        prev = idx
        c    = _WEATHER[idx]
        high = c["base_temp"] + random.randint(-3, 5)
        low  = high - random.randint(5, 10)
        forecast.append({
            "day":       (today + timedelta(days=i)).strftime("%a %d"),
            "condition": c["condition"],
            "icon":      c["icon"],
            "high":      high,
            "low":       low,
            "humidity":  random.randint(40, 90),
            "rain_prob": int(random.uniform(
                0, 75 if c["condition"] in ["Rainy", "Thunderstorm"] else 20
            )),
        })
    return forecast

# ══════════════════════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], password):
            session.permanent = True
            session["user_id"]    = user["id"]
            session["username"]   = user["username"]
            session["farm_name"]  = user["farm_name"]
            session["device_id"]  = user["device_id"]
            session["location"]   = user["location"]
            return redirect(url_for("index"))
        error = "Invalid username or password. Please try again."
    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username  = request.form.get("username",  "").strip()
        password  = request.form.get("password",  "")
        confirm   = request.form.get("confirm",   "")
        farm_name = request.form.get("farm_name", "My Farm").strip() or "My Farm"
        location  = request.form.get("location",  "Unknown").strip() or "Unknown"

        if not username or not password:
            error = "Username and password are required."
        elif password != confirm:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters long."
        else:
            device_id = str(uuid.uuid4())
            try:
                conn = get_db()
                conn.execute(
                    "INSERT INTO users (username, password, farm_name, device_id, location, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (username, generate_password_hash(password),
                     farm_name, device_id, location, datetime.now().isoformat())
                )
                conn.commit()
                conn.close()
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                error = "Username already taken — please choose another."
    return render_template("register.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE ROUTES  (multi-page sidebar layout)
# ══════════════════════════════════════════════════════════════════════════════

def _base_ctx(user):
    """Common template context injected into every page."""
    return dict(
        username     = user["username"],
        farm_name    = user["farm_name"],
        device_id    = user["device_id"],
        short_device = short_device_id(user["device_id"]),
        location     = user["location"],
    )

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")

@app.route("/dashboard")
@login_required
def dashboard():
    user = get_current_user()
    return render_template("dashboard.html", active_page="dashboard", **_base_ctx(user))

@app.route("/analyze")
@login_required
def analyze():
    user = get_current_user()
    return render_template("analyze.html", active_page="analyze", **_base_ctx(user))

@app.route("/crops")
@login_required
def crops():
    user = get_current_user()
    return render_template("crops.html", active_page="crops", **_base_ctx(user))

@app.route("/history")
@login_required
def history():
    user = get_current_user()
    return render_template("history.html", active_page="history", **_base_ctx(user))

@app.route("/weather")
@login_required
def weather():
    user = get_current_user()
    return render_template("weather.html", active_page="weather", **_base_ctx(user))

@app.route("/field-coverage")
@login_required
def field_coverage():
    user = get_current_user()
    return render_template("field_coverage.html", active_page="field_coverage", **_base_ctx(user))

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user    = get_current_user()
    success = None
    error   = None

    if request.method == "POST":
        farm_name        = request.form.get("farm_name",        "").strip() or user["farm_name"]
        location         = request.form.get("location",         "").strip() or user["location"]
        current_password = request.form.get("current_password", "")
        new_password     = request.form.get("new_password",     "")
        confirm_password = request.form.get("confirm_password", "")

        conn = get_db()

        # Password change (optional)
        if new_password:
            if not check_password_hash(user["password"], current_password):
                error = "Current password is incorrect."
            elif new_password != confirm_password:
                error = "New passwords do not match."
            elif len(new_password) < 6:
                error = "Password must be at least 6 characters."
            else:
                conn.execute(
                    "UPDATE users SET farm_name=?, location=?, password=? WHERE id=?",
                    (farm_name, location, generate_password_hash(new_password), user["id"])
                )
                conn.commit()
                session["farm_name"] = farm_name
                session["location"]  = location
                success = "Profile and password updated successfully."
        else:
            conn.execute(
                "UPDATE users SET farm_name=?, location=? WHERE id=?",
                (farm_name, location, user["id"])
            )
            conn.commit()
            session["farm_name"] = farm_name
            session["location"]  = location
            success = "Profile updated successfully."

        conn.close()
        user = get_current_user()  # re-fetch updated user

    created_at = user["created_at"][:10] if user["created_at"] else "—"
    return render_template(
        "profile.html",
        active_page = "profile",
        success     = success,
        error       = error,
        created_at  = created_at,
        **_base_ctx(user),
    )

# ══════════════════════════════════════════════════════════════════════════════
#  API ROUTES  (all require login except hardware telemetry ingest)
# ══════════════════════════════════════════════════════════════════════════════

def _opt_float(val):
    """Parse optional float, returning None when omitted or null (never 0)."""
    if val is None or val == "":
        return None
    f = float(val)
    if not math.isfinite(f):
        raise ValueError("Non-finite numeric value")
    return f


@app.route("/api/sensor-data", methods=["POST"])
def api_sensor_data():
    """Ingest live hardware telemetry from ESP32/Arduino/Raspberry Pi nodes."""
    data = request.get_json(force=True, silent=True) or {}
    node_id = str(data.get("node_id")).strip() if data.get("node_id") else None
    device_id = str(data.get("device_id") or node_id or "").strip()

    if not device_id and not node_id:
        return jsonify({"status": "error", "message": "Missing device_id or node_id"}), 400

    cal = get_device_calibration(node_id or device_id)
    soil_type = str(data.get("soil_type") or cal["soil_type"] or "loam").lower()
    site_name = str(data.get("site_name") or cal["site_name"] or "Primary Trial Plot")
    raw_adc = data.get("raw_moisture_adc")

    try:
        if raw_adc is not None and raw_adc != "":
            raw_adc_int = int(raw_adc)
            moisture = calibrate_soil_moisture(
                raw_adc_int,
                dry_adc=int(cal["dry_adc"]),
                wet_adc=int(cal["wet_adc"]),
                soil_type=soil_type,
            )
        else:
            raw_adc_int = None
            moisture = _opt_float(data.get("moisture"))

        raw_temp = _opt_float(data.get("temperature"))
        raw_hum = _opt_float(data.get("humidity"))
        if raw_temp is not None and raw_hum is not None:
            cal_temp, cal_hum = apply_dht22_calibration(
                raw_temp,
                raw_hum,
                temp_offset=float(cal["temp_offset"]),
                humidity_offset=float(cal["humidity_offset"]),
            )
        else:
            cal_temp = (
                round(max(-40.0, min(80.0, raw_temp + float(cal["temp_offset"]))), 2)
                if raw_temp is not None else None
            )
            cal_hum = (
                round(max(0.0, min(100.0, raw_hum + float(cal["humidity_offset"]))), 2)
                if raw_hum is not None else None
            )

        mq135_val = _opt_float(data.get("mq135", data.get("air_quality")))
        ph_val = _opt_float(data.get("ph"))
        n_val = _opt_float(data.get("nitrogen"))
        p_val = _opt_float(data.get("phosphorus"))
        k_val = _opt_float(data.get("potassium"))

        explicit_measured = data.get("measured_fields")
        if isinstance(explicit_measured, list):
            measured_fields = [str(x) for x in explicit_measured]
        else:
            measured_fields = []
            for key, val in [
                ("moisture", moisture),
                ("temperature", cal_temp),
                ("humidity", cal_hum),
                ("mq135", mq135_val),
                ("ph", ph_val),
                ("nitrogen", n_val),
                ("phosphorus", p_val),
                ("potassium", k_val),
            ]:
                if val is not None:
                    measured_fields.append(key)

        now = datetime.now()
        reading = {
            "timestamp":        now.strftime("%H:%M:%S"),
            "recorded_at":      data.get("timestamp") or now.isoformat(timespec="seconds"),
            "node_id":          node_id,
            "site_name":        site_name,
            "soil_type":        soil_type,
            "raw_moisture_adc": raw_adc_int,
            "moisture":         moisture,
            "ph":               ph_val,
            "nitrogen":         n_val,
            "phosphorus":       p_val,
            "potassium":        k_val,
            "temperature":      cal_temp,
            "humidity":         cal_hum,
            "air_quality":      mq135_val,
            "mq135":            mq135_val,
            "reading_source":   "hardware",
            "measured_fields":  measured_fields,
        }
    except (ValueError, TypeError) as e:
        return jsonify({"status": "error", "message": f"Invalid sensor payload: {e}"}), 400

    sensor_ok = 1 if (bool(data.get("sensor_ok", True)) and validate_reading_bounds(reading)) else 0

    conn = get_db()
    uid = None
    if node_id:
        node_row = conn.execute(
            "SELECT user_id FROM sensor_nodes WHERE node_id = ? ORDER BY id DESC LIMIT 1",
            (node_id,),
        ).fetchone()
        if node_row:
            uid = node_row["user_id"]
            conn.execute(
                "UPDATE sensor_nodes SET status = ? WHERE node_id = ?",
                ("Fetched" if sensor_ok else "Failed", node_id),
            )
            conn.commit()
    if uid is None and device_id:
        user = conn.execute("SELECT id FROM users WHERE device_id = ?", (device_id,)).fetchone()
        if user:
            uid = user["id"]
    conn.close()

    reading_id = persist_sensor_reading(
        uid, device_id, reading, is_simulated=0, sensor_ok=sensor_ok, node_id=node_id
    )
    reading["reading_id"] = reading_id

    if uid is not None and not node_id:
        if uid not in _user_histories:
            _user_histories[uid] = []
        _user_histories[uid].append(reading)
        if len(_user_histories[uid]) > 50:
            _user_histories[uid].pop(0)

    return jsonify({
        "status": "ok",
        "message": "Telemetry received and calibrated successfully",
        "reading_id": reading_id,
        "sensor_ok": bool(sensor_ok),
        "calibration_applied": {
            "soil_type": soil_type,
            "dry_adc": cal["dry_adc"],
            "wet_adc": cal["wet_adc"],
        },
        "reading": reading,
    })


def _get_latest_or_simulated_reading(uid: int, device_id: str) -> tuple[dict, str]:
    """Return latest live hardware reading within 120s, or a simulated reading."""
    conn = get_db()
    latest_hw = conn.execute(
        """
        SELECT moisture, ph, nitrogen, phosphorus, potassium,
               temperature, humidity, air_quality, site_name, soil_type,
               raw_moisture_adc, recorded_at
        FROM sensor_readings
        WHERE (user_id = ? OR device_id = ?) AND is_simulated = 0
        ORDER BY id DESC LIMIT 1
        """,
        (uid, device_id),
    ).fetchone()
    conn.close()

    if latest_hw:
        try:
            age = (datetime.now() - datetime.fromisoformat(latest_hw["recorded_at"])).total_seconds()
            if age <= 120:
                reading = dict(latest_hw)
                reading["timestamp"] = reading["recorded_at"][11:19]
                reading["source"] = "hardware"
                return reading, "hardware"
        except ValueError:
            pass

    reading = _simulate_reading(device_id)
    reading["source"] = "simulated"
    return reading, "simulated"


def _eval_dht22_temp(reading: dict) -> tuple[str, str]:
    t = reading["temperature"]
    if t < 10:
        return "Low", "Ambient temperature is cool; monitor frost-sensitive seedlings."
    if t > 38:
        return "High", "High ambient temperature; watch for evapotranspiration stress."
    return "Normal", "Ambient temperature is within typical agricultural operating range."


def _eval_dht22_humidity(reading: dict) -> tuple[str, str]:
    h = reading["humidity"]
    if h < 30:
        return "Low", "Low relative humidity; evaporative water loss may accelerate."
    if h > 85:
        return "High", "High humidity; monitor foliage for fungal disease risk."
    return "Optimal", "Relative humidity is within healthy crop microclimate limits."


def _eval_mq135(reading: dict) -> tuple[str, str]:
    aqi = reading.get("air_quality", 50.0)
    if aqi > 200:
        return "Elevated", "Elevated gas/ammonia response detected near the MQ-135 module."
    return "Clean", "Air quality response is within normal ambient baseline (< 200 PPM)."


def _eval_soil_moisture(reading: dict) -> tuple[str, str]:
    m = reading["moisture"]
    if m < 40:
        return "Low", "Localized soil moisture is low (< 40%); irrigation recommended."
    if m > 85:
        return "Saturated", "Soil moisture is high (> 85%); check field drainage."
    return "Optimal", "Localized probe moisture is in healthy range (40-85%)."


def _eval_soil_ph(reading: dict) -> tuple[str, str]:
    ph = reading["ph"]
    if ph < 6.0:
        return "Acidic", "Soil is acidic (pH < 6.0); consider agricultural lime."
    if ph > 7.5:
        return "Alkaline", "Soil is alkaline (pH > 7.5); consider elemental sulfur."
    return "Optimal", "Soil pH is in the ideal 6.0-7.5 range for nutrient uptake."


def _eval_npk(reading: dict) -> tuple[str, str]:
    low = []
    if reading["nitrogen"] < 40:
        low.append("N")
    if reading["phosphorus"] < 30:
        low.append("P")
    if reading["potassium"] < 30:
        low.append("K")
    if low:
        return "Deficient", f"Low macronutrient level detected for: {', '.join(low)}."
    return "Balanced", "Macronutrient (N, P, K) levels are adequate."


SENSOR_CHECK_SPECS = {
    "dht22_temp": {
        "label": "Temperature Sensor",
        "hardware": "DHT22 (AM2302)",
        "unit": "°C",
        "fields": ["temperature"],
        "evaluator": _eval_dht22_temp,
    },
    "dht22_humidity": {
        "label": "Humidity Sensor",
        "hardware": "DHT22 (AM2302)",
        "unit": "% RH",
        "fields": ["humidity"],
        "evaluator": _eval_dht22_humidity,
    },
    "mq135": {
        "label": "Air Quality Sensor",
        "hardware": "MQ-135 Gas Sensor",
        "unit": "PPM",
        "fields": ["air_quality"],
        "evaluator": _eval_mq135,
    },
    "soil_moisture": {
        "label": "Soil Moisture Sensor",
        "hardware": "Capacitive Soil Moisture v1.2",
        "unit": "%",
        "fields": ["moisture", "raw_moisture_adc"],
        "evaluator": _eval_soil_moisture,
    },
    "soil_ph": {
        "label": "Soil pH Sensor",
        "hardware": "Soil pH Probe",
        "unit": "pH",
        "fields": ["ph"],
        "evaluator": _eval_soil_ph,
    },
    "npk": {
        "label": "Soil Macronutrients (NPK) Sensor",
        "hardware": "NPK Soil Sensor",
        "unit": "kg/ha",
        "fields": ["nitrogen", "phosphorus", "potassium"],
        "evaluator": _eval_npk,
    },
}


@app.route("/api/soil")
@api_login_required
def api_soil():
    uid = session["user_id"]
    device_id = session["device_id"]
    reading, source = _get_latest_or_simulated_reading(uid, device_id)
    if source == "simulated":
        if uid not in _user_histories:
            _user_histories[uid] = _build_history(device_id)
        _user_histories[uid].append(reading)
        if len(_user_histories[uid]) > 50:
            _user_histories[uid].pop(0)
    return jsonify({"status": "ok", "data": reading})


@app.route("/api/sensor-check", methods=["GET", "POST"])
@api_login_required
def api_sensor_check():
    """Measure or check a single sensor channel at a time without polling all sensors."""
    uid = session["user_id"]
    device_id = session["device_id"]

    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        sensor_key = str(data.get("sensor", "")).strip()
    else:
        sensor_key = str(request.args.get("sensor", "")).strip()

    if sensor_key not in SENSOR_CHECK_SPECS:
        return jsonify({
            "status": "error",
            "message": f"Unknown sensor '{sensor_key}'. Choose one sensor at a time.",
            "supported_sensors": list(SENSOR_CHECK_SPECS.keys()),
        }), 400

    spec = SENSOR_CHECK_SPECS[sensor_key]
    reading, source = _get_latest_or_simulated_reading(uid, device_id)
    values = {field: reading.get(field) for field in spec["fields"]}
    condition, note = spec["evaluator"](reading)

    return jsonify({
        "status": "ok",
        "sensor": sensor_key,
        "label": spec["label"],
        "hardware": spec["hardware"],
        "unit": spec["unit"],
        "values": values,
        "condition": condition,
        "note": note,
        "source": source,
        "checked_at": reading.get("timestamp") or datetime.now().strftime("%H:%M:%S"),
    })


@app.route("/api/history")
@api_login_required
def api_history():
    hist = get_user_history(session["user_id"], session["device_id"])
    return jsonify({"status": "ok", "data": hist[-30:]})


@app.route("/api/recommend")
@api_login_required
def api_recommend():
    hist = get_user_history(session["user_id"], session["device_id"])
    soil = hist[-1] if hist else _simulate_reading(session["device_id"])
    
    scored = _get_ml_recommendations(soil)
    top = scored[:6]
    return jsonify({
        "status": "ok",
        "recommendations": top,
        "advisory":        _build_advisory(soil, top),
        "soil":            soil,
    })


@app.route("/api/analyze", methods=["POST"])
@api_login_required
def api_analyze():
    data = request.get_json(force=True)
    try:
        soil = {
            "timestamp":   datetime.now().strftime("%H:%M:%S"),
            "moisture":    float(data.get("moisture",    60)),
            "ph":          float(data.get("ph",          6.5)),
            "nitrogen":    float(data.get("nitrogen",    80)),
            "phosphorus":  float(data.get("phosphorus",  55)),
            "potassium":   float(data.get("potassium",   60)),
            "temperature": float(data.get("temperature", 25)),
            "humidity":    float(data.get("humidity",    65)),
        }
    except (ValueError, TypeError) as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    scored = _get_ml_recommendations(soil)
    top = scored[:6]
    return jsonify({
        "status": "ok",
        "recommendations": top,
        "advisory":        _build_advisory(soil, top),
        "soil":            soil,
    })


@app.route("/api/weather")
@api_login_required
def api_weather():
    return jsonify({"status": "ok", "forecast": _generate_weather()})


@app.route("/api/user")
@api_login_required
def api_user():
    user = get_current_user()
    return jsonify({
        "status":       "ok",
        "username":     user["username"],
        "farm_name":    user["farm_name"],
        "device_id":    user["device_id"],
        "short_device": short_device_id(user["device_id"]),
        "location":     user["location"],
    })


@app.route("/api/calibration", methods=["GET", "POST"])
@api_login_required
def api_calibration():
    """Retrieve or update soil-moisture and DHT22 calibration settings for the user's node."""
    device_id = session["device_id"]
    if request.method == "GET":
        return jsonify({
            "status": "ok",
            "calibration": get_device_calibration(device_id),
            "supported_soil_types": list(SOIL_TEXTURE_FACTORS.keys()),
        })

    data = request.get_json(force=True, silent=True) or {}
    try:
        dry_adc = int(data.get("dry_adc", 3200))
        wet_adc = int(data.get("wet_adc", 1300))
        temp_offset = float(data.get("temp_offset", 0.0))
        humidity_offset = float(data.get("humidity_offset", 0.0))
        vwc_slope = float(data.get("vwc_slope", 0.45))
        vwc_intercept = float(data.get("vwc_intercept", 0.0))
    except (ValueError, TypeError) as e:
        return jsonify({"status": "error", "message": f"Invalid numeric parameter: {e}"}), 400

    if dry_adc <= wet_adc:
        return jsonify({"status": "error", "message": "dry_adc must be greater than wet_adc"}), 400

    soil_type = str(data.get("soil_type", "loam")).strip().lower()
    if soil_type not in SOIL_TEXTURE_FACTORS:
        return jsonify({"status": "error", "message": f"Unsupported soil_type: {soil_type}"}), 400

    site_name = str(data.get("site_name", "Primary Trial Plot")).strip() or "Primary Trial Plot"
    updated_at = datetime.now().isoformat(timespec="seconds")

    conn = get_db()
    conn.execute(
        """
        INSERT INTO sensor_calibrations (
            device_id, site_name, soil_type, dry_adc, wet_adc,
            temp_offset, humidity_offset, vwc_slope, vwc_intercept, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            site_name=excluded.site_name,
            soil_type=excluded.soil_type,
            dry_adc=excluded.dry_adc,
            wet_adc=excluded.wet_adc,
            temp_offset=excluded.temp_offset,
            humidity_offset=excluded.humidity_offset,
            vwc_slope=excluded.vwc_slope,
            vwc_intercept=excluded.vwc_intercept,
            updated_at=excluded.updated_at
        """,
        (
            device_id, site_name, soil_type, dry_adc, wet_adc,
            temp_offset, humidity_offset, vwc_slope, vwc_intercept, updated_at,
        ),
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "calibration": get_device_calibration(device_id)})


@app.route("/api/validate-sensor", methods=["GET", "POST"])
@api_login_required
def api_validate_sensor():
    """Log or inspect reference-instrument validation runs (DHT22 & capacitive soil sensor)."""
    uid = session["user_id"]
    device_id = session["device_id"]
    allowed_sensors = {"dht22_temp", "dht22_humidity", "soil_moisture"}

    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        sensor_type = str(data.get("sensor_type", "")).strip()
        if sensor_type not in allowed_sensors:
            return jsonify({"status": "error", "message": "Invalid sensor_type"}), 400
        try:
            measured = float(data["measured_value"])
            reference = float(data["reference_value"])
        except (KeyError, ValueError, TypeError):
            return jsonify({"status": "error", "message": "measured_value and reference_value are required"}), 400

        abs_error = round(abs(measured - reference), 3)
        soil_type = str(data.get("soil_type", "loam")).strip().lower()
        notes = str(data.get("notes", "")).strip()[:200]
        validated_at = datetime.now().isoformat(timespec="seconds")

        conn = get_db()
        conn.execute(
            """
            INSERT INTO sensor_validations (
                user_id, device_id, sensor_type, measured_value,
                reference_value, abs_error, soil_type, notes, validated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uid, device_id, sensor_type, measured, reference, abs_error, soil_type, notes, validated_at),
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "ok", "abs_error": abs_error, "validated_at": validated_at})

    conn = get_db()
    rows = conn.execute(
        """
        SELECT sensor_type, measured_value, reference_value, abs_error, soil_type, notes, validated_at
        FROM sensor_validations
        WHERE user_id = ? OR device_id = ?
        ORDER BY id DESC LIMIT 50
        """,
        (uid, device_id),
    ).fetchall()
    conn.close()

    records = [dict(r) for r in rows]
    summary = {}
    for stype in sorted(allowed_sensors):
        subset = [r for r in records if r["sensor_type"] == stype]
        if subset:
            errs = [r["abs_error"] for r in subset]
            biases = [r["measured_value"] - r["reference_value"] for r in subset]
            rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
            summary[stype] = {
                "count": len(subset),
                "mae": round(sum(errs) / len(errs), 3),
                "rmse": round(rmse, 3),
                "max_error": round(max(errs), 3),
                "mean_bias": round(sum(biases) / len(biases), 3),
            }
        else:
            summary[stype] = {"count": 0, "mae": None, "rmse": None, "max_error": None, "mean_bias": None}

    return jsonify({"status": "ok", "summary": summary, "records": records})


@app.route("/api/reliability")
@api_login_required
def api_reliability():
    """Return persistent telemetry reliability metrics across logged readings."""
    uid = session["user_id"]
    device_id = session["device_id"]
    conn = get_db()
    stats = conn.execute(
        """
        SELECT
            COUNT(*) AS total_readings,
            SUM(CASE WHEN is_simulated = 0 THEN 1 ELSE 0 END) AS hardware_readings,
            SUM(CASE WHEN sensor_ok = 1 THEN 1 ELSE 0 END) AS valid_readings,
            COUNT(DISTINCT site_name) AS distinct_sites,
            MIN(recorded_at) AS first_reading_at,
            MAX(recorded_at) AS last_reading_at
        FROM sensor_readings
        WHERE user_id = ? OR device_id = ?
        """,
        (uid, device_id),
    ).fetchone()
    conn.close()

    total = stats["total_readings"] or 0
    valid = stats["valid_readings"] or 0
    valid_rate = round((valid / total) * 100.0, 2) if total > 0 else None

    return jsonify({
        "status": "ok",
        "reliability": {
            "total_persisted_readings": total,
            "hardware_readings": stats["hardware_readings"] or 0,
            "valid_readings": valid,
            "valid_reading_rate_pct": valid_rate,
            "distinct_sites_logged": stats["distinct_sites"] or 0,
            "first_reading_at": stats["first_reading_at"],
            "last_reading_at": stats["last_reading_at"],
        },
        "calibration": get_device_calibration(device_id),
    })


@app.route("/api/model-info")
def api_model_info():
    """Expose verified Random Forest hyperparameters and evaluation metadata."""
    if os.path.exists(MODEL_METADATA_PATH):
        with open(MODEL_METADATA_PATH, "r", encoding="utf-8") as f:
            meta = json.load(f)
    else:
        meta = {
            "model_type": type(CROP_MODEL).__name__,
            "hyperparameters": CROP_MODEL.get_params(),
            "n_classes": len(CROP_LABELS),
        }
    return jsonify({"status": "ok", "model": meta})


AREA_TO_ACRES_FACTORS = {
    "acres": 1.0,
    "hectares": 1.0 / 0.40468564224,
    "sqm": 1.0 / 4046.8564224,
    "sqft": 1.0 / 43560.0,
}


@app.route("/api/field-plans", methods=["GET", "POST"])
@api_login_required
def api_field_plans():
    """List or save conceptual field coverage deployment plans for the logged-in user."""
    uid = session["user_id"]

    if request.method == "GET":
        conn = get_db()
        rows = conn.execute(
            """
            SELECT id, field_name, location_name, latitude, longitude,
                   area_input, unit, area_acres, density_per_acre,
                   estimated_nodes, created_at
            FROM field_plans
            WHERE user_id = ?
            ORDER BY id DESC LIMIT 25
            """,
            (uid,),
        ).fetchall()
        conn.close()
        return jsonify({"status": "ok", "plans": [dict(r) for r in rows]})

    data = request.get_json(force=True, silent=True) or {}
    unit = str(data.get("unit", "acres")).strip().lower()
    if unit not in AREA_TO_ACRES_FACTORS:
        return jsonify({"status": "error", "message": f"Unsupported unit: {unit}"}), 400

    try:
        area_input = float(data.get("area_input"))
        density = float(data.get("density_per_acre", 5.0))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Invalid numeric area or density"}), 400

    if not math.isfinite(area_input) or area_input <= 0 or not math.isfinite(density) or density <= 0:
        return jsonify({"status": "error", "message": "Area and density must be positive finite numbers"}), 400

    area_acres = area_input * AREA_TO_ACRES_FACTORS[unit]
    if area_acres > 1_000_000:
        return jsonify({"status": "error", "message": "Area exceeds maximum supported planning limit (1,000,000 acres)"}), 400

    estimated_nodes = max(1, math.ceil(area_acres * density - 1e-9))
    field_name = str(data.get("field_name") or "My Field").strip()[:100] or "My Field"
    location_name = str(data.get("location_name") or "").strip()[:120]

    lat_val = data.get("latitude")
    lon_val = data.get("longitude")
    try:
        latitude = float(lat_val) if lat_val not in (None, "") else None
        longitude = float(lon_val) if lon_val not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Latitude and longitude must be valid numbers"}), 400

    if latitude is not None and not (-90.0 <= latitude <= 90.0):
        return jsonify({"status": "error", "message": "Latitude must be between -90 and 90"}), 400
    if longitude is not None and not (-180.0 <= longitude <= 180.0):
        return jsonify({"status": "error", "message": "Longitude must be between -180 and 180"}), 400

    created_at = datetime.now().isoformat(timespec="seconds")
    conn = get_db()
    cur = conn.execute(
        """
        INSERT INTO field_plans (
            user_id, field_name, location_name, latitude, longitude,
            area_input, unit, area_acres, density_per_acre,
            estimated_nodes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uid, field_name, location_name, latitude, longitude,
            area_input, unit, round(area_acres, 6), density,
            estimated_nodes, created_at,
        ),
    )
    plan_id = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM field_plans WHERE id = ?", (plan_id,)).fetchone()
    conn.close()

    if data.get("auto_provision_nodes", True):
        provision_nodes_for_field(uid, plan_id, min(estimated_nodes, 50))

    return jsonify({"status": "ok", "plan": dict(row)})


@app.route("/api/field-plans/<int:plan_id>", methods=["DELETE"])
@api_login_required
def api_delete_field_plan(plan_id: int):
    """Delete a saved field plan owned by the logged-in user."""
    uid = session["user_id"]
    conn = get_db()
    conn.execute("DELETE FROM sensor_nodes WHERE field_id = ? AND user_id = ?", (plan_id, uid))
    cur = conn.execute("DELETE FROM field_plans WHERE id = ? AND user_id = ?", (plan_id, uid))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return jsonify({"status": "error", "message": "Field plan not found"}), 404
    return jsonify({"status": "ok"})


# ══════════════════════════════════════════════════════════════════════════════
#  MULTI-NODE FIELD COLLECTION APIs
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_ZONE_NAMES = [
    "Center Zone",
    "North-West Zone",
    "North-East Zone",
    "South-West Zone",
    "South-East Zone",
]


def _default_zone_name(index: int, total: int) -> str:
    if total == 5 and index < 5:
        return DEFAULT_ZONE_NAMES[index]
    return f"Zone {index + 1:02d}"


def provision_nodes_for_field(user_id: int, field_id: int, target_count: int) -> list[dict]:
    """Ensure a field has at least `target_count` registered nodes (AGRI-001..N)."""
    target_count = max(1, min(int(target_count), 100))
    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM sensor_nodes WHERE field_id = ? AND user_id = ? ORDER BY id ASC",
        (field_id, user_id),
    ).fetchall()
    existing_ids = {r["node_id"] for r in existing}
    now_iso = datetime.now().isoformat(timespec="seconds")

    idx = 0
    while len(existing_ids) < target_count:
        idx += 1
        candidate = f"AGRI-{idx:03d}"
        if candidate in existing_ids:
            continue
        zone = _default_zone_name(len(existing_ids), target_count)
        conn.execute(
            """
            INSERT INTO sensor_nodes (node_id, field_id, user_id, zone_name, node_name, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'Pending', ?)
            """,
            (candidate, field_id, user_id, zone, f"Monitoring Node {idx:02d}", now_iso),
        )
        existing_ids.add(candidate)

    conn.commit()
    rows = conn.execute(
        "SELECT * FROM sensor_nodes WHERE field_id = ? AND user_id = ? ORDER BY id ASC",
        (field_id, user_id),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _format_node_reading_row(row: sqlite3.Row) -> dict:
    item = dict(row)
    try:
        measured = json.loads(item.get("measured_fields") or "[]")
    except (TypeError, ValueError):
        measured = []
    return {
        "reading_id": item["id"],
        "node_id": item["node_id"],
        "moisture": item["moisture"],
        "temperature": item["temperature"],
        "humidity": item["humidity"],
        "nitrogen": item["nitrogen"],
        "phosphorus": item["phosphorus"],
        "potassium": item["potassium"],
        "ph": item["ph"],
        "mq135": item["mq135"] if item["mq135"] is not None else item["air_quality"],
        "timestamp": item["recorded_at"],
        "reading_source": item.get("reading_source") or ("simulated" if item.get("is_simulated") else "hardware"),
        "measured_fields": measured,
        "sensor_ok": bool(item.get("sensor_ok", 1)),
    }


def _simulate_node_reading(node_id: str) -> dict:
    """Generate clearly labeled per-node simulated telemetry for demo/testing."""
    base = _simulate_reading(node_id)
    now_iso = datetime.now().isoformat(timespec="seconds")
    return {
        "reading_id": None,
        "node_id": node_id,
        "moisture": base["moisture"],
        "temperature": base["temperature"],
        "humidity": base["humidity"],
        "nitrogen": base["nitrogen"],
        "phosphorus": base["phosphorus"],
        "potassium": base["potassium"],
        "ph": base["ph"],
        "mq135": base["air_quality"],
        "timestamp": now_iso,
        "reading_source": "simulated",
        "measured_fields": [],
        "sensor_ok": True,
    }


def _compute_field_summary(field: dict, node_entries: list[dict], thresholds: dict) -> dict:
    """Aggregate valid readings across a field's nodes without replacing missing values with 0."""
    valid_moisture = []
    valid_temp = []
    valid_hum = []
    valid_ph = []
    valid_mq = []

    fetched_count = 0
    stale_count = 0
    offline_or_failed = 0
    hardware_count = 0
    simulated_count = 0
    attention_zones = []

    for entry in node_entries:
        st = entry.get("fetch_status", "Offline")
        reading = entry.get("reading")
        zone_label = f"{entry['node_id']} ({entry['zone_name']})"

        if st == "Fetched":
            fetched_count += 1
        elif st == "Stale Data":
            stale_count += 1
            attention_zones.append({"node_id": entry["node_id"], "zone": entry["zone_name"], "issue": "Stale telemetry"})
        else:
            offline_or_failed += 1
            attention_zones.append({"node_id": entry["node_id"], "zone": entry["zone_name"], "issue": f"Node {st}"})

        if not reading or st in ("Offline", "Failed"):
            continue

        if reading.get("reading_source") == "hardware":
            hardware_count += 1
        else:
            simulated_count += 1

        m = reading.get("moisture")
        t = reading.get("temperature")
        h = reading.get("humidity")
        ph = reading.get("ph")
        mq = reading.get("mq135")

        if m is not None:
            valid_moisture.append((entry["node_id"], entry["zone_name"], float(m)))
            if m < thresholds["moisture_low"]:
                attention_zones.append({"node_id": entry["node_id"], "zone": entry["zone_name"], "issue": f"Low moisture ({m:.1f}% < {thresholds['moisture_low']}%)"})
            elif m > thresholds["moisture_high"]:
                attention_zones.append({"node_id": entry["node_id"], "zone": entry["zone_name"], "issue": f"High moisture ({m:.1f}% > {thresholds['moisture_high']}%)"})
        if t is not None:
            valid_temp.append(float(t))
            if t > thresholds["temp_high"]:
                attention_zones.append({"node_id": entry["node_id"], "zone": entry["zone_name"], "issue": f"Elevated temperature ({t:.1f}°C)"})
        if h is not None:
            valid_hum.append(float(h))
        if ph is not None:
            valid_ph.append(float(ph))
            if ph < thresholds["ph_low"] or ph > thresholds["ph_high"]:
                attention_zones.append({"node_id": entry["node_id"], "zone": entry["zone_name"], "issue": f"Out-of-range pH ({ph:.2f})"})
        if mq is not None:
            valid_mq.append(float(mq))

    avg_moisture = round(sum(x[2] for x in valid_moisture) / len(valid_moisture), 2) if valid_moisture else None
    min_m = min(valid_moisture, key=lambda x: x[2]) if valid_moisture else None
    max_m = max(valid_moisture, key=lambda x: x[2]) if valid_moisture else None
    moisture_diff = round(max_m[2] - min_m[2], 2) if (min_m and max_m) else None

    total_nodes = len(node_entries)
    responding = fetched_count + stale_count

    return {
        "field_id": field["id"],
        "field_name": field["field_name"],
        "area_acres": field["area_acres"],
        "total_nodes": total_nodes,
        "nodes_fetched": fetched_count,
        "nodes_stale": stale_count,
        "nodes_offline_or_failed": offline_or_failed,
        "node_connectivity_pct": round((responding / total_nodes) * 100.0, 1) if total_nodes else 0.0,
        "data_sources": {"hardware_nodes": hardware_count, "simulated_nodes": simulated_count},
        "averages": {
            "moisture": avg_moisture,
            "temperature": round(sum(valid_temp) / len(valid_temp), 2) if valid_temp else None,
            "humidity": round(sum(valid_hum) / len(valid_hum), 2) if valid_hum else None,
            "ph": round(sum(valid_ph) / len(valid_ph), 2) if valid_ph else None,
            "mq135": round(sum(valid_mq) / len(valid_mq), 2) if valid_mq else None,
        },
        "moisture_differences": {
            "min_zone": f"{min_m[0]} ({min_m[1]})" if min_m else None,
            "min_moisture": round(min_m[2], 2) if min_m else None,
            "max_zone": f"{max_m[0]} ({max_m[1]})" if max_m else None,
            "max_moisture": round(max_m[2], 2) if max_m else None,
            "spread_pct": moisture_diff,
        },
        "zones_needing_attention": attention_zones,
        "data_freshness": {
            "fresh_nodes": fetched_count,
            "stale_nodes": stale_count,
            "stale_threshold_seconds": thresholds["stale_seconds"],
        },
        "thresholds_used": thresholds,
    }


@app.route("/api/fields")
@api_login_required
def api_fields():
    """Return user's fields; auto-provisions a 1-acre sample field with 5 nodes if empty."""
    uid = session["user_id"]
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM field_plans WHERE user_id = ? ORDER BY id DESC", (uid,)
    ).fetchall()
    conn.close()

    if not rows:
        now_iso = datetime.now().isoformat(timespec="seconds")
        conn = get_db()
        cur = conn.execute(
            """
            INSERT INTO field_plans (
                user_id, field_name, location_name, area_input, unit,
                area_acres, density_per_acre, estimated_nodes, created_at
            ) VALUES (?, 'Sample Field (1 Acre)', 'Demo Plot', 1, 'acres', 1.0, 5.0, 5, ?)
            """,
            (uid, now_iso),
        )
        field_id = cur.lastrowid
        conn.commit()
        conn.close()
        provision_nodes_for_field(uid, field_id, 5)
        conn = get_db()
        rows = conn.execute("SELECT * FROM field_plans WHERE user_id = ? ORDER BY id DESC", (uid,)).fetchall()
        conn.close()

    return jsonify({"status": "ok", "fields": [dict(r) for r in rows]})


@app.route("/api/fields/<int:field_id>/nodes", methods=["GET", "POST"])
@api_login_required
def api_field_nodes(field_id: int):
    """List or register/sync sensor nodes belonging to a field."""
    uid = session["user_id"]
    conn = get_db()
    field = conn.execute(
        "SELECT * FROM field_plans WHERE id = ? AND user_id = ?", (field_id, uid)
    ).fetchone()
    if not field:
        conn.close()
        return jsonify({"status": "error", "message": "Field not found"}), 404

    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        if "sync_count" in data:
            conn.close()
            try:
                sync_count = int(data["sync_count"])
            except (TypeError, ValueError):
                return jsonify({"status": "error", "message": "Invalid sync_count"}), 400
            nodes = provision_nodes_for_field(uid, field_id, sync_count)
            return jsonify({"status": "ok", "field_id": field_id, "nodes": nodes})

        node_id = str(data.get("node_id") or "").strip().upper()
        zone_name = str(data.get("zone_name") or "").strip()
        node_name = str(data.get("node_name") or "").strip()
        if not node_id:
            count_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM sensor_nodes WHERE field_id = ?", (field_id,)
            ).fetchone()
            next_num = (count_row["cnt"] or 0) + 1
            node_id = f"AGRI-{next_num:03d}"
        if not zone_name:
            zone_name = f"Zone {node_id}"
        if not node_name:
            node_name = f"Monitoring Node {node_id}"
        now_iso = datetime.now().isoformat(timespec="seconds")
        try:
            conn.execute(
                """
                INSERT INTO sensor_nodes (node_id, field_id, user_id, zone_name, node_name, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'Pending', ?)
                """,
                (node_id, field_id, uid, zone_name, node_name, now_iso),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({"status": "error", "message": f"Node {node_id} already registered on this field"}), 409

    node_rows = conn.execute(
        "SELECT * FROM sensor_nodes WHERE field_id = ? AND user_id = ? ORDER BY id ASC",
        (field_id, uid),
    ).fetchall()
    conn.close()

    if not node_rows and field["estimated_nodes"] > 0:
        nodes = provision_nodes_for_field(uid, field_id, min(field["estimated_nodes"], 50))
    else:
        nodes = [dict(r) for r in node_rows]

    # Attach latest timestamp metadata without fetching payloads eagerly
    conn = get_db()
    enriched = []
    for n in nodes:
        latest = conn.execute(
            "SELECT recorded_at, reading_source FROM sensor_readings WHERE node_id = ? ORDER BY id DESC LIMIT 1",
            (n["node_id"],),
        ).fetchone()
        n["last_received_at"] = latest["recorded_at"] if latest else None
        n["reading_source"] = latest["reading_source"] if latest else None
        enriched.append(n)
    conn.close()

    return jsonify({"status": "ok", "field": dict(field), "nodes": enriched})


def _resolve_node_latest(uid: int, node_id: str, field_id: int | None, simulate: bool, stale_seconds: int, sim_scenario: str = "normal") -> tuple[dict, int]:
    conn = get_db()
    if field_id is not None:
        node = conn.execute(
            "SELECT * FROM sensor_nodes WHERE node_id = ? AND field_id = ? AND user_id = ?",
            (node_id, field_id, uid),
        ).fetchone()
    else:
        node = conn.execute(
            "SELECT * FROM sensor_nodes WHERE node_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
            (node_id, uid),
        ).fetchone()

    if not node:
        conn.close()
        return {"status": "error", "message": f"Node '{node_id}' not found"}, 404

    if simulate:
        conn.close()
        if sim_scenario == "failed":
            return {
                "status": "ok",
                "node": dict(node),
                "fetch_status": "Failed",
                "reason": "Simulated timeout / no response from node",
                "reading": None,
            }, 200
        if sim_scenario == "offline":
            return {
                "status": "ok",
                "node": dict(node),
                "fetch_status": "Offline",
                "reason": "Simulated offline node",
                "reading": None,
            }, 200
        reading = _simulate_node_reading(node_id)
        if sim_scenario == "missing_npk":
            reading["nitrogen"] = None
            reading["phosphorus"] = None
            reading["potassium"] = None
            reading["ph"] = None
        if sim_scenario == "stale":
            reading["timestamp"] = (datetime.now() - timedelta(seconds=stale_seconds + 120)).isoformat(timespec="seconds")
            return {
                "status": "ok",
                "node": dict(node),
                "fetch_status": "Stale Data",
                "is_stale": True,
                "age_seconds": stale_seconds + 120,
                "reason": f"Reading older than {stale_seconds}s freshness window",
                "reading": reading,
            }, 200
        return {
            "status": "ok",
            "node": dict(node),
            "fetch_status": "Fetched",
            "is_stale": False,
            "age_seconds": 0,
            "reading": reading,
        }, 200

    latest_row = conn.execute(
        "SELECT * FROM sensor_readings WHERE node_id = ? ORDER BY id DESC LIMIT 1",
        (node_id,),
    ).fetchone()
    conn.close()

    if not latest_row:
        return {
            "status": "ok",
            "node": dict(node),
            "fetch_status": "Offline",
            "reason": "No telemetry received from this node yet",
            "reading": None,
        }, 200

    formatted = _format_node_reading_row(latest_row)
    if not formatted["sensor_ok"]:
        return {
            "status": "ok",
            "node": dict(node),
            "fetch_status": "Failed",
            "reason": "Node reported a sensor fault or out-of-range reading",
            "reading": formatted,
        }, 200

    try:
        age_seconds = max(0, int((datetime.now() - datetime.fromisoformat(formatted["timestamp"])).total_seconds()))
    except ValueError:
        age_seconds = 0

    is_stale = age_seconds > stale_seconds
    return {
        "status": "ok",
        "node": dict(node),
        "fetch_status": "Stale Data" if is_stale else "Fetched",
        "is_stale": is_stale,
        "age_seconds": age_seconds,
        "reason": f"Reading age ({age_seconds}s) exceeds {stale_seconds}s threshold" if is_stale else None,
        "reading": formatted,
    }, 200


@app.route("/api/nodes/<node_id>/latest")
@api_login_required
def api_node_latest(node_id: str):
    """Retrieve the latest reading and freshness status for a single registered sensor node."""
    uid = session["user_id"]
    field_id = request.args.get("field_id", type=int)
    simulate = request.args.get("simulate", "0").lower() in ("1", "true", "yes")
    stale_seconds = request.args.get("stale_seconds", default=300, type=int)
    sim_scenario = request.args.get("sim_scenario", default="normal")
    payload, status_code = _resolve_node_latest(uid, node_id, field_id, simulate, stale_seconds, sim_scenario)
    return jsonify(payload), status_code


@app.route("/api/nodes/<node_id>/history")
@api_login_required
def api_node_history(node_id: str):
    """Retrieve historical readings for a single registered sensor node."""
    uid = session["user_id"]
    conn = get_db()
    node = conn.execute(
        "SELECT * FROM sensor_nodes WHERE node_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
        (node_id, uid),
    ).fetchone()
    if not node:
        conn.close()
        return jsonify({"status": "error", "message": f"Node '{node_id}' not found"}), 404

    rows = conn.execute(
        "SELECT * FROM sensor_readings WHERE node_id = ? ORDER BY id DESC LIMIT 30",
        (node_id,),
    ).fetchall()
    conn.close()
    return jsonify({
        "status": "ok",
        "node": dict(node),
        "history": [_format_node_reading_row(r) for r in rows],
    })


@app.route("/api/fields/<int:field_id>/summary", methods=["GET", "POST"])
@api_login_required
def api_field_summary(field_id: int):
    """Generate a combined field-level analysis from valid node readings."""
    uid = session["user_id"]
    conn = get_db()
    field = conn.execute(
        "SELECT * FROM field_plans WHERE id = ? AND user_id = ?", (field_id, uid)
    ).fetchone()
    if not field:
        conn.close()
        return jsonify({"status": "error", "message": "Field not found"}), 404
    nodes = conn.execute(
        "SELECT * FROM sensor_nodes WHERE field_id = ? AND user_id = ? ORDER BY id ASC",
        (field_id, uid),
    ).fetchall()
    conn.close()

    thresholds = {
        "moisture_low": request.args.get("moisture_low", default=40.0, type=float),
        "moisture_high": request.args.get("moisture_high", default=85.0, type=float),
        "temp_high": request.args.get("temp_high", default=35.0, type=float),
        "ph_low": request.args.get("ph_low", default=6.0, type=float),
        "ph_high": request.args.get("ph_high", default=7.5, type=float),
        "stale_seconds": request.args.get("stale_seconds", default=300, type=int),
    }

    if request.method == "POST":
        body = request.get_json(force=True, silent=True) or {}
        if isinstance(body.get("thresholds"), dict):
            for k in thresholds:
                if k in body["thresholds"]:
                    thresholds[k] = float(body["thresholds"][k]) if k != "stale_seconds" else int(body["thresholds"][k])
        entries = body.get("node_results") or []
        summary = _compute_field_summary(dict(field), entries, thresholds)
        return jsonify({"status": "ok", "summary": summary})

    simulate = request.args.get("simulate", "0").lower() in ("1", "true", "yes")
    entries = []
    for n in nodes:
        res, _ = _resolve_node_latest(uid, n["node_id"], field_id, simulate, thresholds["stale_seconds"])
        entries.append({
            "node_id": n["node_id"],
            "zone_name": n["zone_name"],
            "fetch_status": res.get("fetch_status", "Offline"),
            "reading": res.get("reading"),
        })

    summary = _compute_field_summary(dict(field), entries, thresholds)
    return jsonify({"status": "ok", "summary": summary})


if __name__ == "__main__":
    print("[AgriSense] Server starting at http://localhost:5000")
    app.run(debug=True, port=5000)
