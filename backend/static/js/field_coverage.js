/* ══════════════════════════════════════════════════════════
   AgriSense — Field Coverage Planner & Sequential Node Collection JS
   ══════════════════════════════════════════════════════════ */
"use strict";

const SQM_PER_ACRE = 4046.8564224;
const HA_PER_ACRE = 0.40468564224;
const SQFT_PER_ACRE = 43560;
const DEFAULT_DENSITY = 5;
const MAX_ACRES_LIMIT = 1000000;
const MAX_RENDERED_NODES = 200;
const EPSILON = 1e-9;
const FETCH_TIMEOUT_MS = 6000;
const SEQUENTIAL_STEP_DELAY_MS = 280;

const UNIT_META = {
  acres: { singular: "acre", plural: "acres", toAcres: (v) => v, fromAcres: (a) => a, decimals: 4 },
  hectares: { singular: "hectare", plural: "hectares", toAcres: (v) => v / HA_PER_ACRE, fromAcres: (a) => a * HA_PER_ACRE, decimals: 4 },
  sqm: { singular: "square metre", plural: "square metres", toAcres: (v) => v / SQM_PER_ACRE, fromAcres: (a) => a * SQM_PER_ACRE, decimals: 2 },
  sqft: { singular: "square foot", plural: "square feet", toAcres: (v) => v / SQFT_PER_ACRE, fromAcres: (a) => a * SQFT_PER_ACRE, decimals: 2 },
};

const STATUS_STYLE = {
  Pending: { color: "#94a3b8", zoneFill: "rgba(148, 163, 184, 0.10)", zoneStroke: "rgba(148, 163, 184, 0.35)", css: "pending" },
  Fetching: { color: "#38bdf8", zoneFill: "rgba(56, 189, 248, 0.18)", zoneStroke: "rgba(56, 189, 248, 0.70)", css: "fetching" },
  Fetched: { color: "#10b981", zoneFill: "rgba(16, 185, 129, 0.14)", zoneStroke: "rgba(16, 185, 129, 0.45)", css: "fetched" },
  "Stale Data": { color: "#f59e0b", zoneFill: "rgba(245, 158, 11, 0.14)", zoneStroke: "rgba(245, 158, 11, 0.55)", css: "stale" },
  Failed: { color: "#ef4444", zoneFill: "rgba(239, 68, 68, 0.14)", zoneStroke: "rgba(239, 68, 68, 0.55)", css: "failed" },
  Offline: { color: "#ef4444", zoneFill: "rgba(239, 68, 68, 0.12)", zoneStroke: "rgba(239, 68, 68, 0.45)", css: "offline" },
};

const state = {
  fields: [],
  activeField: null,
  registeredNodes: [],
  selectedNodeId: null,
  isCollecting: false,
  lastAreaAcres: 1.0,
  lastEstimatedNodes: 5,
  lastSideMetres: Math.sqrt(SQM_PER_ACRE),
};

const el = {
  areaInput: document.getElementById("fcAreaInput"),
  areaUnit: document.getElementById("fcAreaUnit"),
  resetBtn: document.getElementById("fcResetBtn"),
  densityInput: document.getElementById("fcDensityInput"),
  validationError: document.getElementById("fcValidationError"),

  eqAcres: document.getElementById("fcEqAcres"),
  eqHectares: document.getElementById("fcEqHectares"),
  eqSqm: document.getElementById("fcEqSqm"),
  eqSqft: document.getElementById("fcEqSqft"),

  summaryAcres: document.getElementById("fcSummaryAcres"),
  summaryEquiv: document.getElementById("fcSummaryEquiv"),
  summaryNodes: document.getElementById("fcSummaryNodes"),
  summaryFormula: document.getElementById("fcSummaryFormula"),
  summaryDensity: document.getElementById("fcSummaryDensity"),
  summaryDimensions: document.getElementById("fcSummaryDimensions"),

  vizBadge: document.getElementById("fcVizBadge"),
  vizCapNotice: document.getElementById("fcVizCapNotice"),
  fieldSvg: document.getElementById("fcFieldSvg"),
  nodeInspector: document.getElementById("fcNodeInspector"),
  summaryText: document.getElementById("fcDeploymentSummaryText"),
  disclaimerText: document.getElementById("fcDisclaimerText"),

  fieldName: document.getElementById("fcFieldName"),
  locationName: document.getElementById("fcLocationName"),
  latitude: document.getElementById("fcLatitude"),
  longitude: document.getElementById("fcLongitude"),
  savePlanBtn: document.getElementById("fcSavePlanBtn"),
  saveStatus: document.getElementById("fcSaveStatus"),
  savedList: document.getElementById("fcSavedPlansList"),
  savedCount: document.getElementById("fcSavedCount"),

  colFieldSelect: document.getElementById("fcCollectionFieldSelect"),
  telemetryMode: document.getElementById("fcTelemetryMode"),
  modeBanner: document.getElementById("fcModeBanner"),
  syncNodesBtn: document.getElementById("fcSyncNodesBtn"),
  addNodeBtn: document.getElementById("fcAddNodeBtn"),

  colFieldName: document.getElementById("fcColFieldName"),
  colFieldArea: document.getElementById("fcColFieldArea"),
  colTotalNodes: document.getElementById("fcColTotalNodes"),
  colFetched: document.getElementById("fcColFetched"),
  colFailed: document.getElementById("fcColFailed"),
  colPending: document.getElementById("fcColPending"),
  colProgressLabel: document.getElementById("fcColProgressLabel"),
  colProgressPct: document.getElementById("fcColProgressPct"),
  colProgressBar: document.getElementById("fcColProgressBar"),

  fetchFieldDataBtn: document.getElementById("fcFetchFieldDataBtn"),
  retryFailedBtn: document.getElementById("fcRetryFailedBtn"),
  fetchAllAgainBtn: document.getElementById("fcFetchAllAgainBtn"),
  clearCollectionBtn: document.getElementById("fcClearCollectionBtn"),

  analysisPanel: document.getElementById("fcFieldAnalysisPanel"),
  analysisFreshness: document.getElementById("fcAnalysisFreshness"),
  analysisMetrics: document.getElementById("fcAnalysisMetrics"),
  analysisAttention: document.getElementById("fcAnalysisAttention"),
  analysisThresholdsNote: document.getElementById("fcAnalysisThresholdsNote"),

  nodeCardsGrid: document.getElementById("fcNodeCardsGrid"),
  nodeHistoryBox: document.getElementById("fcNodeHistoryBox"),
};

