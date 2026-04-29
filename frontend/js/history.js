/* ══════════════════════════════════════════════════════════
   AgriSense — History Page JS
   ══════════════════════════════════════════════════════════ */
"use strict";

const C = {
  green: "#10b981", amber: "#f59e0b", red: "#ef4444",
  cyan: "#0ea5e9", purple: "#8b5cf6", pink: "#ec4899"
};

let charts = {};

function initHistoryCharts() {
  Chart.defaults.color = "#94a3b8";
  Chart.defaults.font.family = "'Inter', sans-serif";

  const commonOpts = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    elements: { point: { radius: 2, hoverRadius: 5 }, line: { tension: 0.4, borderWidth: 2 } },
    plugins: { legend: { position: 'top', labels: { usePointStyle: true, boxWidth: 8 } } },
    scales: {
      x: { grid: { display: false } },
      y: { grid: { color: "rgba(255,255,255,0.05)" } }
    }
  };

  // 1. Moisture & Humidity
  charts.mh = new Chart(document.getElementById("moistureHistoryChart"), {
    type: "line",
    data: { labels: [], datasets: [
      { label: "Moisture (%)", borderColor: C.cyan, backgroundColor: "rgba(14, 165, 233, 0.1)", fill: true, data: [] },
      { label: "Humidity (%)", borderColor: C.green, backgroundColor: "transparent", borderDash: [5, 5], data: [] }
    ]},
    options: commonOpts
  });

  // 2. NPK
  charts.npk = new Chart(document.getElementById("npkHistoryChart"), {
    type: "line",
    data: { labels: [], datasets: [
      { label: "Nitrogen (N)", borderColor: C.green, backgroundColor: "transparent", data: [] },
      { label: "Phosphorus (P)", borderColor: C.amber, backgroundColor: "transparent", data: [] },
      { label: "Potassium (K)", borderColor: C.purple, backgroundColor: "transparent", data: [] }
    ]},
    options: commonOpts
  });

  // 3. Temp & pH
  charts.tp = new Chart(document.getElementById("tempPhHistoryChart"), {
    type: "line",
    data: { labels: [], datasets: [
      { label: "Temp (°C)", borderColor: C.amber, backgroundColor: "transparent", data: [], yAxisID: 'y' },
      { label: "pH Level", borderColor: C.pink, backgroundColor: "transparent", data: [], yAxisID: 'y1' }
    ]},
    options: {
      ...commonOpts,
      scales: {
        x: { grid: { display: false } },
        y: { position: 'left', grid: { color: "rgba(255,255,255,0.05)" }, title: {display: true, text: 'Temp (°C)'} },
        y1: { position: 'right', grid: { display: false }, title: {display: true, text: 'pH Level'}, min: 0, max: 14 }
      }
    }
  });
}

function updateHistoryCharts(dataArr) {
  const labels = dataArr.map(d => {
    const dObj = new Date(d.timestamp);
    return `${dObj.getHours()}:${dObj.getMinutes().toString().padStart(2, '0')}:${dObj.getSeconds().toString().padStart(2, '0')}`;
  });

  // Update M&H
  charts.mh.data.labels = labels;
  charts.mh.data.datasets[0].data = dataArr.map(d => d.moisture);
  charts.mh.data.datasets[1].data = dataArr.map(d => d.humidity);
  charts.mh.update();

  // Update NPK
  charts.npk.data.labels = labels;
  charts.npk.data.datasets[0].data = dataArr.map(d => d.nitrogen);
  charts.npk.data.datasets[1].data = dataArr.map(d => d.phosphorus);
  charts.npk.data.datasets[2].data = dataArr.map(d => d.potassium);
  charts.npk.update();

  // Update T&P
  charts.tp.data.labels = labels;
  charts.tp.data.datasets[0].data = dataArr.map(d => d.temperature);
  charts.tp.data.datasets[1].data = dataArr.map(d => d.ph);
  charts.tp.update();
}

async function fetchHistory() {
  try {
    const res = await fetch("/api/history");
    if (res.status === 401) { window.location.href = "/login"; return; }
    const json = await res.json();
    if (json.status === "ok" && json.data.length > 0) {
      updateHistoryCharts(json.data);
      const ts = document.getElementById("lastUpdate");
      if (ts) ts.textContent = new Date().toLocaleTimeString();
    }
  } catch (e) {
    console.error("Failed to fetch history data", e);
  }
}

function boot() {
  initHistoryCharts();
  fetchHistory();
  setInterval(fetchHistory, 300000); // 5 minutes
}

document.readyState === "loading"
  ? document.addEventListener("DOMContentLoaded", boot)
  : boot();
