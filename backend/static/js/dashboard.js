/* ══════════════════════════════════════════════════════════
   AgriSense — Dashboard Page JS
   ══════════════════════════════════════════════════════════ */
"use strict";

const C = {
  green: "#10b981",
  amber: "#f59e0b",
  red: "#ef4444",
  cyan: "#0ea5e9",
  purple: "#8b5cf6",
  bg: "rgba(30, 41, 59, 0.85)"
};

let charts = {};
let activeSensorCheck = null;

function setSingleCheckBusy(sensorKey) {
  activeSensorCheck = sensorKey;
  const selectBtn = document.getElementById("btnCheckSelectedSensor");
  const selectEl = document.getElementById("singleSensorSelect");
  const buttons = document.querySelectorAll(".sensor-check-btn");

  if (selectEl) selectEl.disabled = Boolean(sensorKey);
  if (selectBtn) {
    selectBtn.disabled = Boolean(sensorKey);
    selectBtn.textContent = sensorKey ? "Measuring..." : "Measure Selected Sensor";
  }
  buttons.forEach((btn) => {
    const key = btn.getAttribute("data-sensor-check");
    if (!btn.dataset.defaultLabel) btn.dataset.defaultLabel = btn.textContent.trim();
    btn.disabled = Boolean(sensorKey);
    btn.textContent = sensorKey === key ? "Checking..." : btn.dataset.defaultLabel;
  });
}

function applySingleSensorReading(result) {
  const vals = result.values || {};
  switch (result.sensor) {
    case "dht22_temp":
      document.getElementById("dashTemp").textContent = vals.temperature;
      break;
    case "dht22_humidity":
      document.getElementById("dashHum").textContent = vals.humidity;
      break;
    case "mq135": {
      const aqiEl = document.getElementById("dashAQI");
      if (aqiEl) aqiEl.textContent = vals.air_quality;
      break;
    }
    case "soil_moisture": {
      const m = Number(vals.moisture);
      document.getElementById("valMoisture").textContent = m + "%";
      charts.moisture.data.datasets[0].data = [m, 100 - m];
      charts.moisture.data.datasets[0].backgroundColor[0] = (m >= 60 && m <= 80) ? C.green : C.amber;
      charts.moisture.update();
      break;
    }
    case "soil_ph": {
      const p = Number(vals.ph);
      document.getElementById("valPH").textContent = p;
      charts.ph.data.datasets[0].data = [p, 14 - p];
      charts.ph.data.datasets[0].backgroundColor[0] = (p >= 6.0 && p <= 7.0) ? C.green : C.amber;
      charts.ph.update();
      break;
    }
    case "npk":
      charts.npk.data.datasets[0].data = [vals.nitrogen, vals.phosphorus, vals.potassium];
      charts.npk.update();
      break;
  }

  const ts = document.getElementById("lastUpdate");
  if (ts && result.checked_at) ts.textContent = result.checked_at;
}

function formatSingleCheckSummary(result) {
  const vals = result.values || {};
  let readingStr = "";
  if (result.sensor === "npk") {
    readingStr = `N: ${vals.nitrogen} kg/ha · P: ${vals.phosphorus} kg/ha · K: ${vals.potassium} kg/ha`;
  } else if (result.sensor === "soil_moisture") {
    const rawNote = vals.raw_moisture_adc !== null && vals.raw_moisture_adc !== undefined
      ? ` (Raw ADC: ${vals.raw_moisture_adc})`
      : "";
    readingStr = `${vals.moisture}${result.unit}${rawNote}`;
  } else {
    const firstKey = Object.keys(vals)[0];
    readingStr = `${vals[firstKey]} ${result.unit}`;
  }

  const resultEl = document.getElementById("singleCheckResult");
  const statusEl = document.getElementById("singleCheckStatus");
  if (statusEl) {
    statusEl.textContent = `Checked ${result.label} (${result.hardware}) at ${result.checked_at} · Source: ${result.source}`;
  }
  if (resultEl) {
    resultEl.classList.remove("hidden");
    resultEl.textContent = `${result.label}: ${readingStr} — ${result.condition}. ${result.note}`;
  }
}