function escapeText(str) {
  return String(str ?? "").replace(/[<>&"]/g, "");
}

function formatTrimmed(num, maxDecimals = 4) {
  if (!Number.isFinite(num)) return "0";
  return Number(num.toFixed(maxDecimals)).toString();
}

function formatLocale(num, maxDecimals = 2) {
  if (!Number.isFinite(num)) return "0";
  return Number(num.toFixed(maxDecimals)).toLocaleString(undefined, {
    maximumFractionDigits: maxDecimals,
  });
}

function convertToAcres(value, unit) {
  const meta = UNIT_META[unit];
  return meta ? meta.toAcres(value) : NaN;
}

function calculateEstimatedNodes(areaAcres, densityPerAcre) {
  return Math.max(1, Math.ceil(areaAcres * densityPerAcre - EPSILON));
}

function showValidationError(message) {
  if (message) {
    el.validationError.textContent = message;
    el.validationError.classList.remove("hidden");
  } else {
    el.validationError.textContent = "";
    el.validationError.classList.add("hidden");
  }
}

function updatePresetHighlight(areaAcres) {
  document.querySelectorAll(".fc-preset-btn").forEach((btn) => {
    const presetAcres = parseFloat(btn.dataset.acres);
    btn.classList.toggle("active", Math.abs(areaAcres - presetAcres) < 1e-6);
  });
}

function syncEquivalentInputs(areaAcres, skipId = null) {
  if (skipId !== "fcEqAcres") el.eqAcres.value = formatTrimmed(areaAcres, 4);
  if (skipId !== "fcEqHectares") el.eqHectares.value = formatTrimmed(areaAcres * HA_PER_ACRE, 4);
  if (skipId !== "fcEqSqm") el.eqSqm.value = formatTrimmed(areaAcres * SQM_PER_ACRE, 2);
  if (skipId !== "fcEqSqft") el.eqSqft.value = formatTrimmed(areaAcres * SQFT_PER_ACRE, 2);
}

function computeNodePositions(nodeCount, bounds) {
  const { x, y, width, height } = bounds;
  if (nodeCount <= 0) return [];

  if (nodeCount === 5) {
    const cx = x + width / 2;
    const cy = y + height / 2;
    const dx = width * 0.27;
    const dy = height * 0.27;
    return [
      { id: 1, x: cx, y: cy },
      { id: 2, x: cx - dx, y: cy - dy },
      { id: 3, x: cx + dx, y: cy - dy },
      { id: 4, x: cx - dx, y: cy + dy },
      { id: 5, x: cx + dx, y: cy + dy },
    ];
  }

  if (nodeCount === 1) {
    return [{ id: 1, x: x + width / 2, y: y + height / 2 }];
  }

  const aspect = width / height;
  const cols = Math.max(1, Math.ceil(Math.sqrt(nodeCount * aspect)));
  const rows = Math.max(1, Math.ceil(nodeCount / cols));
  const padX = Math.min(48, width / (cols + 1));
  const padY = Math.min(42, height / (rows + 1));
  const usableW = Math.max(20, width - padX * 2);
  const usableH = Math.max(20, height - padY * 2);

  const positions = [];
  let idx = 0;
  for (let r = 0; r < rows; r++) {
    const remaining = nodeCount - idx;
    const rowCols = Math.min(cols, remaining);
    const rowY = rows === 1 ? y + height / 2 : y + padY + (r / (rows - 1)) * usableH;

    for (let c = 0; c < rowCols; c++) {
      const colX = rowCols === 1 ? x + width / 2 : x + padX + (c / (rowCols - 1)) * usableW;
      idx += 1;
      positions.push({ id: idx, x: colX, y: rowY });
    }
  }
  return positions;
}

function renderFieldSvg(areaAcres, estimatedNodes, sideMetres) {
  const svg = el.fieldSvg;
  const plot = { x: 64, y: 46, width: 512, height: 320 };
  const useRegistered = state.registeredNodes.length > 0;
  const totalMarkers = useRegistered ? state.registeredNodes.length : estimatedNodes;
  const renderCount = Math.min(totalMarkers, MAX_RENDERED_NODES);
  const positions = computeNodePositions(renderCount, plot);

  const zoneRadius = renderCount <= 5 ? 36 : Math.max(10, Math.min(28, 170 / Math.sqrt(renderCount)));
  const markerRadius = renderCount <= 12 ? 13 : Math.max(6, Math.min(11, 80 / Math.sqrt(renderCount)));
  const showNumbers = renderCount <= 60;

  let gridLines = "";
  for (let i = 1; i < 4; i++) {
    const gx = plot.x + (plot.width / 4) * i;
    const gy = plot.y + (plot.height / 4) * i;
    gridLines += `<line x1="${gx}" y1="${plot.y}" x2="${gx}" y2="${plot.y + plot.height}" stroke="rgba(255,255,255,0.06)" stroke-width="1" />`;
    gridLines += `<line x1="${plot.x}" y1="${gy}" x2="${plot.x + plot.width}" y2="${gy}" stroke="rgba(255,255,255,0.06)" stroke-width="1" />`;
  }

  const markersSvg = positions
    .map((p, idx) => {
      const regNode = useRegistered ? state.registeredNodes[idx] : null;
      const status = regNode ? regNode.fetch_status : "Fetched";
      const st = STATUS_STYLE[status] || STATUS_STYLE.Pending;
      const isSelected = regNode && state.selectedNodeId === regNode.node_id;
      const nodeLabel = regNode ? regNode.node_id : `Node ${p.id}`;
      const zoneLabel = regNode ? regNode.zone_name : `Zone ${p.id}`;
      const numText = regNode ? regNode.node_id.replace(/^AGRI-/, "") : p.id;
      const ringStroke = isSelected ? "#ffffff" : "#ecfdf5";
      const ringWidth = isSelected ? 2.5 : 1.5;

      const labelSvg = showNumbers
        ? `<text x="${p.x}" y="${p.y + 3.2}" text-anchor="middle" fill="#0f172a" font-size="${markerRadius > 10 ? 8.5 : 7}" font-weight="800" font-family="Inter, sans-serif">${escapeText(numText)}</text>`
        : "";

      const idCaption = renderCount <= 15 && regNode
        ? `<text x="${p.x}" y="${p.y + markerRadius + 12}" text-anchor="middle" fill="#cbd5e1" font-size="9.5" font-weight="600" font-family="Inter, sans-serif">${escapeText(regNode.node_id)}</text>`
        : "";

      const pulseCircle = status === "Fetching"
        ? `<circle cx="${p.x}" cy="${p.y}" r="${zoneRadius * 0.72}" fill="none" stroke="#38bdf8" stroke-width="2" stroke-opacity="0.8">
             <animate attributeName="r" values="${markerRadius};${zoneRadius}" dur="0.9s" repeatCount="indefinite" />
             <animate attributeName="stroke-opacity" values="0.9;0.1" dur="0.9s" repeatCount="indefinite" />
           </circle>`
        : "";

      return `
        <g class="fc-node-marker" data-node-id="${regNode ? escapeText(regNode.node_id) : ""}" style="cursor: ${regNode ? "pointer" : "default"};">
          <title>${escapeText(nodeLabel)} (${escapeText(zoneLabel)}) — Status: ${escapeText(status)}</title>
          <circle cx="${p.x}" cy="${p.y}" r="${zoneRadius}" fill="${st.zoneFill}" stroke="${st.zoneStroke}" stroke-width="1" stroke-dasharray="3 3" />
          ${pulseCircle}
          <circle cx="${p.x}" cy="${p.y}" r="${markerRadius}" fill="${st.color}" stroke="${ringStroke}" stroke-width="${ringWidth}" />
          ${labelSvg}
          ${idCaption}
        </g>
      `;
    })
    .join("");

  const fieldTitle = (state.activeField ? state.activeField.field_name : el.fieldName.value.trim()) || "Conceptual Field Plot";
  const sideLabel = `~${formatLocale(sideMetres, 1)} m (approx. square side)`;

  svg.innerHTML = `
    <defs>
      <pattern id="soilDots" width="24" height="24" patternUnits="userSpaceOnUse">
        <circle cx="12" cy="12" r="1" fill="rgba(148, 163, 184, 0.14)" />
      </pattern>
    </defs>

    <rect x="${plot.x}" y="${plot.y}" width="${plot.width}" height="${plot.height}" rx="12" fill="url(#soilDots)" stroke="rgba(14, 165, 233, 0.75)" stroke-width="2" stroke-dasharray="8 5" />
    ${gridLines}

    <text x="${plot.x + plot.width / 2}" y="26" text-anchor="middle" fill="#e2e8f0" font-size="13" font-weight="700" font-family="Space Grotesk, sans-serif">
      ${escapeText(fieldTitle)} · ${formatLocale(areaAcres, 3)} ${Math.abs(areaAcres - 1) < 1e-6 ? "acre" : "acres"}
    </text>

    <line x1="${plot.x}" y1="${plot.y + plot.height + 20}" x2="${plot.x + plot.width}" y2="${plot.y + plot.height + 20}" stroke="rgba(148, 163, 184, 0.45)" stroke-width="1" />
    <text x="${plot.x + plot.width / 2}" y="${plot.y + plot.height + 38}" text-anchor="middle" fill="#94a3b8" font-size="11.5" font-family="Inter, sans-serif">
      ${escapeText(sideLabel)}
    </text>

    ${markersSvg}
  `;

  svg.querySelectorAll("[data-node-id]").forEach((nodeEl) => {
    const nid = nodeEl.getAttribute("data-node-id");
    if (nid) {
      nodeEl.addEventListener("click", () => selectNode(nid));
    }
  });

  if (totalMarkers > MAX_RENDERED_NODES) {
    el.vizCapNotice.textContent = `Displaying ${MAX_RENDERED_NODES} representative markers out of ${totalMarkers.toLocaleString()} nodes for visual clarity.`;
    el.vizCapNotice.classList.remove("hidden");
  } else {
    el.vizCapNotice.classList.add("hidden");
  }
}

function updateUI(sourceId = null) {
  const rawArea = parseFloat(el.areaInput.value);
  const unit = el.areaUnit.value;
  const density = parseFloat(el.densityInput.value);

  if (!Number.isFinite(rawArea) || rawArea <= 0) {
    showValidationError("Please enter a valid field area greater than zero.");
    return;
  }
  if (!Number.isFinite(density) || density <= 0 || density > 50) {
    showValidationError("Deployment density must be between 1 and 50 nodes per acre.");
    return;
  }

  const areaAcres = convertToAcres(rawArea, unit);
  if (!Number.isFinite(areaAcres) || areaAcres > MAX_ACRES_LIMIT) {
    showValidationError(`Field area exceeds the maximum planning limit of ${MAX_ACRES_LIMIT.toLocaleString()} acres.`);
    return;
  }

  showValidationError("");

  const areaSqm = areaAcres * SQM_PER_ACRE;
  const areaHa = areaAcres * HA_PER_ACRE;
  const sideMetres = Math.sqrt(areaSqm);
  const estimatedNodes = calculateEstimatedNodes(areaAcres, density);

  state.lastAreaAcres = areaAcres;
  state.lastEstimatedNodes = estimatedNodes;
  state.lastSideMetres = sideMetres;

  syncEquivalentInputs(areaAcres, sourceId);
  updatePresetHighlight(areaAcres);

  el.summaryAcres.textContent = formatLocale(areaAcres, 4);
  el.summaryEquiv.textContent = `${formatLocale(areaHa, 4)} ha · ${formatLocale(areaSqm, 2)} m²`;
  el.summaryNodes.textContent = estimatedNodes.toLocaleString();
  el.summaryFormula.textContent = `Ceil(${formatTrimmed(areaAcres, 4)} × ${formatTrimmed(density, 2)}) planning estimate`;
  el.summaryDensity.textContent = `${formatTrimmed(density, 2)} / acre`;
  el.summaryDimensions.textContent = `${formatLocale(sideMetres, 1)} × ${formatLocale(sideMetres, 1)} m`;

  const displayCount = state.registeredNodes.length > 0 ? state.registeredNodes.length : estimatedNodes;
  const nodeWord = displayCount === 1 ? "node" : "nodes";
  el.vizBadge.textContent = `${formatLocale(areaAcres, 3)} ${Math.abs(areaAcres - 1) < 1e-6 ? "acre" : "acres"} · ${displayCount.toLocaleString()} ${nodeWord}`;

  const unitMeta = UNIT_META[unit];
  const unitWord = Math.abs(rawArea - 1) < 1e-9 ? unitMeta.singular : unitMeta.plural;
  const formattedArea = formatTrimmed(rawArea, unitMeta.decimals);
  const formattedDensity = formatTrimmed(density, 2);
  const estWord = estimatedNodes === 1 ? "node" : "nodes";

  el.summaryText.textContent =
    `Your field area is ${formattedArea} ${unitWord}. Based on the current deployment configuration of ${formattedDensity} sensor nodes per acre, ` +
    `AgriSense estimates ${estimatedNodes.toLocaleString()} monitoring ${estWord} for this field. ` +
    `This configuration is intended to distribute monitoring across representative sections of the field. ` +
    `Actual placement should be adjusted based on soil variability, crop root zone, irrigation layout and field conditions.`;

  el.disclaimerText.textContent =
    `Sensor quantity is an initial planning estimate based on a configurable deployment density of ${formattedDensity} monitoring nodes per acre. ` +
    `Actual requirements depend on soil variability, crop type, irrigation practices, terrain, sensor depth and field conditions. ` +
    `This estimate does not represent a scientifically validated coverage guarantee.`;

  renderFieldSvg(areaAcres, estimatedNodes, sideMetres);
}

function handleEquivalentInput(unit, inputEl) {
  const val = parseFloat(inputEl.value);
  if (!Number.isFinite(val) || val <= 0) {
    showValidationError("Please enter a valid field area greater than zero.");
    return;
  }
  const acres = convertToAcres(val, unit);
  if (!Number.isFinite(acres) || acres > MAX_ACRES_LIMIT) {
    showValidationError(`Field area exceeds the maximum planning limit of ${MAX_ACRES_LIMIT.toLocaleString()} acres.`);
    return;
  }
  el.areaUnit.value = unit;
  el.areaInput.value = formatTrimmed(val, UNIT_META[unit].decimals);
  updateUI(inputEl.id);
}

/* ── Node Metric Formatting & Inspector ─────────────────── */
function createMetricCell(label, value, unit = "") {
  const cell = document.createElement("div");
  cell.className = "fc-metric-cell";
  const nameEl = document.createElement("div");
  nameEl.className = "fc-metric-name";
  nameEl.textContent = label;
  const valEl = document.createElement("div");
  if (value === null || value === undefined || value === "") {
    valEl.className = "fc-metric-val missing";
    valEl.textContent = "Not measured";
  } else {
    valEl.className = "fc-metric-val";
    valEl.textContent = unit ? `${value} ${unit}` : String(value);
  }
  cell.appendChild(nameEl);
  cell.appendChild(valEl);
  return cell;
}

function selectNode(nodeId) {
  state.selectedNodeId = nodeId;
  renderNodeCards();
  renderFieldSvg(state.lastAreaAcres, state.lastEstimatedNodes, state.lastSideMetres);

  const node = state.registeredNodes.find((n) => n.node_id === nodeId);
  if (!node) {
    el.nodeInspector.classList.add("hidden");
    return;
  }

  el.nodeInspector.classList.remove("hidden");
  el.nodeInspector.innerHTML = "";

  const header = document.createElement("div");
  header.style.cssText = "display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 10px;";
  const title = document.createElement("div");
  title.style.cssText = "font-weight: 700; color: #fff;";
  title.textContent = `${node.node_id} — ${node.zone_name} (${node.fetch_status})`;
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "btn-outline";
  closeBtn.style.cssText = "padding: 4px 10px; font-size: 0.75rem;";
  closeBtn.textContent = "Close";
  closeBtn.addEventListener("click", () => {
    state.selectedNodeId = null;
    el.nodeInspector.classList.add("hidden");
    renderNodeCards();
    renderFieldSvg(state.lastAreaAcres, state.lastEstimatedNodes, state.lastSideMetres);
  });
  header.appendChild(title);
  header.appendChild(closeBtn);
  el.nodeInspector.appendChild(header);

  if (!node.reading) {
    const empty = document.createElement("div");
    empty.style.cssText = "font-size: 0.84rem; color: var(--text-muted);";
    empty.textContent = node.reason || "No reading collected yet. Run Fetch Field Data to retrieve telemetry for this node.";
    el.nodeInspector.appendChild(empty);
    return;
  }

  const r = node.reading;
  const grid = document.createElement("div");
  grid.className = "fc-metrics-grid";
  grid.style.gridTemplateColumns = "repeat(4, 1fr)";
  grid.appendChild(createMetricCell("Moisture", r.moisture, "%"));
  grid.appendChild(createMetricCell("Temperature", r.temperature, "°C"));
  grid.appendChild(createMetricCell("Humidity", r.humidity, "%"));
  grid.appendChild(createMetricCell("MQ-135", r.mq135, "PPM"));
  grid.appendChild(createMetricCell("Nitrogen (N)", r.nitrogen, "kg/ha"));
  grid.appendChild(createMetricCell("Phosphorus (P)", r.phosphorus, "kg/ha"));
  grid.appendChild(createMetricCell("Potassium (K)", r.potassium, "kg/ha"));
  grid.appendChild(createMetricCell("Soil pH", r.ph, ""));
  el.nodeInspector.appendChild(grid);

  const meta = document.createElement("div");
  meta.style.cssText = "margin-top: 8px; font-size: 0.78rem; color: var(--text-muted);";
  meta.textContent = `Source: ${r.reading_source === "hardware" ? "Hardware" : "Simulated (Demo)"} · Timestamp: ${r.timestamp || "—"}`;
  el.nodeInspector.appendChild(meta);
}

/* ── Collection Stats, Cards & Sequential Scanner ──────── */
function updateCollectionStats() {
  const total = state.registeredNodes.length;
  const fetched = state.registeredNodes.filter((n) => n.fetch_status === "Fetched").length;
  const stale = state.registeredNodes.filter((n) => n.fetch_status === "Stale Data").length;
  const failed = state.registeredNodes.filter((n) => n.fetch_status === "Failed" || n.fetch_status === "Offline").length;
  const pending = state.registeredNodes.filter((n) => n.fetch_status === "Pending" || n.fetch_status === "Fetching").length;
  const processed = total - pending;
  const pct = total > 0 ? Math.round((processed / total) * 100) : 0;

  if (state.activeField) {
    el.colFieldName.textContent = state.activeField.field_name;
    el.colFieldArea.textContent = `${Number(state.activeField.area_acres).toFixed(2)} ac`;
  }
  el.colTotalNodes.textContent = total;
  el.colFetched.textContent = fetched + (stale > 0 ? ` (+${stale} stale)` : "");
  el.colFailed.textContent = failed;
  el.colPending.textContent = pending;
  el.colProgressPct.textContent = `${processed} / ${total} (${pct}%)`;
  el.colProgressBar.style.width = `${pct}%`;

  const hasRetryable = failed + stale > 0;
  el.retryFailedBtn.disabled = state.isCollecting || !hasRetryable;
  el.fetchFieldDataBtn.disabled = state.isCollecting || total === 0;
  el.fetchAllAgainBtn.disabled = state.isCollecting || total === 0;
  el.clearCollectionBtn.disabled = state.isCollecting;
  el.colFieldSelect.disabled = state.isCollecting;
  el.syncNodesBtn.disabled = state.isCollecting;
  el.addNodeBtn.disabled = state.isCollecting;
}

function renderNodeCards() {
  const grid = el.nodeCardsGrid;
  grid.innerHTML = "";

  if (state.registeredNodes.length === 0) {
    const empty = document.createElement("div");
    empty.style.cssText = "color: var(--text-muted); font-size: 0.9rem;";
    empty.textContent = "No sensor nodes registered on this field yet.";
    grid.appendChild(empty);
    updateCollectionStats();
    return;
  }

  state.registeredNodes.forEach((node) => {
    const st = STATUS_STYLE[node.fetch_status] || STATUS_STYLE.Pending;
    const card = document.createElement("div");
    card.className = `fc-node-card is-${st.css}${state.selectedNodeId === node.node_id ? " is-selected" : ""}`;
    card.id = `node-card-${node.node_id}`;

    // Header row
    const top = document.createElement("div");
    top.style.cssText = "display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;";

    const idWrap = document.createElement("div");
    const idTitle = document.createElement("div");
    idTitle.style.cssText = "font-family: 'Space Grotesk', sans-serif; font-weight: 700; color: #fff; font-size: 1.05rem;";
    idTitle.textContent = node.node_id;
    const zoneSub = document.createElement("div");
    zoneSub.style.cssText = "font-size: 0.78rem; color: var(--text-muted);";
    zoneSub.textContent = `${node.zone_name} · ${node.node_name}`;
    idWrap.appendChild(idTitle);
    idWrap.appendChild(zoneSub);

    const badgeWrap = document.createElement("div");
    badgeWrap.style.cssText = "display: flex; flex-direction: column; align-items: flex-end; gap: 4px;";
    const badge = document.createElement("span");
    badge.className = `fc-status-badge ${st.css}`;
    badge.textContent = node.fetch_status === "Fetching" ? "Fetching Data..." : node.fetch_status;
    badgeWrap.appendChild(badge);

    if (node.reading && node.reading.reading_source) {
      const srcPill = document.createElement("span");
      const srcClass = node.reading.reading_source === "hardware" ? "hardware" : "simulated";
      srcPill.className = `fc-source-pill ${srcClass}`;
      srcPill.textContent = srcClass === "hardware" ? "Hardware" : "Simulated";
      badgeWrap.appendChild(srcPill);
    }

    top.appendChild(idWrap);
    top.appendChild(badgeWrap);
    card.appendChild(top);

    // Fetching scan animation
    if (node.fetch_status === "Fetching") {
      const scanBar = document.createElement("div");
      scanBar.className = "fc-scan-bar";
      card.appendChild(scanBar);
    }

    // Metrics grid
    const r = node.reading || {};
    const metrics = document.createElement("div");
    metrics.className = "fc-metrics-grid";
    metrics.appendChild(createMetricCell("Soil Moisture", r.moisture, "%"));
    metrics.appendChild(createMetricCell("Temperature", r.temperature, "°C"));
    metrics.appendChild(createMetricCell("Humidity", r.humidity, "%"));
    metrics.appendChild(createMetricCell("MQ-135", r.mq135, "PPM"));
    metrics.appendChild(createMetricCell("Nitrogen (N)", r.nitrogen, "kg/ha"));
    metrics.appendChild(createMetricCell("Phosphorus (P)", r.phosphorus, "kg/ha"));
    metrics.appendChild(createMetricCell("Potassium (K)", r.potassium, "kg/ha"));
    metrics.appendChild(createMetricCell("Soil pH", r.ph, ""));
    card.appendChild(metrics);

    if (node.reason) {
      const reasonEl = document.createElement("div");
      reasonEl.style.cssText = "font-size: 0.78rem; color: #fca5a5;";
      reasonEl.textContent = node.reason;
      card.appendChild(reasonEl);
    }

    // Footer row (timestamp + actions)
    const footer = document.createElement("div");
    footer.style.cssText = "display: flex; justify-content: space-between; align-items: center; gap: 8px; padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.06);";

    const tsEl = document.createElement("span");
    tsEl.style.cssText = "font-size: 0.74rem; color: var(--text-muted);";
    tsEl.textContent = r.timestamp ? `Last: ${r.timestamp}` : "Last: —";

    const actions = document.createElement("div");
    actions.style.cssText = "display: flex; gap: 6px;";

    const retryBtn = document.createElement("button");
    retryBtn.type = "button";
    retryBtn.className = "btn-outline";
    retryBtn.style.cssText = "padding: 4px 9px; font-size: 0.74rem;";
    retryBtn.textContent = (node.fetch_status === "Failed" || node.fetch_status === "Offline") ? "Retry" : "Fetch";
    retryBtn.disabled = state.isCollecting;
    retryBtn.addEventListener("click", () => runSequentialCollection([node]));

    const histBtn = document.createElement("button");
    histBtn.type = "button";
    histBtn.className = "btn-outline";
    histBtn.style.cssText = "padding: 4px 9px; font-size: 0.74rem;";
    histBtn.textContent = "History";
    histBtn.addEventListener("click", () => loadNodeHistory(node.node_id));

    actions.appendChild(retryBtn);
    actions.appendChild(histBtn);
    footer.appendChild(tsEl);
    footer.appendChild(actions);
    card.appendChild(footer);

    grid.appendChild(card);
  });

  updateCollectionStats();
}

async function fetchSingleNodeWithTimeout(node) {
  const simulate = el.telemetryMode.value === "simulate";
  const fieldId = state.activeField ? state.activeField.id : "";
  const url = `/api/nodes/${encodeURIComponent(node.node_id)}/latest?field_id=${encodeURIComponent(fieldId)}&simulate=${simulate ? 1 : 0}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  try {
    const res = await fetch(url, { signal: controller.signal });
    clearTimeout(timer);
    if (res.status === 401) {
      window.location.href = "/login";
      return null;
    }
    const json = await res.json();
    if (!res.ok || json.status !== "ok") {
      return { fetch_status: "Failed", reading: null, reason: json.message || `HTTP ${res.status}` };
    }
    return {
      fetch_status: json.fetch_status || "Fetched",
      reading: json.reading || null,
      reason: json.reason || null,
      is_stale: Boolean(json.is_stale),
      age_seconds: json.age_seconds,
    };
  } catch (err) {
    clearTimeout(timer);
    const reason = err.name === "AbortError" ? "Request timed out" : "Network error / no response";
    return { fetch_status: "Failed", reading: null, reason };
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function runSequentialCollection(targetNodes) {
  if (state.isCollecting || !targetNodes || targetNodes.length === 0) return;

  state.isCollecting = true;
  el.analysisPanel.classList.add("hidden");
  updateCollectionStats();

  for (let i = 0; i < targetNodes.length; i++) {
    const node = targetNodes[i];
    node.fetch_status = "Fetching";
    node.reason = null;
    el.colProgressLabel.textContent = `Scanning ${node.node_id} (${i + 1} of ${targetNodes.length})...`;

    renderNodeCards();
    renderFieldSvg(state.lastAreaAcres, state.lastEstimatedNodes, state.lastSideMetres);

    const outcome = await fetchSingleNodeWithTimeout(node);
    if (!outcome) {
      state.isCollecting = false;
      updateCollectionStats();
      return;
    }

    node.fetch_status = outcome.fetch_status;
    node.reading = outcome.reading;
    node.reason = outcome.reason;
    node.is_stale = outcome.is_stale;
    node.age_seconds = outcome.age_seconds;

    renderNodeCards();
    renderFieldSvg(state.lastAreaAcres, state.lastEstimatedNodes, state.lastSideMetres);
    if (state.selectedNodeId === node.node_id) {
      selectNode(node.node_id);
    }

    if (i < targetNodes.length - 1) {
      await sleep(SEQUENTIAL_STEP_DELAY_MS);
    }
  }

  state.isCollecting = false;
  el.colProgressLabel.textContent = `Sequential scan complete (${targetNodes.length} nodes processed).`;
  updateCollectionStats();
  await updateFieldAnalysisSummary();
}

async function updateFieldAnalysisSummary() {
  if (!state.activeField) return;
  try {
    const res = await fetch(`/api/fields/${state.activeField.id}/summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        node_results: state.registeredNodes.map((n) => ({
          node_id: n.node_id,
          zone_name: n.zone_name,
          fetch_status: n.fetch_status,
          reading: n.reading,
        })),
      }),
    });
    if (!res.ok) return;
    const json = await res.json();
    const s = json.summary;
    if (!s) return;

    el.analysisPanel.classList.remove("hidden");
    el.analysisFreshness.textContent =
      `Connectivity: ${s.node_connectivity_pct}% · Hardware: ${s.data_sources.hardware_nodes} · Simulated: ${s.data_sources.simulated_nodes} · Fresh: ${s.data_freshness.fresh_nodes} · Stale: ${s.data_freshness.stale_nodes}`;

    const avg = s.averages || {};
    const diff = s.moisture_differences || {};
    const fmt = (v, unit) => (v !== null && v !== undefined ? `${v}${unit}` : "N/A");

    el.analysisMetrics.innerHTML = "";
    [
      ["Nodes Fetched", `${s.nodes_fetched} / ${s.total_nodes}`],
      ["Avg Moisture", fmt(avg.moisture, "%")],
      ["Avg Temperature", fmt(avg.temperature, "°C")],
      ["Avg Humidity", fmt(avg.humidity, "%")],
      ["Moisture Zone Spread", diff.spread_pct !== null && diff.spread_pct !== undefined ? `${diff.spread_pct}%` : "N/A"],
      ["Lowest Moisture Zone", diff.min_zone ? `${diff.min_zone} (${diff.min_moisture}%)` : "N/A"],
      ["Highest Moisture Zone", diff.max_zone ? `${diff.max_zone} (${diff.max_moisture}%)` : "N/A"],
      ["Avg pH / MQ-135", `${fmt(avg.ph, "")} / ${fmt(avg.mq135, " PPM")}`],
    ].forEach(([k, v]) => {
      const box = document.createElement("div");
      box.className = "fc-mini-stat";
      const lbl = document.createElement("div");
      lbl.className = "fc-mini-stat-label";
      lbl.textContent = k;
      const val = document.createElement("div");
      val.className = "fc-mini-stat-val";
      val.style.fontSize = "0.98rem";
      val.textContent = v;
      box.appendChild(lbl);
      box.appendChild(val);
      el.analysisMetrics.appendChild(box);
    });

    const issues = s.zones_needing_attention || [];
    if (issues.length === 0) {
      el.analysisAttention.textContent = "All responding zones are within configured illustrative thresholds.";
      el.analysisAttention.style.color = "#6ee7b7";
    } else {
      el.analysisAttention.style.color = "#fde68a";
      el.analysisAttention.textContent = `Zones needing attention (${issues.length}): ` + issues.map((x) => `${x.node_id} (${x.zone}): ${x.issue}`).join(" · ");
    }

    const th = s.thresholds_used || {};
    el.analysisThresholdsNote.textContent =
      `Configurable illustrative thresholds used — Moisture: ${th.moisture_low}–${th.moisture_high}%, Temp max: ${th.temp_high}°C, pH: ${th.ph_low}–${th.ph_high}, Freshness window: ${th.stale_seconds}s. Missing channels are excluded rather than replaced with zero.`;
  } catch (err) {
    console.error("Failed to generate field analysis summary", err);
  }
}

