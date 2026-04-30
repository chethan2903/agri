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

app = Flask(__name__)
CORS(app)

# ── Persistent secret key (sessions survive restarts) ─────────────────────────
_KEY_FILE = "secret.key"
if os.path.exists(_KEY_FILE):
    with open(_KEY_FILE, "rb") as _f:
        app.secret_key = _f.read()
else:
    _key = os.urandom(32)
    with open(_KEY_FILE, "wb") as _f:
        _f.write(_key)
    app.secret_key = _key

# ── Database ───────────────────────────────────────────────────────────────────
DATABASE = "agrisense.db"

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
with open("data/crops.json", "r", encoding="utf-8") as f:
    CROPS = json.load(f)

with open("models/crop_model.pkl", "rb") as f:
    CROP_MODEL = pickle.load(f)

with open("models/crop_labels.pkl", "rb") as f:
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

    return {
        "timestamp":   (datetime.now() + timedelta(seconds=time_offset)).strftime("%H:%M:%S"),
        "moisture":    max(10,  min(100, moisture)),
        "ph":          max(4.0, min(9.0, ph)),
        "nitrogen":    max(5,   min(200, nitrogen)),
        "phosphorus":  max(5,   min(150, phosphorus)),
        "potassium":   max(5,   min(200, potassium)),
        "temperature": max(5,   min(50,  temperature)),
        "humidity":    max(10,  min(100, humidity)),
    }

def _build_history(device_id: str) -> list:
    hist = []
    for i in range(29, -1, -1):
        r = _simulate_reading(device_id, time_offset=-(i * 5))
        r["timestamp"] = (datetime.now() - timedelta(seconds=i * 5)).strftime("%H:%M:%S")
        hist.append(r)
    return hist

def get_user_history(user_id: int, device_id: str) -> list:
    if user_id not in _user_histories:
        _user_histories[user_id] = _build_history(device_id)
    return _user_histories[user_id]

# ── Crop scoring engine ────────────────────────────────────────────────────────
def _get_ml_recommendations(soil: dict) -> list:
    # Model features: ['N' 'P' 'K' 'temperature' 'humidity' 'ph']
    features = [[
        soil["nitrogen"],
        soil["phosphorus"],
        soil["potassium"],
        soil["temperature"],
        soil["humidity"],
        soil["ph"]
    ]]
    
    probs = CROP_MODEL.predict_proba(features)[0]
    
    results = []
    for label, prob in zip(CROP_LABELS, probs):
        if prob > 0:
            # Match with CROPS json
            crop_info = next((c for c in CROPS if c["name"].lower() == label.lower()), None)
            score = round(prob * 100, 1)
            if crop_info:
                results.append({**crop_info, "score": score})
            else:
                results.append({
                    "name": label.capitalize(),
                    "image": "",
                    "score": score,
                    "season": "Any",
                    "description": "Recommended by AI model.",
                    "waterRequirement": "Unknown",
                    "growthDuration": "Unknown"
                })
    
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
        tips.append(f"Low nitrogen ({soil['nitrogen']:.0f} kg/ha). Apply urea or ammonium nitrate fertilizer.")
    if soil["phosphorus"] < 30:
        tips.append(f"Phosphorus deficiency ({soil['phosphorus']:.0f} kg/ha). Apply superphosphate or DAP.")
    if soil["potassium"]  < 30:
        tips.append(f"Low potassium ({soil['potassium']:.0f} kg/ha). Apply muriate of potash (MOP).")

    if top_crops:
        b = top_crops[0]
        tips.append(f"Best crop match: {b['name']} with {b['score']:.0f}% compatibility — ideal for {b['season']} season.")
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
    return render_frontend("index.html")

@app.route("/dashboard")
@login_required
def dashboard():
    user = get_current_user()
    return render_frontend("dashboard.html", active_page="dashboard", **_base_ctx(user))

@app.route("/analyze")
@login_required
def analyze():
    user = get_current_user()
    return render_frontend("analyze.html", active_page="analyze", **_base_ctx(user))

@app.route("/crops")
@login_required
def crops():
    user = get_current_user()
    return render_frontend("crops.html", active_page="crops", **_base_ctx(user))

@app.route("/history")
@login_required
def history():
    user = get_current_user()
    return render_frontend("history.html", active_page="history", **_base_ctx(user))

@app.route("/weather")
@login_required
def weather():
    user = get_current_user()
    return render_frontend("weather.html", active_page="weather", **_base_ctx(user))

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
    return render_frontend(
        "profile.html",
        active_page = "profile",
        success     = success,
        error       = error,
        created_at  = created_at,
        **_base_ctx(user),
    )

# ══════════════════════════════════════════════════════════════════════════════
#  API ROUTES  (all require login)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/soil")
@api_login_required
def api_soil():
    uid       = session["user_id"]
    device_id = session["device_id"]
    reading   = _simulate_reading(device_id)
    hist      = get_user_history(uid, device_id)
    hist.append(reading)
    if len(hist) > 50:
        hist.pop(0)
    return jsonify({"status": "ok", "data": reading})


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


if __name__ == "__main__":
    print("[AgriSense] Server starting at http://localhost:5000")
    app.run(debug=True, port=5000)
