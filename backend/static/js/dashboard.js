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

async function fetchLiveSoil() {
  try {
    const res = await fetch("/api/soil");
    if (res.status === 401) { window.location.href = "/login"; return; }
    const json = await res.json();
    if (json.status === "ok") {
      updateDashboard(json.data);
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
  fetchLiveSoil();
  setInterval(fetchLiveSoil, 300000); // 5 minutes
}

document.readyState === "loading"
  ? document.addEventListener("DOMContentLoaded", boot)
  : boot();
