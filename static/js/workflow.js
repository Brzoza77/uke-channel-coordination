(function () {
  const statusEl = document.getElementById("workflowStatus");
  const metaEl = document.getElementById("workflowMeta");
  const summaryEl = document.getElementById("workflowSummary");
  const stateEl = document.getElementById("workflowState");
  const viewportEl = document.getElementById("workflowViewport");
  const edgesBodyEl = document.getElementById("workflowEdgesBody");
  const refreshBtnEl = document.getElementById("refreshWorkflowBtn");
  const lowConfidenceEl = document.getElementById("showLowConfidenceEdges");
  const dotLinkEl = document.getElementById("workflowDotLink");
  let currentPayload = null;

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function escapeMermaid(value) {
    return String(value)
      .replace(/"/g, "'")
      .replace(/[{}[\]()`]/g, " ");
  }

  function setStatus(ok, text) {
    statusEl.textContent = text;
    statusEl.classList.remove("is-ok", "is-error");
    statusEl.classList.add(ok ? "is-ok" : "is-error");
  }

  function visibleEdges(payload) {
    const includeLow = Boolean(lowConfidenceEl.checked);
    return (payload.edges || []).filter((edge) => includeLow || edge.confidence !== "low");
  }

  function renderSummary(payload) {
    const edges = visibleEdges(payload);
    const cards = [
      ["SQLite", payload.sqlite_path || "-"],
      ["Source DB", payload.source_db || "-"],
      ["Tabele", payload.table_count || 0],
      ["Relacje widoczne", edges.length],
      ["Relacje ogolem", payload.edge_count || 0],
      ["DOT", payload.dot_available ? "dostepny" : "brak"]
    ];
    summaryEl.innerHTML = cards.map(([label, value]) => `
      <div class="stat-card">
        <span class="stat-card-label">${escapeHtml(label)}</span>
        <span class="stat-card-value ${label === "SQLite" ? "mono-text" : ""}">${escapeHtml(value)}</span>
      </div>
    `).join("");
  }

  function buildMermaid(payload) {
    const nodeIds = new Map();
    const lines = ["flowchart LR"];
    (payload.tables || []).forEach((table, index) => {
      const nodeId = `T${index}`;
      nodeIds.set(table.source_table, nodeId);
      lines.push(`${nodeId}["${escapeMermaid(`${table.source_table}<br/>rows=${table.row_count}`)}"]`);
    });

    visibleEdges(payload).forEach((edge) => {
      const from = nodeIds.get(edge.from);
      const to = nodeIds.get(edge.to);
      if (!from || !to) {
        return;
      }
      const arrow = edge.confidence === "high" ? "==>" : "-->";
      lines.push(`${from} ${arrow}|${edge.confidence}| ${to}`);
    });

    return lines.join("\n");
  }

  async function renderGraph(payload) {
    if (!window.mermaid) {
      viewportEl.innerHTML = `<div class="empty-cell">Brak biblioteki Mermaid w przegladarce.</div>`;
      return;
    }

    const graphDefinition = buildMermaid(payload);
    viewportEl.innerHTML = `<pre class="mermaid">${escapeHtml(graphDefinition)}</pre>`;
    await window.mermaid.run({ querySelector: ".mermaid" });
  }

  function renderEdges(payload) {
    const edges = visibleEdges(payload);
    if (!edges.length) {
      edgesBodyEl.innerHTML = `<tr><td colspan="5" class="empty-cell">Brak widocznych relacji.</td></tr>`;
      return;
    }

    edgesBodyEl.innerHTML = edges
      .slice(0, 120)
      .map((edge) => `
        <tr>
          <td>${escapeHtml(edge.from)}</td>
          <td>${escapeHtml(edge.to)}</td>
          <td><span class="status-badge is-neutral">${escapeHtml(edge.confidence)}</span></td>
          <td>${escapeHtml(edge.rule)}</td>
          <td class="mono-text">${escapeHtml(`${edge.left_column} -> ${edge.right_column}`)}</td>
        </tr>
      `)
      .join("");
  }

  async function renderPayload(payload) {
    currentPayload = payload;
    renderSummary(payload);
    renderEdges(payload);
    metaEl.textContent = `${payload.sqlite_path || "-"} | tables: ${payload.table_count || 0} | edges: ${visibleEdges(payload).length}`;
    stateEl.textContent = "Graf zaladowany.";
    stateEl.classList.remove("error");
    dotLinkEl.style.display = payload.dot_available ? "inline-flex" : "none";
    if (payload.dot_url) {
      dotLinkEl.href = payload.dot_url;
    }
    await renderGraph(payload);
  }

  async function loadWorkflow() {
    try {
      const payload = await ApiClient.getWorkflowGraph();
      await renderPayload(payload);
      setStatus(true, `Workflow: ${payload.table_count || 0} tabel`);
    } catch (error) {
      summaryEl.innerHTML = `
        <div class="stat-card">
          <span class="stat-card-label">Status</span>
          <span class="stat-card-value">${escapeHtml(error.message)}</span>
        </div>
      `;
      viewportEl.innerHTML = `<div class="empty-cell">${escapeHtml(error.message)}</div>`;
      edgesBodyEl.innerHTML = `<tr><td colspan="5" class="empty-cell">${escapeHtml(error.message)}</td></tr>`;
      metaEl.textContent = "Brak workflow graph.";
      stateEl.textContent = error.message;
      stateEl.classList.add("error");
      setStatus(false, `Workflow error: ${error.message}`);
    }
  }

  refreshBtnEl.addEventListener("click", loadWorkflow);
  lowConfidenceEl.addEventListener("change", () => {
    if (currentPayload) {
      renderPayload(currentPayload);
    }
  });

  if (window.mermaid) {
    window.mermaid.initialize({
      startOnLoad: false,
      theme: "dark",
      securityLevel: "loose",
      flowchart: {
        useMaxWidth: false,
        nodeSpacing: 30,
        rankSpacing: 40,
      }
    });
  }

  loadWorkflow();
})();
