const ApiClient = (() => {
  async function handleJsonResponse(response) {
    const contentType = response.headers.get("content-type") || "";
    const isJson = contentType.includes("application/json");
    const payload = isJson ? await response.json() : await response.text();

    if (!response.ok) {
      const detail = isJson && payload && typeof payload === "object"
        ? payload.detail || JSON.stringify(payload)
        : String(payload);
      throw new Error(detail || `HTTP ${response.status}`);
    }

    return payload;
  }

  async function getHealth() {
    const response = await fetch("/api/health", {
      method: "GET",
      headers: {
        "Accept": "application/json"
      }
    });
    return handleJsonResponse(response);
  }

  async function getSource() {
    const response = await fetch("/api/source", {
      method: "GET",
      headers: {
        "Accept": "application/json"
      }
    });
    return handleJsonResponse(response);
  }

  async function getAnalysisRuns(limit = 200) {
    const query = new URLSearchParams({ limit: String(limit) });
    const response = await fetch(`/api/analysis-runs?${query.toString()}`, {
      method: "GET",
      headers: {
        "Accept": "application/json"
      }
    });
    return handleJsonResponse(response);
  }

  async function getWorkflowGraph() {
    const response = await fetch("/api/workflow-graph", {
      method: "GET",
      headers: {
        "Accept": "application/json"
      }
    });
    return handleJsonResponse(response);
  }

  async function uploadWlr(file) {
    if (!(file instanceof File)) {
      throw new Error("Brak poprawnego pliku do wysłania.");
    }

    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch("/api/upload-wlr", {
      method: "POST",
      body: formData
    });
    return handleJsonResponse(response);
  }

  async function analyzeWlr(payload) {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
    return handleJsonResponse(response);
  }

  function buildReportUrl(payload) {
    if (!payload || !payload.upload_id) {
      throw new Error("Brak upload_id do wygenerowania raportu.");
    }
    const query = new URLSearchParams({
      radius_km: String(payload.radius_km ?? 30),
      max_links: String(payload.max_links ?? 500),
      operator_name: String(payload.operator_name ?? "Towerlink Poland Sp. z o.o.")
    });
    return `/api/report/${encodeURIComponent(payload.upload_id)}.pdf?${query.toString()}`;
  }

  return {
    getHealth,
    getSource,
    getAnalysisRuns,
    getWorkflowGraph,
    uploadWlr,
    analyzeWlr,
    buildReportUrl
  };
})();
