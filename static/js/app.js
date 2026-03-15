(function () {
  const healthStatusEl = document.getElementById("healthStatus");
  const sourceSummaryEl = document.getElementById("sourceSummary");
  const requestSummaryEl = document.getElementById("requestSummary");
  const recentWlrListEl = document.getElementById("recentWlrList");
  const uploadFormEl = document.getElementById("uploadForm");
  const uploadInputEl = document.getElementById("wlrFile");
  const uploadBtnEl = document.getElementById("uploadBtn");
  const uploadResultEl = document.getElementById("uploadResult");
  const refreshSourceBtnEl = document.getElementById("refreshSourceBtn");
  const downloadReportBtnEl = document.getElementById("downloadReportBtn");
  const debugBoxEl = document.getElementById("debugBox");
  const recommendationsStateEl = document.getElementById("recommendationsState");
  const recommendationsTableBodyEl = document.querySelector("#recommendationsTable tbody");
  const conflictsTableBodyEl = document.querySelector("#conflictsTable tbody");
  const mapContainerEl = document.getElementById("map");

  let currentUploadId = null;
  let map = null;
  let mapLayers = [];
  let mapLegend = null;
  let analyzeBtnEl = null;
  let currentEngineVersion = null;
  let currentAnalysisRequest = null;
  const RECENT_WLR_KEY = "uke_recent_wlr_v1";
  const MAX_RECENT_ITEMS = 12;

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function setDebug(label, payload) {
    const text = typeof payload === "string"
      ? payload
      : JSON.stringify(payload, null, 2);
    debugBoxEl.textContent = `${label}\n${text}`;
  }

  function renderRecommendationsState(summary) {
    if (!recommendationsStateEl) {
      return;
    }

    recommendationsStateEl.classList.remove("is-neutral", "is-danger", "is-ok");

    if (!summary) {
      recommendationsStateEl.classList.add("is-neutral");
      recommendationsStateEl.textContent = "Brak wyników analizy.";
      return;
    }

    if (summary.has_accepted) {
      recommendationsStateEl.classList.add("is-ok");
      recommendationsStateEl.textContent = `Znaleziono kanały dopuszczalne: ${summary.accepted_count}. Tabela pokazuje najlepsze warianty.`;
      return;
    }

    recommendationsStateEl.classList.add("is-danger");
    recommendationsStateEl.textContent = "Brak kanału dopuszczalnego w analizowanym planie. Tabela poniżej pokazuje najmniej konfliktowe warianty odrzucone.";
  }

  function setHealthStatusOk(payload) {
    healthStatusEl.textContent = `API: ${payload.status}`;
    healthStatusEl.classList.remove("is-error");
    healthStatusEl.classList.add("is-ok");
    if (payload && payload.engine_version) {
      currentEngineVersion = payload.engine_version;
    }
  }

  function setHealthStatusError(error) {
    healthStatusEl.textContent = `API error: ${error.message}`;
    healthStatusEl.classList.remove("is-ok");
    healthStatusEl.classList.add("is-error");
  }

  function renderSourceSummary(source) {
    const engineVersion = (source && source.engine_version) || currentEngineVersion || "-";
    const items = [
      ["Wersja silnika", engineVersion],
      ["Plik XLSX", source.filename],
      ["Ścieżka", source.full_path],
      ["Arkusz", source.sheet_name],
      ["Wiersze", source.rows_count],
      ["Rozmiar [B]", source.file_size_bytes],
      ["Modyfikacja", source.modified_at],
      ["Łącza duplex", source.duplex_links],
      ["Sparowane rekordy", source.paired_records_count],
      ["Sieroty", source.orphan_records_count],
      ["Plany", source.plans_count],
      ["Pliki planów", source.plan_files_count]
    ];

    sourceSummaryEl.innerHTML = items.map(([key, value]) => `
      <div class="kv-item">
        <span class="kv-key">${escapeHtml(key)}</span>
        <span class="kv-value">${escapeHtml(value)}</span>
      </div>
    `).join("");
  }

  function renderRequestSummary(summary) {
    if (!summary) {
      requestSummaryEl.innerHTML = `
        <div class="kv-item">
          <span class="kv-key">Status</span>
          <span class="kv-value">Brak sparsowanego zapytania</span>
        </div>
      `;
      return;
    }

    const items = [
      ["Upload ID", summary.upload_id || "-"],
      ["Link", summary.link_name || "-"],
      ["Plan", summary.plan_symbol || "-"],
      ["Kanał", summary.requested_channel || "-"],
      ["Pol.", summary.requested_polarization || "-"],
      ["Szerokość [MHz]", summary.channel_width_mhz ?? "-"]
    ];

    requestSummaryEl.innerHTML = items.map(([key, value]) => `
      <div class="kv-item">
        <span class="kv-key">${escapeHtml(key)}</span>
        <span class="kv-value">${escapeHtml(value)}</span>
      </div>
    `).join("");
  }

  function getRecentEntries() {
    try {
      const raw = window.localStorage.getItem(RECENT_WLR_KEY);
      if (!raw) {
        return [];
      }
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (_error) {
      return [];
    }
  }

  function setRecentEntries(entries) {
    window.localStorage.setItem(RECENT_WLR_KEY, JSON.stringify(entries));
  }

  function addRecentEntry(entry) {
    const entries = getRecentEntries().filter((item) => item.upload_id !== entry.upload_id);
    entries.unshift(entry);
    setRecentEntries(entries.slice(0, MAX_RECENT_ITEMS));
    renderRecentEntries();
  }

  function renderRecentEntries() {
    if (!recentWlrListEl) {
      return;
    }
    const entries = getRecentEntries();
    if (entries.length === 0) {
      recentWlrListEl.innerHTML = `<div class="muted">Brak historii analiz.</div>`;
      return;
    }

    recentWlrListEl.innerHTML = entries.map((entry) => `
      <button type="button" class="recent-item" data-upload-id="${escapeHtml(entry.upload_id)}">
        <strong>${escapeHtml(entry.link_name || entry.upload_id)}</strong>
        <span>${escapeHtml(entry.requested_channel || "-")} | ${escapeHtml(entry.requested_polarization || "-")} | ${escapeHtml(entry.analyzed_at || "-")}</span>
      </button>
    `).join("");

    recentWlrListEl.querySelectorAll(".recent-item").forEach((button) => {
      button.addEventListener("click", () => {
        const uploadId = button.getAttribute("data-upload-id");
        if (uploadId) {
          analyzeByUploadId(uploadId);
        }
      });
    });
  }

  function setUploadMessage(text, mode = "muted") {
    uploadResultEl.textContent = text;
    uploadResultEl.classList.remove("muted", "success", "error");
    uploadResultEl.classList.add(mode);
  }

  function ensureAnalyzeButton() {
    if (analyzeBtnEl && document.body.contains(analyzeBtnEl)) {
      return analyzeBtnEl;
    }

    analyzeBtnEl = document.getElementById("analyzeBtn");
    if (analyzeBtnEl) {
      return analyzeBtnEl;
    }

    const buttonRow = uploadFormEl.querySelector(".button-row");
    const targetContainer = buttonRow || uploadFormEl;

    analyzeBtnEl = document.createElement("button");
    analyzeBtnEl.type = "button";
    analyzeBtnEl.id = "analyzeBtn";
    analyzeBtnEl.textContent = "Analizuj WLR";
    analyzeBtnEl.disabled = true;

    targetContainer.appendChild(analyzeBtnEl);
    return analyzeBtnEl;
  }

  function setAnalyzeButtonState(enabled, label) {
    const button = ensureAnalyzeButton();
    button.disabled = !enabled;
    if (label) {
      button.textContent = label;
    }
  }

  function setReportButtonState(enabled, label) {
    if (!downloadReportBtnEl) {
      return;
    }
    downloadReportBtnEl.disabled = !enabled;
    if (label) {
      downloadReportBtnEl.textContent = label;
    }
  }

  function ensureMap() {
    if (!mapContainerEl) {
      return null;
    }

    if (typeof window.L === "undefined") {
      mapContainerEl.innerHTML = "<div class=\"map-placeholder-text\">Leaflet nie jest załadowany.</div>";
      return null;
    }

    if (map) {
      return map;
    }

    map = window.L.map(mapContainerEl).setView([52.1, 19.4], 6);
    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors"
    }).addTo(map);
    if (!mapLegend) {
      mapLegend = window.L.control({ position: "bottomright" });
      mapLegend.onAdd = function onAdd() {
        const div = window.L.DomUtil.create("div", "map-legend");
        div.style.background = "rgba(255,255,255,0.95)";
        div.style.padding = "8px 10px";
        div.style.border = "1px solid #cbd5e1";
        div.style.borderRadius = "8px";
        div.style.boxShadow = "0 2px 8px rgba(15,23,42,0.15)";
        div.style.fontSize = "12px";
        div.style.lineHeight = "1.4";
        div.innerHTML = [
          "<div style=\"font-weight:600; margin-bottom:4px;\">Legenda</div>",
          "<div><span style=\"display:inline-block;width:20px;height:0;border-top:4px solid #1d4ed8;vertical-align:middle;margin-right:6px;\"></span>Link analizowany</div>",
          "<div><span style=\"display:inline-block;width:20px;height:0;border-top:4px solid #dc2626;vertical-align:middle;margin-right:6px;\"></span>Link potencjalnie zakłócający</div>"
        ].join("");
        return div;
      };
      mapLegend.addTo(map);
    }
    return map;
  }

  function clearMapLayers() {
    if (!map) {
      return;
    }
    mapLayers.forEach((layer) => {
      if (map.hasLayer(layer)) {
        map.removeLayer(layer);
      }
    });
    mapLayers = [];
  }

  function featureStyle(feature) {
    const kind = feature?.properties?.feature_type || feature?.properties?.kind;
    const risk = feature?.properties?.risk_level || "";

    if (kind === "requested_link") {
      return { color: "#1d4ed8", weight: 5, opacity: 0.95 };
    }
    if (kind === "conflict_link") {
      if (risk === "red") {
        return { color: "#dc2626", weight: 4, opacity: 0.95 };
      }
      if (risk === "amber") {
        return { color: "#dc2626", weight: 3, opacity: 0.85, dashArray: "6,6" };
      }
      return { color: "#dc2626", weight: 3, opacity: 0.75, dashArray: "4,8" };
    }
    return { color: "#475569", weight: 3 };
  }

  function pointToLayer(feature, latlng) {
    const kind = feature?.properties?.feature_type || feature?.properties?.kind;
    if (kind === "requested_site") {
      return window.L.circleMarker(latlng, {
        radius: 7,
        color: "#1d4ed8",
        fillColor: "#1d4ed8",
        weight: 2,
        fillOpacity: 0.9
      });
    }
    return window.L.circleMarker(latlng, {
      radius: 5,
      color: "#dc2626",
      fillColor: "#dc2626",
      weight: 1,
      fillOpacity: 0.8
    });
  }

  function popupHtml(properties) {
    if (!properties) {
      return "Brak danych";
    }
    const labels = {
      label: "Etykieta",
      site: "Punkt",
      link_id: "Link ID",
      operator_name: "Operator",
      permit_number: "Nr pozwolenia",
      plan_symbol: "Plan",
      polarization: "Polaryzacja",
      same_plan_as_request: "Ten sam plan",
      risk_level: "Ryzyko",
      conflict_type: "Typ konfliktu",
      score: "Score",
      distance_km: "Odległość [km]",
      effective_freq_delta_mhz: "Delta f [MHz]",
      estimated_ci_victim_db: "CI victim [dB]",
      estimated_ci_aggressor_db: "CI aggressor [dB]",
      estimated_degradation_victim_db: "TD victim [dB]",
      estimated_degradation_aggressor_db: "TD aggressor [dB]",
      decision_explanation: "Opis",
      channel_ab: "Kanał A→B",
      channel_ba: "Kanał B→A"
    };

    const orderedKeys = [
      "label",
      "site",
      "link_id",
      "operator_name",
      "permit_number",
      "plan_symbol",
      "polarization",
      "same_plan_as_request",
      "risk_level",
      "conflict_type",
      "score",
      "distance_km",
      "effective_freq_delta_mhz",
      "estimated_ci_victim_db",
      "estimated_ci_aggressor_db",
      "estimated_degradation_victim_db",
      "estimated_degradation_aggressor_db",
      "channel_ab",
      "channel_ba",
      "decision_explanation"
    ];

    const seen = new Set();
    const rows = [];

    orderedKeys.forEach((key) => {
      if (!(key in properties)) {
        return;
      }
      seen.add(key);
      const rawValue = properties[key];
      const value = typeof rawValue === "boolean" ? (rawValue ? "tak" : "nie") : (rawValue ?? "-");
      rows.push(`<div><strong>${escapeHtml(labels[key] || key)}:</strong> ${escapeHtml(value)}</div>`);
    });

    Object.entries(properties).forEach(([key, rawValue]) => {
      if (seen.has(key) || key === "details" || key === "feature_type" || key === "kind") {
        return;
      }
      const value = typeof rawValue === "boolean" ? (rawValue ? "tak" : "nie") : (rawValue ?? "-");
      rows.push(`<div><strong>${escapeHtml(labels[key] || key)}:</strong> ${escapeHtml(value)}</div>`);
    });

    return rows.join("");
  }

  function renderMap(mapSection) {
    const leafletMap = ensureMap();
    if (!leafletMap || !mapSection || !mapSection.features || !Array.isArray(mapSection.features.features)) {
      return;
    }

    clearMapLayers();

    const geoJsonLayer = window.L.geoJSON(mapSection.features, {
      style: featureStyle,
      pointToLayer,
      onEachFeature(feature, layer) {
        layer.bindPopup(popupHtml(feature.properties));
      }
    }).addTo(leafletMap);

    mapLayers.push(geoJsonLayer);

    const bounds = geoJsonLayer.getBounds();
    if (bounds.isValid()) {
      leafletMap.fitBounds(bounds.pad(0.2), { maxZoom: 14 });
    }
  }

  function renderRecommendations(recommendations, summary) {
    renderRecommendationsState(summary || null);

    if (!recommendations || recommendations.length === 0) {
      recommendationsTableBodyEl.innerHTML = `
        <tr>
          <td colspan="9" class="empty-cell">Brak wyników analizy.</td>
        </tr>
      `;
      return;
    }

    recommendationsTableBodyEl.innerHTML = recommendations.slice(0, 10).map((item) => {
      const status = item.status || item.details?.status || "UNKNOWN";
      const reasonText = item.rejection_reasons && item.rejection_reasons.length
        ? item.rejection_reasons.slice(0, 3).join("; ")
        : (item.summary || item.best_explanation || "-");
      const showAsRejectedVariant = summary && !summary.has_accepted;
      const rankLabel = showAsRejectedVariant ? `Wariant ${item.rank}` : item.rank;

      return `
        <tr>
          <td>${escapeHtml(rankLabel)}</td>
          <td>${escapeHtml(item.channel_ab)}</td>
          <td>${escapeHtml(item.channel_ba)}</td>
          <td>${escapeHtml(item.polarization)}</td>
          <td>${escapeHtml(Number(item.score).toFixed(1))}</td>
          <td><strong>${escapeHtml(status)}</strong></td>
          <td>${escapeHtml(item.red_conflicts)}</td>
          <td>${escapeHtml(item.candidate_links_count)}</td>
          <td>${escapeHtml(reasonText)}</td>
        </tr>
      `;
    }).join("");
  }

  function renderConflicts(conflicts) {
    if (!conflicts || conflicts.length === 0) {
      conflictsTableBodyEl.innerHTML = `
        <tr>
          <td colspan="8" class="empty-cell">Brak powodów warunkowych lub odrzuceń.</td>
        </tr>
      `;
      return;
    }

    conflictsTableBodyEl.innerHTML = conflicts.slice(0, 30).map((item) => {
      const status = item.details?.status || item.risk_level || "UNKNOWN";
      const topConflicts = item.details?.top_conflicts || [];
      const topConflictText = topConflicts.length
        ? topConflicts.map((conflict) =>
            `${conflict.link_id} | ${conflict.operator_name || "-"} | ${conflict.risk_level}`
          ).join(" ; ")
        : "-";

      return `
        <tr>
          <td>${escapeHtml(item.link_id)}</td>
          <td>${escapeHtml(status)}</td>
          <td>${escapeHtml(item.channel_ab || "-")}</td>
          <td>${escapeHtml(item.channel_ba || "-")}</td>
          <td>${escapeHtml(item.polarization || "-")}</td>
          <td>${escapeHtml(Number(item.score).toFixed(1))}</td>
          <td>${escapeHtml(item.decision_explanation || "-")}</td>
          <td>${escapeHtml(topConflictText)}</td>
        </tr>
      `;
    }).join("");
  }

  async function loadHealth() {
    try {
      const payload = await ApiClient.getHealth();
      setHealthStatusOk(payload);
      setDebug("GET /api/health", payload);
    } catch (error) {
      setHealthStatusError(error);
      setDebug("GET /api/health ERROR", error.message);
    }
  }

  async function loadSource() {
    sourceSummaryEl.innerHTML = `
      <div class="kv-item">
        <span class="kv-key">Status</span>
        <span class="kv-value">Ładowanie…</span>
      </div>
    `;

    try {
      const payload = await ApiClient.getSource();
      renderSourceSummary(payload);
      setDebug("GET /api/source", payload);
    } catch (error) {
      sourceSummaryEl.innerHTML = `
        <div class="kv-item">
          <span class="kv-key">Błąd</span>
          <span class="kv-value">${escapeHtml(error.message)}</span>
        </div>
      `;
      setDebug("GET /api/source ERROR", error.message);
    }
  }

  async function handleUploadSubmit(event) {
    event.preventDefault();

    const file = uploadInputEl.files && uploadInputEl.files[0];
    if (!file) {
      setUploadMessage("Najpierw wybierz plik .wlr.", "error");
      return;
    }

    uploadBtnEl.disabled = true;
    setAnalyzeButtonState(false, "Analizuj WLR");
    setUploadMessage(`Wysyłanie pliku: ${file.name}`, "muted");

    try {
      const payload = await ApiClient.uploadWlr(file);
      currentUploadId = payload.upload_id || null;

      setUploadMessage(
        `Plik zapisany: ${payload.stored_filename}`,
        payload.parsed ? "success" : "error"
      );

      renderRequestSummary(payload.request_summary || {
        upload_id: payload.upload_id
      });
      renderRecommendations([], null);
      renderConflicts([]);
      clearMapLayers();
      currentAnalysisRequest = null;
      setAnalyzeButtonState(Boolean(currentUploadId && payload.parsed), "Analizuj WLR");
      setReportButtonState(false, "Pobierz PDF");
      setDebug("POST /api/upload-wlr", payload);
    } catch (error) {
      currentUploadId = null;
      currentAnalysisRequest = null;
      setUploadMessage(`Błąd uploadu: ${error.message}`, "error");
      setAnalyzeButtonState(false, "Analizuj WLR");
      setReportButtonState(false, "Pobierz PDF");
      setDebug("POST /api/upload-wlr ERROR", error.message);
    } finally {
      uploadBtnEl.disabled = false;
    }
  }

  async function analyzeByUploadId(uploadId) {
    if (!uploadId) {
      setUploadMessage("Brak upload_id do analizy. Najpierw wyślij plik WLR.", "error");
      return;
    }

    currentUploadId = uploadId;
    setAnalyzeButtonState(false, "Analiza w toku…");
    setUploadMessage(`Uruchamianie analizy dla upload_id=${uploadId}`, "muted");

    try {
      currentAnalysisRequest = {
        upload_id: uploadId,
        radius_km: 30,
        max_links: 500,
        operator_name: "Towerlink Poland Sp. z o.o."
      };
      const payload = await ApiClient.analyzeWlr(currentAnalysisRequest);

      renderRequestSummary(payload.request || { upload_id: uploadId });
      renderRecommendations(payload.recommendations || [], payload.summary || null);
      renderConflicts(payload.conflicts || []);
      renderMap(payload.map);
      addRecentEntry({
        upload_id: uploadId,
        link_name: payload.request?.link_name || null,
        requested_channel: payload.request?.requested_channel || null,
        requested_polarization: payload.request?.requested_polarization || null,
        analyzed_at: new Date().toLocaleString("pl-PL")
      });

      if (payload.summary?.has_accepted) {
        setUploadMessage("Znaleziono co najmniej jeden kanał ACCEPTED.", "success");
      } else {
        setUploadMessage("Nie znaleziono kanału ACCEPTED. Sprawdź CONDITIONAL i REJECTED.", "error");
      }

      setReportButtonState(true, "Pobierz PDF");
      setDebug("POST /api/analyze", payload);
    } catch (error) {
      currentAnalysisRequest = null;
      setReportButtonState(false, "Pobierz PDF");
      setUploadMessage(`Błąd analizy: ${error.message}`, "error");
      setDebug("POST /api/analyze ERROR", error.message);
    } finally {
      setAnalyzeButtonState(true, "Analizuj WLR");
    }
  }

  async function handleAnalyzeClick() {
    return analyzeByUploadId(currentUploadId);
  }

  async function handleDownloadReportClick() {
    if (!currentAnalysisRequest) {
      setUploadMessage("Najpierw uruchom analizę, aby wygenerować raport PDF.", "error");
      return;
    }

    setReportButtonState(false, "Generowanie PDF…");
    try {
      const link = document.createElement("a");
      const url = ApiClient.buildReportUrl(currentAnalysisRequest);
      link.href = url;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setUploadMessage("Raport PDF jest generowany i pobierany przez przeglądarkę.", "success");
      setDebug("GET /api/report/{upload_id}.pdf", { url, upload_id: currentAnalysisRequest.upload_id });
    } catch (error) {
      setUploadMessage(`Błąd generowania PDF: ${error.message}`, "error");
      setDebug("GET /api/report/{upload_id}.pdf ERROR", error.message);
    } finally {
      setReportButtonState(Boolean(currentAnalysisRequest), "Pobierz PDF");
    }
  }

  function bindEvents() {
    uploadFormEl.addEventListener("submit", handleUploadSubmit);
    refreshSourceBtnEl.addEventListener("click", loadSource);
    ensureAnalyzeButton().addEventListener("click", handleAnalyzeClick);
    if (downloadReportBtnEl) {
      downloadReportBtnEl.addEventListener("click", handleDownloadReportClick);
    }
  }

  async function bootstrap() {
    try {
      bindEvents();
      ensureMap();
      renderRequestSummary(null);
      renderRecentEntries();
      renderRecommendations([]);
      renderConflicts([]);
      setReportButtonState(false, "Pobierz PDF");
      await loadHealth();
      await loadSource();
    } catch (error) {
      setDebug("BOOTSTRAP ERROR", error.message || String(error));
      setUploadMessage(`Błąd inicjalizacji UI: ${error.message || error}`, "error");
    }
  }

  window.addEventListener("DOMContentLoaded", bootstrap);
})();
