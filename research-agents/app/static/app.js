const form = document.querySelector("#research-form");
const submitButton = document.querySelector("#submit");
const formStatus = document.querySelector("#form-status");
const runPanel = document.querySelector("#run-panel");
const runIdEl = document.querySelector("#run-id");
const runStatusEl = document.querySelector("#run-status");
const runQuestionEl = document.querySelector("#run-question");
const traceEl = document.querySelector("#trace");
const resultEl = document.querySelector("#result");
const errorEl = document.querySelector("#error");
const approvalPanel = document.querySelector("#approval-panel");
const approvalSummary = document.querySelector("#approval-summary");
const feedbackEl = document.querySelector("#feedback");
const healthEl = document.querySelector("#health");

let currentRun = null;
let eventSource = null;
const seenTrace = new Set();

function setStatus(status) {
  runStatusEl.textContent = status;
  runStatusEl.className = "badge";
  if (status === "completed") runStatusEl.classList.add("done");
  else if (status === "failed" || status === "rejected") runStatusEl.classList.add("bad");
  else if (status === "awaiting_approval") runStatusEl.classList.add("wait");
}

function showError(message) {
  if (!message) {
    errorEl.textContent = "";
    errorEl.classList.add("hidden");
    return;
  }
  errorEl.textContent = message;
  errorEl.classList.remove("hidden");
}

function appendTrace(event) {
  const key = `${event.timestamp}|${event.node}|${event.event}|${JSON.stringify(event.data || {})}`;
  if (seenTrace.has(key)) return;
  seenTrace.add(key);
  const item = document.createElement("li");
  const title = document.createElement("span");
  title.className = "node";
  title.textContent = `${event.node || "graph"} · ${event.event || "event"}`;
  item.appendChild(title);
  const data = event.data || {};
  if (Object.keys(data).length) {
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(data, null, 2);
    item.appendChild(pre);
  }
  traceEl.appendChild(item);
  traceEl.scrollTop = traceEl.scrollHeight;
}

function clearRun() {
  seenTrace.clear();
  traceEl.replaceChildren();
  resultEl.replaceChildren();
  approvalPanel.classList.add("hidden");
  showError("");
}

function safeUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function renderList(title, values) {
  if (!values || !values.length) return null;
  const heading = document.createElement("h4");
  heading.textContent = title;
  const list = document.createElement("ul");
  for (const value of values) {
    const item = document.createElement("li");
    item.textContent = value;
    list.appendChild(item);
  }
  const wrapper = document.createElement("div");
  wrapper.append(heading, list);
  return wrapper;
}

function renderReport(report, usage, errors) {
  resultEl.replaceChildren();
  if (report) {
    const title = document.createElement("h3");
    title.textContent = report.title || "Informe";
    const confidence = document.createElement("p");
    confidence.className = "muted";
    confidence.textContent = `Confianza: ${report.confidence || "—"}`;
    const answer = document.createElement("pre");
    answer.className = "answer";
    answer.textContent = report.answer_markdown || "";
    resultEl.append(title, confidence, answer);

    if (report.claims?.length) {
      const heading = document.createElement("h4");
      heading.textContent = "Claims y citas";
      const list = document.createElement("ul");
      for (const claim of report.claims) {
        const item = document.createElement("li");
        const citations = (claim.source_ids || []).map((id) => `[${id}]`).join(" ");
        item.textContent = `${claim.text} ${citations}`.trim();
        list.appendChild(item);
      }
      resultEl.append(heading, list);
    }

    if (report.sources?.length) {
      const heading = document.createElement("h4");
      heading.textContent = "Fuentes";
      const list = document.createElement("ul");
      for (const source of report.sources) {
        const item = document.createElement("li");
        const href = safeUrl(source.url);
        if (href) {
          const link = document.createElement("a");
          link.href = href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = source.title || href;
          item.appendChild(link);
        } else {
          item.textContent = source.title || "Fuente sin URL";
        }
        const id = document.createElement("span");
        id.className = "muted";
        id.textContent = ` [${source.source_id}]`;
        item.appendChild(id);
        list.appendChild(item);
      }
      resultEl.append(heading, list);
    }

    const limitations = renderList("Limitaciones", report.limitations);
    if (limitations) resultEl.appendChild(limitations);
  } else if (errors?.length) {
    const list = renderList("Errores", errors);
    if (list) resultEl.appendChild(list);
  } else {
    const pending = document.createElement("p");
    pending.className = "muted";
    pending.textContent = "La ejecución terminó sin informe.";
    resultEl.appendChild(pending);
  }

  if (usage) {
    const stats = document.createElement("p");
    stats.className = "muted";
    stats.textContent =
      `Uso: ${usage.llm_calls ?? 0} llamadas · ` +
      `${usage.total_tokens ?? 0} tokens · ` +
      `${usage.search_calls ?? 0} búsquedas`;
    resultEl.appendChild(stats);
  }
}

