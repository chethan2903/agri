/* ══════════════════════════════════════════════════════════
   AgriSense — Crops Page JS
   ══════════════════════════════════════════════════════════ */
"use strict";

function createCropCard(crop, index) {
  const prob = crop.probability * 100;
  let color = "#10b981"; // Green
  if (prob < 70) color = "#f59e0b"; // Amber
  if (prob < 40) color = "#ef4444"; // Red

  // Format the name nicely
  const formattedName = crop.crop.charAt(0).toUpperCase() + crop.crop.slice(1);
  const data = crop.data || {};
  const season = data.season || "Year-round";
  const desc = data.desc || "Optimal crop choice for current soil conditions.";
  const tags = data.tags || [];

  const html = `
    <div class="crop-header">
      <div style="flex: 1;">
        <div class="crop-name">${formattedName}</div>
        <div class="crop-season">Best in: ${season}</div>
      </div>
      <div style="font-size: 2rem;">🌱</div>
    </div>
    
    <div class="score-bar-wrap">
      <div class="score-bar-header">
        <span>Compatibility Score</span>
        <span style="color: ${color};">${prob.toFixed(1)}%</span>
      </div>
      <div class="score-track">
        <div class="score-fill" style="width: 0%; background: ${color};" data-target="${prob}"></div>
      </div>
    </div>

    <div class="crop-desc">${desc}</div>
    
    <div class="crop-meta">
      ${tags.map(t => `<span class="crop-tag">${t}</span>`).join('')}
    </div>
  `;

  const el = document.createElement("div");
  el.className = "crop-card";
  el.style.animationDelay = `${index * 0.1}s`;
  el.innerHTML = html;

  // Trigger animation after render
  setTimeout(() => {
    const fill = el.querySelector(".score-fill");
    if (fill) fill.style.width = fill.getAttribute("data-target") + "%";
  }, 100);

  return el;
}

async function fetchRecommendations() {
  try {
    const res = await fetch("/api/recommend");
    if (res.status === 401) { window.location.href = "/login"; return; }
    const json = await res.json();
    
    document.getElementById("loadingContainer").classList.add("hidden");
    const container = document.getElementById("cropsContainer");
    container.classList.remove("hidden");
    container.innerHTML = "";

    if (json.status === "ok" && json.recommendations) {
      json.recommendations.forEach((crop, idx) => {
        container.appendChild(createCropCard(crop, idx));
      });
      const ts = document.getElementById("lastUpdate");
      if (ts) ts.textContent = new Date().toLocaleTimeString();
    } else {
      container.innerHTML = `<div class="col-span-12" style="text-align: center; color: var(--text-muted); padding: 40px;">No recommendations available right now. Ensure sensor is online.</div>`;
    }
  } catch (e) {
    console.error("Failed to fetch crop data", e);
  }
}

document.readyState === "loading"
  ? document.addEventListener("DOMContentLoaded", fetchRecommendations)
  : fetchRecommendations();