async function loadNodeHistory(nodeId) {
  try {
    const res = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}/history`);
    if (!res.ok) return;
    const json = await res.json();
    const hist = json.history || [];

    el.nodeHistoryBox.classList.remove("hidden");
    el.nodeHistoryBox.innerHTML = "";

    const head = document.createElement("div");
    head.style.cssText = "display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;";
    const title = document.createElement("strong");
    title.style.color = "#fff";
    title.textContent = `Stored Telemetry History — ${nodeId} (${hist.length} records)`;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "btn-outline";
    close.style.cssText = "padding: 4px 10px; font-size: 0.75rem;";
    close.textContent = "Close";
    close.addEventListener("click", () => el.nodeHistoryBox.classList.add("hidden"));
    head.appendChild(title);
    head.appendChild(close);
    el.nodeHistoryBox.appendChild(head);

    if (hist.length === 0) {
      const p = document.createElement("div");
      p.style.cssText = "font-size: 0.84rem; color: var(--text-muted);";
      p.textContent = "No persisted hardware readings logged for this node yet.";
      el.nodeHistoryBox.appendChild(p);
      return;
    }

    hist.slice(0, 8).forEach((row) => {
      const line = document.createElement("div");
      line.style.cssText = "font-size: 0.8rem; color: #cbd5e1; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.05);";
      line.textContent =
        `${row.timestamp} [${row.reading_source}] — Moisture: ${row.moisture ?? "N/A"}%, Temp: ${row.temperature ?? "N/A"}°C, RH: ${row.humidity ?? "N/A"}%, MQ-135: ${row.mq135 ?? "N/A"} PPM, pH: ${row.ph ?? "N/A"}`;
      el.nodeHistoryBox.appendChild(line);
    });
  } catch (err) {
    console.error("Failed to fetch node history", err);
  }
}

async function loadFieldNodes(fieldId) {
  try {
    const res = await fetch(`/api/fields/${fieldId}/nodes`);
    if (!res.ok) return;
    const json = await res.json();
    state.activeField = json.field;
    state.registeredNodes = (json.nodes || []).map((n) => ({
      ...n,
      fetch_status: "Pending",
      reading: null,
      reason: null,
    }));
    state.selectedNodeId = null;
    el.nodeInspector.classList.add("hidden");
    el.analysisPanel.classList.add("hidden");
    el.nodeHistoryBox.classList.add("hidden");
    el.colProgressLabel.textContent = "Ready for sequential node scan.";

    renderNodeCards();
    renderFieldSvg(state.lastAreaAcres, state.lastEstimatedNodes, state.lastSideMetres);
  } catch (err) {
    console.error("Failed to load field nodes", err);
  }
}

async function loadFields() {
  try {
    const res = await fetch("/api/fields");
    if (!res.ok) return;
    const json = await res.json();
    state.fields = json.fields || [];

    el.colFieldSelect.innerHTML = "";
    state.fields.forEach((f) => {
      const opt = document.createElement("option");
      opt.value = f.id;
      opt.textContent = `${f.field_name} (${Number(f.area_acres).toFixed(2)} ac · est. ${f.estimated_nodes} nodes)`;
      el.colFieldSelect.appendChild(opt);
    });

    if (state.fields.length > 0) {
      await loadFieldNodes(state.fields[0].id);
    }
  } catch (err) {
    console.error("Failed to load fields", err);
  }
}

function clearCollectionDisplay() {
  if (state.isCollecting) return;
  state.registeredNodes.forEach((n) => {
    n.fetch_status = "Pending";
    n.reading = null;
    n.reason = null;
  });
  state.selectedNodeId = null;
  el.nodeInspector.classList.add("hidden");
  el.analysisPanel.classList.add("hidden");
  el.nodeHistoryBox.classList.add("hidden");
  el.colProgressLabel.textContent = "Collection display cleared. Ready to scan.";
  renderNodeCards();
  renderFieldSvg(state.lastAreaAcres, state.lastEstimatedNodes, state.lastSideMetres);
}

/* ── Saved Field Plans ─────────────────────────────────── */
async function fetchSavedPlans() {
  try {
    const res = await fetch("/api/field-plans");
    if (!res.ok) return;
    const json = await res.json();
    const plans = json.plans || [];
    el.savedCount.textContent = `${plans.length} saved`;

    if (plans.length === 0) {
      el.savedList.innerHTML = `<div style="color: var(--text-muted); font-size: 0.88rem;">No saved field plans yet.</div>`;
      return;
    }

    el.savedList.innerHTML = "";
    plans.forEach((plan) => {
      const row = document.createElement("div");
      row.className = "fc-saved-item";

      const infoWrap = document.createElement("div");
      const titleEl = document.createElement("div");
      titleEl.style.cssText = "font-weight: 700; color: #fff; font-size: 0.92rem;";
      const loc = plan.location_name ? ` · ${plan.location_name}` : "";
      titleEl.textContent = `${plan.field_name}${loc}`;

      const subEl = document.createElement("div");
      subEl.style.cssText = "font-size: 0.78rem; color: var(--text-muted);";
      subEl.textContent = `${plan.area_input} ${plan.unit} (${Number(plan.area_acres).toFixed(3)} ac) · ${plan.estimated_nodes} nodes @ ${plan.density_per_acre}/ac`;

      infoWrap.appendChild(titleEl);
      infoWrap.appendChild(subEl);

      const btnWrap = document.createElement("div");
      btnWrap.style.cssText = "display: flex; gap: 8px;";

      const loadBtn = document.createElement("button");
      loadBtn.type = "button";
      loadBtn.className = "btn-outline fc-load-plan";
      loadBtn.style.cssText = "padding: 6px 10px; font-size: 0.76rem;";
      loadBtn.textContent = "Load";

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "btn-outline fc-del-plan";
      delBtn.style.cssText = "padding: 6px 10px; font-size: 0.76rem; color: var(--accent-danger); border-color: rgba(239,68,68,0.3);";
      delBtn.textContent = "Delete";

      btnWrap.appendChild(loadBtn);
      btnWrap.appendChild(delBtn);
      row.appendChild(infoWrap);
      row.appendChild(btnWrap);

      loadBtn.addEventListener("click", async () => {
        el.areaUnit.value = plan.unit;
        el.areaInput.value = plan.area_input;
        el.densityInput.value = plan.density_per_acre;
        el.fieldName.value = plan.field_name || "";
        el.locationName.value = plan.location_name || "";
        el.latitude.value = plan.latitude ?? "";
        el.longitude.value = plan.longitude ?? "";
        el.colFieldSelect.value = String(plan.id);
        updateUI();
        await loadFieldNodes(plan.id);
      });

      delBtn.addEventListener("click", async () => {
        const delRes = await fetch(`/api/field-plans/${plan.id}`, { method: "DELETE" });
        if (delRes.ok) {
          await fetchSavedPlans();
          await loadFields();
        }
      });

      el.savedList.appendChild(row);
    });
  } catch (err) {
    console.error("Failed to load field plans", err);
  }
}

async function saveFieldPlan() {
  const rawArea = parseFloat(el.areaInput.value);
  const density = parseFloat(el.densityInput.value);
  if (!Number.isFinite(rawArea) || rawArea <= 0 || !Number.isFinite(density) || density <= 0) {
    el.saveStatus.style.color = "var(--accent-danger)";
    el.saveStatus.textContent = "Enter a valid positive area and density before saving.";
    return;
  }

  const payload = {
    field_name: el.fieldName.value.trim() || "My Field",
    location_name: el.locationName.value.trim(),
    latitude: el.latitude.value === "" ? null : parseFloat(el.latitude.value),
    longitude: el.longitude.value === "" ? null : parseFloat(el.longitude.value),
    area_input: rawArea,
    unit: el.areaUnit.value,
    density_per_acre: density,
  };

  try {
    const res = await fetch("/api/field-plans", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const json = await res.json();
    if (res.ok && json.status === "ok") {
      el.saveStatus.style.color = "var(--accent-primary)";
      el.saveStatus.textContent = `Saved "${json.plan.field_name}" (${json.plan.estimated_nodes} nodes provisioned).`;
      await fetchSavedPlans();
      await loadFields();
      el.colFieldSelect.value = String(json.plan.id);
      await loadFieldNodes(json.plan.id);
    } else {
      el.saveStatus.style.color = "var(--accent-danger)";
      el.saveStatus.textContent = json.message || "Could not save field plan.";
    }
  } catch (err) {
    console.error("Failed to save plan", err);
    el.saveStatus.style.color = "var(--accent-danger)";
    el.saveStatus.textContent = "Network error while saving field plan.";
  }
}

function resetPlanner() {
  el.areaInput.value = "1";
  el.areaUnit.value = "acres";
  el.densityInput.value = String(DEFAULT_DENSITY);
  el.fieldName.value = "";
  el.locationName.value = "";
  el.latitude.value = "";
  el.longitude.value = "";
  el.saveStatus.textContent = "";
  updateUI();
}

function bindEvents() {
  el.areaInput.addEventListener("input", () => updateUI());
  el.areaUnit.addEventListener("change", () => updateUI());
  el.densityInput.addEventListener("input", () => updateUI());
  el.fieldName.addEventListener("input", () => updateUI());
  el.resetBtn.addEventListener("click", resetPlanner);
  el.savePlanBtn.addEventListener("click", saveFieldPlan);

  el.eqAcres.addEventListener("input", () => handleEquivalentInput("acres", el.eqAcres));
  el.eqHectares.addEventListener("input", () => handleEquivalentInput("hectares", el.eqHectares));
  el.eqSqm.addEventListener("input", () => handleEquivalentInput("sqm", el.eqSqm));
  el.eqSqft.addEventListener("input", () => handleEquivalentInput("sqft", el.eqSqft));

  document.querySelectorAll(".fc-preset-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      el.areaUnit.value = "acres";
      el.areaInput.value = btn.dataset.acres;
      updateUI();
    });
  });

  el.colFieldSelect.addEventListener("change", () => {
    const id = parseInt(el.colFieldSelect.value, 10);
    if (Number.isFinite(id)) loadFieldNodes(id);
  });

  el.telemetryMode.addEventListener("change", () => {
    const isSim = el.telemetryMode.value === "simulate";
    el.modeBanner.innerHTML = isSim
      ? "Simulation Mode Active — multi-node readings are simulated for demonstration and clearly tagged <strong>Simulated</strong>. Switch to <strong>Live / Stored Telemetry</strong> to read real ESP32 packets posted via <code>/api/sensor-data</code>."
      : "Live / Stored Telemetry Mode — reads real persisted packets posted by ESP32 nodes (<code>node_id</code>) to <code>/api/sensor-data</code>. Nodes without recent telemetry report <strong>Offline</strong> or <strong>Stale Data</strong>.";
  });

  el.syncNodesBtn.addEventListener("click", async () => {
    if (!state.activeField || state.isCollecting) return;
    const res = await fetch(`/api/fields/${state.activeField.id}/nodes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sync_count: state.lastEstimatedNodes }),
    });
    if (res.ok) await loadFieldNodes(state.activeField.id);
  });

  el.addNodeBtn.addEventListener("click", async () => {
    if (!state.activeField || state.isCollecting) return;
    const res = await fetch(`/api/fields/${state.activeField.id}/nodes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (res.ok) await loadFieldNodes(state.activeField.id);
  });

  el.fetchFieldDataBtn.addEventListener("click", () => {
    const pendingOrAll = state.registeredNodes.filter((n) => n.fetch_status === "Pending");
    runSequentialCollection(pendingOrAll.length > 0 ? pendingOrAll : state.registeredNodes);
  });

  el.retryFailedBtn.addEventListener("click", () => {
    const retryNodes = state.registeredNodes.filter((n) =>
      ["Failed", "Offline", "Stale Data"].includes(n.fetch_status)
    );
    runSequentialCollection(retryNodes);
  });

  el.fetchAllAgainBtn.addEventListener("click", () => {
    runSequentialCollection(state.registeredNodes);
  });

  el.clearCollectionBtn.addEventListener("click", clearCollectionDisplay);
}

async function boot() {
  bindEvents();
  updateUI();
  await fetchSavedPlans();
  await loadFields();
}

document.readyState === "loading"
  ? document.addEventListener("DOMContentLoaded", boot)
  : boot();