function renderApproval(interrupt) {
  if (!interrupt) {
    approvalPanel.classList.add("hidden");
    return;
  }
  const summary = interrupt.analysis_summary || "El equipo terminó la investigación.";
  const critique = interrupt.critique?.verdict
    ? ` Crítica: ${interrupt.critique.verdict}.`
    : "";
  const notes = interrupt.notes?.length ? ` ${interrupt.notes.length} notas.` : "";
  approvalSummary.textContent = `${summary}${critique}${notes}`;
  approvalPanel.classList.remove("hidden");
}

async function refresh(runId) {
  const response = await fetch(`/v1/research/${encodeURIComponent(runId)}`);
  if (!response.ok) {
    if (response.status === 404) showError("La ejecución ya no está disponible.");
    return;
  }
  const data = await response.json();
  setStatus(data.status);
  runQuestionEl.textContent = data.question;
  renderApproval(data.interrupt);
  if (data.trace?.length) {
    for (const event of data.trace) appendTrace(event);
  }
  if (data.status === "completed" || data.status === "failed" || data.status === "rejected") {
    renderReport(data.report, data.usage, data.errors);
    if (data.errors?.length) showError(data.errors.join(" · "));
  }
}

function connect(runId) {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/v1/research/${encodeURIComponent(runId)}/events`);
  eventSource.onmessage = (message) => {
    let event;
    try {
      event = JSON.parse(message.data);
    } catch {
      return;
    }
    if (event.type === "status") {
      if (event.status) setStatus(event.status);
    } else if (event.type === "trace") {
      appendTrace(event);
    } else if (event.type === "run_error") {
      showError(event.message || "Error en la ejecución.");
    } else if (event.type === "end") {
      setStatus(event.status || "completed");
      if (event.status === "awaiting_approval") {
        refresh(runId);
        return;
      }
      eventSource.close();
      refresh(runId);
    }
  };
  eventSource.onerror = () => {
    if (eventSource.readyState === EventSource.CLOSED) {
      showError("Se perdió la conexión SSE; actualiza para ver el estado.");
    }
  };
}

async function approve(approved) {
  if (!currentRun) return;
  const response = await fetch(
    `/v1/research/${encodeURIComponent(currentRun)}/approve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        approved,
        feedback: feedbackEl.value.trim(),
      }),
    },
  );
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    showError(data.detail || "No se pudo enviar la decisión.");
    return;
  }
  approvalPanel.classList.add("hidden");
  feedbackEl.value = "";
  setStatus(data.status);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = document.querySelector("#question").value.trim();
  if (!question) return;
  clearRun();
  submitButton.disabled = true;
  formStatus.textContent = "Creando ejecución…";
  try {
    const response = await fetch("/v1/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        language: document.querySelector("#language").value,
        hitl: document.querySelector("#hitl").checked,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      formStatus.textContent = "";
      showError(data.detail ? JSON.stringify(data.detail) : "No se pudo iniciar la ejecución.");
      return;
    }
    currentRun = data.run_id;
    runPanel.classList.remove("hidden");
    runIdEl.textContent = data.run_id;
    runQuestionEl.textContent = question;
    setStatus(data.status);
    resultEl.replaceChildren();
    const pending = document.createElement("p");
    pending.className = "muted";
    pending.textContent = "Esperando el informe…";
    resultEl.appendChild(pending);
    formStatus.textContent = "Ejecución iniciada.";
    connect(data.run_id);
  } catch (error) {
    formStatus.textContent = "";
    showError(`Error de red: ${error}`);
  } finally {
    submitButton.disabled = false;
  }
});

document.querySelector("#approve").addEventListener("click", () => approve(true));
document.querySelector("#reject").addEventListener("click", () => approve(false));

async function checkHealth() {
  try {
    const response = await fetch("/health");
    const data = await response.json();
    if (data.status === "ok") {
      healthEl.textContent = `API lista · ${data.provider.name}/${data.provider.model}`;
    } else {
      healthEl.textContent = `API degradada · ${data.provider.name}/${data.provider.model}`;
      healthEl.title = "Falta una clave o el checkpointer no está disponible.";
    }
  } catch {
    healthEl.textContent = "API no disponible";
  }
}

checkHealth();