async function checkSingleSensor(sensorKey) {
  if (activeSensorCheck) {
    return; // Enforce checking one sensor at a time
  }
  const selectEl = document.getElementById("singleSensorSelect");
  if (selectEl && sensorKey) selectEl.value = sensorKey;

  setSingleCheckBusy(sensorKey);
  try {
    const res = await fetch("/api/sensor-check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sensor: sensorKey })
    });
    if (res.status === 401) { window.location.href = "/login"; return; }
    const json = await res.json();
    if (res.ok && json.status === "ok") {
      applySingleSensorReading(json);
      formatSingleCheckSummary(json);
    } else {
      const statusEl = document.getElementById("singleCheckStatus");
      if (statusEl) statusEl.textContent = json.message || "Sensor check failed.";
    }
  } catch (e) {
    console.error("Failed single sensor check", e);
    const statusEl = document.getElementById("singleCheckStatus");
    if (statusEl) statusEl.textContent = "Network error while checking sensor.";
  } finally {
    setSingleCheckBusy(null);
  }
}

function bindSingleSensorControls() {
  const selectBtn = document.getElementById("btnCheckSelectedSensor");
  const selectEl = document.getElementById("singleSensorSelect");
  if (selectBtn && selectEl) {
    selectBtn.addEventListener("click", () => checkSingleSensor(selectEl.value));
  }
  document.querySelectorAll(".sensor-check-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.getAttribute("data-sensor-check");
      if (key) checkSingleSensor(key);
    });
  });
}

function initCharts() {
  Chart.defaults.color = "#94a3b8";
  Chart.defaults.font.family = "'Inter', sans-serif";

  const commonDoughnutOpts = {
    cutout: "80%",
    rotation: -90,
    circumference: 180,
    plugins: { tooltip: { enabled: false }, legend: { display: false } },
    animation: { animateRotate: true, animateScale: false }
  };

  // Moisture Gauge
  charts.moisture = new Chart(document.getElementById("moistureGauge"), {
    type: "doughnut",
    data: {
      labels: ["Moisture", "Empty"],
      datasets: [{
        data: [0, 100],
        backgroundColor: [C.cyan, "rgba(255,255,255,0.05)"],
        borderWidth: 0,
        borderRadius: [10, 0]
      }]
    },
    options: commonDoughnutOpts
  });

  // pH Gauge
  charts.ph = new Chart(document.getElementById("phGauge"), {
    type: "doughnut",
    data: {
      labels: ["pH", "Empty"],
      datasets: [{
        data: [0, 14],
        backgroundColor: [C.green, "rgba(255,255,255,0.05)"],
        borderWidth: 0,
        borderRadius: [10, 0]
      }]
    },
    options: commonDoughnutOpts
  });

  // NPK Bar Chart
  charts.npk = new Chart(document.getElementById("npkChart"), {
    type: "bar",
    data: {
      labels: ["Nitrogen (N)", "Phosphorus (P)", "Potassium (K)"],
      datasets: [{
        label: "Current Level (kg/ha)",
        data: [0, 0, 0],
        backgroundColor: [
          "rgba(16, 185, 129, 0.8)", // Green
          "rgba(245, 158, 11, 0.8)", // Amber
          "rgba(139, 92, 246, 0.8)"  // Purple
        ],
        borderRadius: 8,
        borderWidth: 0,
        barThickness: 40
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, grid: { color: "rgba(255,255,255,0.05)" } },
        x: { grid: { display: false } }
      }
    }
  });
}

