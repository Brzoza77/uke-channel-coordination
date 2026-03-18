(function () {
  const healthEl = document.getElementById("runsHealthStatus");
  const metaEl = document.getElementById("runsMeta");
  const summaryEl = document.getElementById("runsSummary");
  const bodyEl = document.getElementById("runsTableBody");
  const refreshBtnEl = document.getElementById("refreshRunsBtn");
  const autoRefreshEl = document.getElementById("autoRefreshRuns");
  let refreshTimer = null;

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatSeconds(durationMs) {
    return Number.isFinite(durationMs) ? (durationMs / 1000).toFixed(2) : "-";
  }

  function renderSummary(items) {
    if (!items.length) {
      summaryEl.innerHTML = `
        <div class="stat-card">
          <span class="stat-card-label">Status</span>
          <span class="stat-card-value">Brak wpisow</span>
        </div>
      `;
      return;
    }

    const okCount = items.filter((item) => item.status === "ok").length;
    const errorCount = items.length - okCount;
    const avgDurationMs = items.reduce((sum, item) => sum + Number(item.duration_ms || 0), 0) / items.length;
    const newest = items[0];

    const cards = [
      ["Wpisy", items.length],
      ["OK", okCount],
      ["Bledy", errorCount],
      ["Sredni czas [s]", formatSeconds(avgDurationMs)],
      ["Ostatni koniec", newest.finished_at || "-"],
      ["Ostatni link", newest.link_name || newest.upload_id || "-"]
    ];

    summaryEl.innerHTML = cards.map(([label, value]) => `
      <div class="stat-card">
        <span class="stat-card-label">${escapeHtml(label)}</span>
        <span class="stat-card-value">${escapeHtml(value)}</span>
      </div>
    `).join("");
  }

  function renderTable(items) {
    if (!items.length) {
      bodyEl.innerHTML = `<tr><td colspan="8" class="empty-cell">Brak wpisow.</td></tr>`;
      return;
    }

    bodyEl.innerHTML = items.map((item) => {
      const summary = item.summary || {};
      const bestChannel = [summary.best_channel_ab, summary.best_channel_ba, summary.best_polarization]
        .filter(Boolean)
        .join(" / ") || "-";
      const requested = [item.requested_channel_ab, item.requested_channel_ba, item.requested_polarization]
        .filter(Boolean)
        .join(" / ") || "-";
      const statusClass = item.status === "ok" ? "is-ok" : "is-error";
      const counts = `${summary.accepted_count ?? 0}/${summary.conditional_count ?? 0}/${summary.rejected_count ?? 0}`;

      return `
        <tr>
          <td>${escapeHtml(item.finished_at || "-")}</td>
          <td>${escapeHtml(formatSeconds(Number(item.duration_ms || 0)))}</td>
          <td><span class="status-badge ${statusClass}">${escapeHtml(item.status || "-")}</span></td>
          <td>${escapeHtml(item.trigger || "-")}</td>
          <td>${escapeHtml(item.link_name || item.upload_id || "-")}</td>
          <td>${escapeHtml(requested)}</td>
          <td>${escapeHtml(bestChannel)}</td>
          <td>${escapeHtml(counts)}</td>
        </tr>
      `;
    }).join("");
  }

  function setHealth(ok, message) {
    healthEl.textContent = message;
    healthEl.classList.remove("is-ok", "is-error");
    healthEl.classList.add(ok ? "is-ok" : "is-error");
  }

  async function loadRuns() {
    try {
      const payload = await ApiClient.getAnalysisRuns(250);
      const items = Array.isArray(payload.items) ? payload.items : [];
      renderSummary(items);
      renderTable(items);
      metaEl.textContent = `${payload.log_path || "logs/wlr_analysis_runs.jsonl"} | wpisy: ${items.length}`;
      setHealth(true, `Runs: ${items.length}`);
    } catch (error) {
      renderSummary([]);
      bodyEl.innerHTML = `<tr><td colspan="8" class="empty-cell">${escapeHtml(error.message)}</td></tr>`;
      metaEl.textContent = "Nie udalo sie zaladowac logu analiz.";
      setHealth(false, `Runs error: ${error.message}`);
    }
  }

  function resetAutoRefresh() {
    if (refreshTimer) {
      window.clearInterval(refreshTimer);
      refreshTimer = null;
    }
    if (autoRefreshEl.checked) {
      refreshTimer = window.setInterval(loadRuns, 15000);
    }
  }

  refreshBtnEl.addEventListener("click", loadRuns);
  autoRefreshEl.addEventListener("change", resetAutoRefresh);

  loadRuns();
  resetAutoRefresh();
})();
