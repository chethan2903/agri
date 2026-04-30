/* ══════════════════════════════════════════════════════════
   AgriSense — Weather Page JS
   ══════════════════════════════════════════════════════════ */
"use strict";

const icons = {
  "Sunny": "☀️",
  "Cloudy": "☁️",
  "Partly Cloudy": "⛅",
  "Rain": "🌧️",
  "Storm": "⛈️"
};

function createWeatherCard(day, index) {
  const icon = icons[day.condition] || "⛅";
  const rainProb = day.rain_probability || 0;
  
  const el = document.createElement("div");
  el.className = "weather-card";
  el.style.animation = `slideUp 0.4s ease forwards ${index * 0.1}s`;
  el.style.opacity = "0";
  
  el.innerHTML = `
    <div class="w-day">${day.day}</div>
    <div class="w-icon">${icon}</div>
    <div class="w-temps">
      <span class="w-high">${day.high}°</span>
      <span class="w-low">${day.low}°</span>
    </div>
    <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px;">Rain: ${rainProb}%</div>
    <div class="w-rain">
      <div class="w-rain-fill" style="width: ${rainProb}%"></div>
    </div>
  `;
  return el;
}

async function fetchWeather() {
  try {
    const res = await fetch("/api/weather");
    if (res.status === 401) { window.location.href = "/login"; return; }
    const json = await res.json();
    
    document.getElementById("loadingContainer").classList.add("hidden");
    const grid = document.getElementById("weatherGrid");
    grid.classList.remove("hidden");
    grid.innerHTML = "";

    if (json.status === "ok" && json.forecast) {
      // Set current top block to first day
      const today = json.forecast[0];
      document.getElementById("currentTemp").textContent = `${today.high}°C`;
      document.getElementById("currentDesc").textContent = today.condition;
      document.getElementById("currentIcon").textContent = icons[today.condition] || "⛅";

      json.forecast.forEach((day, idx) => {
        grid.appendChild(createWeatherCard(day, idx));
      });
      
      const ts = document.getElementById("lastUpdate");
      if (ts) ts.textContent = new Date().toLocaleTimeString();
    }
  } catch(e) {
    console.error("Failed to fetch weather", e);
  }
}

document.readyState === "loading"
  ? document.addEventListener("DOMContentLoaded", fetchWeather)
  : fetchWeather();