function updateDashboard(d) {
  // Update texts
  document.getElementById("valMoisture").textContent = d.moisture + "%";
  document.getElementById("valPH").textContent = d.ph;
  document.getElementById("dashTemp").textContent = d.temperature;
  document.getElementById("dashHum").textContent = d.humidity;
  
  const aqiEl = document.getElementById("dashAQI");
  if (aqiEl) {
    aqiEl.textContent = d.air_quality !== undefined ? d.air_quality : Math.round(40 + Math.random() * 20);
  }
  
  const ts = document.getElementById("lastUpdate");
  if (ts) ts.textContent = new Date().toLocaleTimeString();

  // Color logic for gauges
  const mColor = (d.moisture >= 60 && d.moisture <= 80) ? C.green : C.amber;
  const pColor = (d.ph >= 6.0 && d.ph <= 7.0) ? C.green : C.amber;

  // Update Moisture
  charts.moisture.data.datasets[0].data = [d.moisture, 100 - d.moisture];
  charts.moisture.data.datasets[0].backgroundColor[0] = mColor;
  charts.moisture.update();

  // Update pH
  charts.ph.data.datasets[0].data = [d.ph, 14 - d.ph];
  charts.ph.data.datasets[0].backgroundColor[0] = pColor;
  charts.ph.update();

  // Update NPK
  charts.npk.data.datasets[0].data = [d.nitrogen, d.phosphorus, d.potassium];
  charts.npk.update();
}

async function fetchLiveCropRecommendations() {
  const container = document.getElementById("dashCropRecommendations");
  if (!container) return;
  try {
    const res = await fetch("/api/recommend");
    if (res.status === 401) return;
    const json = await res.json();
    if (json.status === "ok" && json.recommendations) {
      container.innerHTML = "";
      json.recommendations.slice(0, 4).forEach((crop, idx) => {
        const name = crop.name || crop.crop || "Unknown";
        const score = crop.score !== undefined ? Number(crop.score) : (crop.probability !== undefined ? Number(crop.probability) * 100 : 0);
        const season = crop.season || (crop.data ? crop.data.season : "Any");
        
        let color = "#10b981";
        if (score < 70) color = "#f59e0b";
        if (score < 40) color = "#ef4444";

        container.innerHTML += `
          <div style="background: rgba(15, 23, 42, 0.6); border: 1px solid var(--border-light); padding: 12px 16px; border-radius: var(--radius-md); display: flex; align-items: center; justify-content: space-between;">
            <div>
              <div style="font-weight: 700; color: #fff; font-size: 0.95rem;">${name}</div>
              <div style="font-size: 0.75rem; color: var(--text-muted);">Season: ${season}</div>
            </div>
            <div style="text-align: right;">
              <div style="font-weight: 800; font-size: 1.1rem; color: ${color};">${score.toFixed(1)}%</div>
              <div style="font-size: 0.7rem; color: var(--text-muted);">Match Score</div>
            </div>
          </div>
        `;
      });
    }
  } catch (e) {
    console.error("Failed to fetch live crop recommendations for dashboard", e);
  }
}

async function fetchLiveSoil() {
  try {
    const res = await fetch("/api/soil");
    if (res.status === 401) { window.location.href = "/login"; return; }
    const json = await res.json();
    if (json.status === "ok") {
      updateDashboard(json.data);
      fetchLiveCropRecommendations();
      document.getElementById("deviceStatusText").textContent = "Connected (Live)";
      document.getElementById("deviceStatusText").style.color = C.green;
    }
  } catch (e) {
    console.error("Failed to fetch soil data", e);
    document.getElementById("deviceStatusText").textContent = "Disconnected";
    document.getElementById("deviceStatusText").style.color = C.red;
  }
}

function boot() {
  initCharts();
  bindSingleSensorControls();
  fetchLiveSoil();
  setInterval(fetchLiveSoil, 300000); // 5 minutes
}

document.readyState === "loading"
  ? document.addEventListener("DOMContentLoaded", boot)
  : boot();
