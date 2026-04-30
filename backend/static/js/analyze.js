/* ══════════════════════════════════════════════════════════
   AgriSense — Analyze Page JS
   ══════════════════════════════════════════════════════════ */
"use strict";

const form = document.getElementById("analyzeForm");
const btnAnalyze = document.getElementById("btnAnalyze");
const btnAutofill = document.getElementById("btnAutofill");

// Autofill from live sensor
btnAutofill.addEventListener("click", async () => {
  btnAutofill.textContent = "Fetching...";
  try {
    const res = await fetch("/api/soil");
    if (res.status === 401) { window.location.href = "/login"; return; }
    const json = await res.json();
    if (json.status === "ok") {
      const d = json.data;
      document.getElementById("nitrogen").value = d.nitrogen;
      document.getElementById("phosphorus").value = d.phosphorus;
      document.getElementById("potassium").value = d.potassium;
      document.getElementById("temperature").value = d.temperature;
      document.getElementById("humidity").value = d.humidity;
      document.getElementById("ph").value = d.ph;
    }
  } catch(e) {
    console.error(e);
  } finally {
    btnAutofill.textContent = "Autofill from Sensor";
  }
});

// Render Results
function renderResults(json) {
  const panel = document.getElementById("resultsPanel");
  panel.style.display = "block";
  panel.scrollIntoView({ behavior: 'smooth' });

  // Render chips
  const s = json.soil;
  document.getElementById("resultsChips").innerHTML = `
    <div class="soil-chip">N: <strong>${s.nitrogen}</strong></div>
    <div class="soil-chip">P: <strong>${s.phosphorus}</strong></div>
    <div class="soil-chip">K: <strong>${s.potassium}</strong></div>
    <div class="soil-chip">Temp: <strong>${s.temperature}°C</strong></div>
    <div class="soil-chip">Hum: <strong>${s.humidity}%</strong></div>
    <div class="soil-chip">pH: <strong>${s.ph}</strong></div>
  `;

  // Render top result
  const recs = json.recommendations || [];
  if (recs.length > 0) {
    const top = recs[0];
    document.getElementById("topResultContainer").innerHTML = `
      <div class="top-result-inner">
        <div>
          <div class="top-result-label">Top Recommendation</div>
          <div class="top-result-name">${top.crop.charAt(0).toUpperCase() + top.crop.slice(1)}</div>
        </div>
        <div class="top-result-score" style="color: var(--accent-primary);">${(top.probability*100).toFixed(1)}%</div>
      </div>
    `;
  }

  // Render alternates
  const altContainer = document.getElementById("altCropsContainer");
  altContainer.innerHTML = "";
  recs.slice(1, 5).forEach(crop => {
    const name = crop.crop.charAt(0).toUpperCase() + crop.crop.slice(1);
    const prob = (crop.probability*100).toFixed(1);
    const html = `
      <div style="background: rgba(0,0,0,0.2); border: 1px solid var(--border-light); padding: 16px; border-radius: var(--radius-md);">
        <div style="font-weight: 700; color: #fff; margin-bottom: 4px;">${name}</div>
        <div style="font-size: 0.85rem; color: var(--text-muted);">Score: ${prob}%</div>
      </div>
    `;
    altContainer.innerHTML += html;
  });

  // Render advisory
  const advList = document.getElementById("advisoryList");
  advList.innerHTML = "";
  (json.advisory || []).forEach(tip => {
    advList.innerHTML += `<li>${tip}</li>`;
  });
}

// Form Submit
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  
  btnAnalyze.innerHTML = "<div class='loading-spinner' style='width: 20px; height: 20px; border-width: 2px; margin: 0;'></div> Analyzing...";
  btnAnalyze.disabled = true;

  const payload = {
    nitrogen: parseFloat(document.getElementById("nitrogen").value),
    phosphorus: parseFloat(document.getElementById("phosphorus").value),
    potassium: parseFloat(document.getElementById("potassium").value),
    temperature: parseFloat(document.getElementById("temperature").value),
    humidity: parseFloat(document.getElementById("humidity").value),
    ph: parseFloat(document.getElementById("ph").value)
  };

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.status === 401) { window.location.href = "/login"; return; }
    
    const json = await res.json();
    if (json.status === "ok") {
      setTimeout(() => renderResults(json), 500); // slight delay for animation feel
    }
  } catch (err) {
    console.error(err);
    alert("Analysis failed. Please try again.");
  } finally {
    setTimeout(() => {
      btnAnalyze.innerHTML = "Run ML Analysis 🧠";
      btnAnalyze.disabled = false;
    }, 500);
  }
});
