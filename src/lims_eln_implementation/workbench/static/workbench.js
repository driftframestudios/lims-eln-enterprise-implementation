const form = document.querySelector("#golden-run-form");
const statusNode = document.querySelector("#run-status");
const resultPanel = document.querySelector("#specimen-result");
const refreshButton = document.querySelector("#refresh-summary");
const resumeButton = document.querySelector("#resume-review");
const recoveryField = document.querySelector("#recovery-field");
const occurredAt = document.querySelector("#occurred-at");
occurredAt.value = new Date().toISOString().slice(0, 19);

function field(id) {
  return document.querySelector(`#${id}`);
}

function tenantHeaders(tenantId, includeContent = false) {
  const headers = { "X-Tenant-ID": tenantId };
  if (includeContent) headers["Content-Type"] = "application/json";
  return headers;
}

function utf8Base64(value) {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function setStatus(message, kind = "progress") {
  statusNode.textContent = message;
  statusNode.dataset.kind = kind;
  statusNode.setAttribute("role", kind === "error" ? "alert" : "status");
}

function appendDefinition(list, term, description) {
  const group = document.createElement("div");
  const label = document.createElement("dt");
  const value = document.createElement("dd");
  label.textContent = term;
  value.textContent = description;
  group.append(label, value);
  list.append(group);
}

function renderSpecimen(document, observation) {
  field("result-title").textContent = document.specimen_id;
  field("result-state").textContent = `${document.state} · r${document.version}`;

  const timeline = field("event-timeline");
  timeline.replaceChildren();
  for (const event of document.events) {
    const item = documentNode("li");
    const title = documentNode("strong", event.event_type.replaceAll("_", " "));
    const details = documentNode(
      "span",
      `revision ${event.aggregate_version} · ${event.actor_id} · ${event.command_id}`,
    );
    item.append(title, details);
    timeline.append(item);
  }

  const evidence = field("boundary-evidence");
  evidence.replaceChildren();
  appendDefinition(evidence, "Custody", document.custody?.location ?? "Pending placement");
  const ingress = document.instrument_receipts.at(-1);
  appendDefinition(evidence, "Raw payload SHA-256", ingress?.raw_sha256 ?? "Pending ingress");
  const normalized = ingress?.normalized_observation;
  appendDefinition(
    evidence,
    "Normalized result",
    normalized
      ? `${normalized.analyte} · ${normalized.value} ${normalized.unit}`
      : ingress?.reason_code ?? "Pending ingress",
  );
  appendDefinition(
    evidence,
    "Normalized SHA-256",
    ingress?.normalized_digest ?? "Pending normalization",
  );
  appendDefinition(
    evidence,
    "Vendor projection",
    document.projection
      ? `${document.projection.vendor_name} revision ${document.projection.revision}`
      : "Pending projection",
  );
  appendDefinition(
    evidence,
    "Reconciliation",
    document.projection?.reconciled ? "Authoritative readback confirmed" : "Direct confirmation",
  );
  appendDefinition(
    evidence,
    "Shared observation",
    observation
      ? `${observation.observation_id} · contract ${observation.envelope_version}`
      : "Install contract package 0.3.x for the constellation envelope",
  );
  resultPanel.hidden = false;
  resultPanel.focus({ preventScroll: true });
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  resultPanel.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
}

function documentNode(name, text) {
  const node = document.createElement(name);
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderSummary(summary) {
  field("specimen-count").textContent = summary.specimen_count;
  field("receipt-count").textContent = summary.instrument_receipt_count;
  field("quarantine-count").textContent = summary.quarantine_count;
  field("outbox-count").textContent = summary.pending_outbox_count;
  const list = field("lifecycle-counts");
  list.replaceChildren();
  const entries = Object.entries(summary.lifecycle_counts);
  if (entries.length === 0) {
    list.append(documentNode("li", "Ready for the first specimen."));
    return;
  }
  for (const [state, count] of entries) {
    const item = documentNode("li");
    item.append(documentNode("span", state.replaceAll("_", " ")), documentNode("strong", count));
    list.append(item);
  }
}

async function requestJson(url, options) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") ?? "";
  let body;
  if (contentType.includes("json")) {
    body = await response.json().catch(() => ({}));
  } else {
    body = { detail: (await response.text()) || `Request returned ${response.status}` };
  }
  if (!response.ok) {
    const error = new Error(body.detail ?? `Request returned ${response.status}`);
    error.problem = body;
    error.status = response.status;
    throw error;
  }
  return body;
}

async function refreshSummary() {
  const tenantId = field("tenant-id").value.trim();
  const summary = await requestJson(
    `/api/workbench/summary?tenant_id=${encodeURIComponent(tenantId)}`,
    { headers: tenantHeaders(tenantId) },
  );
  renderSummary(summary);
}

function buildPayload() {
  const tenantId = field("tenant-id").value.trim();
  const instrumentPayload = JSON.stringify({
    analyte: field("analyte").value.trim(),
    value: field("observed-value").value.trim(),
    unit: field("unit").value,
  });
  return {
    run_id: field("run-id").value.trim(),
    tenant_id: tenantId,
    specimen_id: field("specimen-id").value.trim(),
    actor_id: field("actor-id").value.trim(),
    scientist_id: field("scientist-id").value.trim(),
    quality_actor_id: field("quality-actor-id").value.trim(),
    occurred_at: new Date(`${occurredAt.value}Z`).toISOString(),
    raw_instrument_payload_base64: utf8Base64(instrumentPayload),
    vendor_payload: { status: field("vendor-status").value },
  };
}

async function runJourney({ recovery = false } = {}) {
  if (!form.reportValidity()) return;
  const submitButton = form.querySelector("button[type='submit']");
  submitButton.disabled = true;
  resumeButton.disabled = true;
  form.setAttribute("aria-busy", "true");
  setStatus("The workbench is carrying the specimen across five boundaries.");
  const payload = buildPayload();
  if (recovery) payload.recovery_of_run_id = field("recovery-of-run-id").value.trim();
  const endpoint = recovery
    ? "/api/workbench/instrument-recovery-runs"
    : "/api/workbench/golden-runs";
  try {
    const result = await requestJson(endpoint, {
      method: "POST",
      headers: tenantHeaders(payload.tenant_id, true),
      body: JSON.stringify(payload),
    });
    renderSpecimen(result.specimen, result.observation);
    setStatus("Journey complete. The evidence view reflects the recorded outcome.", "success");
    recoveryField.hidden = true;
    resumeButton.hidden = true;
    try {
      await refreshSummary();
    } catch (summaryError) {
      setStatus(
        `Journey complete. The summary refresh can be retried: ${summaryError.message}`,
        "success",
      );
    }
  } catch (error) {
    const isInstrumentReview = error.message.includes("instrument review required");
    if (isInstrumentReview) {
      const failedRunId = payload.run_id;
      field("recovery-of-run-id").value = failedRunId;
      field("run-id").value = `${failedRunId.slice(0, 110)}-RECOVERY-01`;
      recoveryField.hidden = false;
      resumeButton.hidden = false;
      setStatus(
        `${error.message} Correct the instrument values, retain the linked identities, and resume review.`,
        "error",
      );
    } else {
      setStatus(error.message, "error");
    }
    try {
      await refreshSummary();
    } catch {
      // The primary domain decision remains the useful status for this interaction.
    }
  } finally {
    submitButton.disabled = false;
    resumeButton.disabled = false;
    form.setAttribute("aria-busy", "false");
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await runJourney();
});

resumeButton.addEventListener("click", async () => {
  await runJourney({ recovery: true });
});

refreshButton.addEventListener("click", async () => {
  try {
    await refreshSummary();
    setStatus("Tenant read model refreshed.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
});

refreshSummary().catch((error) => setStatus(error.message, "error"));
