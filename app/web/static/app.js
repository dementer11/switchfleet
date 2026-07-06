const $ = (id) => document.getElementById(id);

const sensitiveKeys = new Set(["password", "new_password"]);
let lastResult = {};

function inputValue(id) {
  const node = $(id);
  return node ? node.value.trim() : "";
}

function boolValue(id) {
  const node = $(id);
  return Boolean(node && node.checked);
}

function numberValue(id) {
  const value = inputValue(id);
  return value === "" ? null : Number(value);
}

function basePayload() {
  return {
    inventory_path: inputValue("inventoryPath"),
    state_dir: inputValue("stateDir") || ".switchfleet_lab",
    debug: boolValue("debugMode"),
  };
}

function operationPayload() {
  const payload = {
    credential: inputValue("credentialRef"),
    operation: inputValue("operation"),
    capability: inputValue("capability"),
    vlan_id: numberValue("vlanId"),
    name: inputValue("operationName"),
    username: inputValue("passwordUser"),
    new_password: inputValue("newPassword"),
    level: numberValue("privilegeLevel"),
    interface: inputValue("interfaceName"),
    simulation_hash: inputValue("simulationHash"),
    real_lab: boolValue("realLab"),
  };
  for (const [key, value] of Object.entries(payload)) {
    if (value === "" || value === null) {
      delete payload[key];
    }
  }
  return payload;
}

function commandPayload(command) {
  const payload = {
    ...basePayload(),
    all_devices: boolValue("allDevices"),
    device: inputValue("deviceIp"),
    vendor: inputValue("vendorFilter"),
    category: inputValue("categoryFilter"),
    status: inputValue("statusFilter"),
    allowlisted_only: boolValue("allowlistedOnly"),
    limit: numberValue(command === "audit-tail" ? "auditLimit" : "limit"),
  };
  if (["backup", "dry-run", "evaluate-apply", "certify", "execute-apply"].includes(command)) {
    Object.assign(payload, operationPayload());
  }
  if (command === "add-credential") {
    Object.assign(payload, {
      name: inputValue("credentialName"),
      username: inputValue("credentialUsername"),
      password: inputValue("credentialPassword"),
      purpose: inputValue("credentialPurpose") || "lab_apply",
    });
  }
  if (command === "workflow") {
    Object.assign(payload, {
      profile_path: inputValue("profilePath"),
      with_backup: boolValue("withBackup"),
    });
  }
  if (command === "certification-report" || command === "audit-tail" || command === "doctor" || command === "summary") {
    delete payload.device;
    delete payload.all_devices;
  }
  if (command === "list") {
    delete payload.device;
    delete payload.all_devices;
  }
  for (const [key, value] of Object.entries(payload)) {
    if (value === "" || value === null || value === undefined) {
      delete payload[key];
    }
    if (sensitiveKeys.has(key) && value === "") {
      delete payload[key];
    }
  }
  return payload;
}

async function runCommand(command) {
  setBusy(true);
  clearMessage();
  $("resultTitle").textContent = command;
  try {
    const response = await fetch(`/api/local/${encodeURIComponent(command)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(commandPayload(command)),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
    lastResult = data;
    renderResult(data);
    showMessage("Command completed", "ok");
    if (command === "add-credential") {
      $("credentialPassword").value = "";
    }
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    lastResult = { error: detail };
    renderJson(lastResult);
    $("tableOutput").innerHTML = "";
    showMessage(detail, "error");
  } finally {
    setBusy(false);
  }
}

function renderResult(data) {
  const tableData = pickRows(data);
  if (tableData.length) {
    renderTable(tableData);
  } else {
    $("tableOutput").innerHTML = "";
  }
  renderJson(data);
}

function pickRows(data) {
  if (Array.isArray(data.devices)) {
    return data.devices;
  }
  if (Array.isArray(data.results)) {
    return data.results;
  }
  if (Array.isArray(data.events)) {
    return data.events;
  }
  if (Array.isArray(data.certifications)) {
    return data.certifications;
  }
  if (data.backup) {
    return [data.backup];
  }
  if (data.credential) {
    return [data.credential];
  }
  if (data.device_ip || data.family || data.command_hash || data.allowed !== undefined) {
    return [data];
  }
  return [];
}

function renderTable(rows) {
  const columns = preferredColumns(rows);
  const head = columns.map((key) => `<th>${escapeHtml(labelFor(key))}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${columns.map((key) => `<td>${cell(row[key], key)}</td>`).join("")}</tr>`)
    .join("");
  $("tableOutput").innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function preferredColumns(rows) {
  const preferred = [
    "device_ip",
    "hostname",
    "label",
    "vendor",
    "model",
    "family",
    "driver",
    "selected_transport",
    "transport",
    "backup_status",
    "apply_status",
    "status",
    "allowed",
    "operation",
    "capability",
    "command_hash",
    "simulation_hash",
    "backup_id",
    "config_hash",
    "error",
  ];
  const available = new Set();
  rows.forEach((row) => Object.keys(row || {}).forEach((key) => available.add(key)));
  const selected = preferred.filter((key) => available.has(key));
  for (const key of available) {
    if (!selected.includes(key) && !String(key).includes("internal")) {
      selected.push(key);
    }
  }
  return selected.slice(0, 14);
}

function cell(value, key) {
  if (value === undefined || value === null || value === "") {
    return "";
  }
  if (typeof value === "boolean") {
    return chip(value ? "yes" : "no", value ? "ok" : "");
  }
  if (typeof value === "object") {
    if (value.status) {
      return chip(String(value.status), String(value.status));
    }
    return `<code>${escapeHtml(JSON.stringify(value))}</code>`;
  }
  const text = String(value);
  if (["status", "backup_status", "apply_status", "selected_transport", "transport"].includes(key)) {
    return chip(text, text);
  }
  return escapeHtml(text);
}

function chip(text, cls) {
  const normalized = cls.replace(/[^a-z0-9_-]/gi, "_");
  return `<span class="chip ${escapeHtml(normalized)}">${escapeHtml(text)}</span>`;
}

function labelFor(key) {
  return key.replaceAll("_", " ");
}

function renderJson(data) {
  $("jsonOutput").textContent = JSON.stringify(redactForDisplay(data), null, 2);
}

function redactForDisplay(value) {
  if (Array.isArray(value)) {
    return value.map((item) => redactForDisplay(item));
  }
  if (value && typeof value === "object") {
    const copy = {};
    for (const [key, entry] of Object.entries(value)) {
      if (/password|secret|token|credential_payload/i.test(key)) {
        copy[key] = "<redacted>";
      } else {
        copy[key] = redactForDisplay(entry);
      }
    }
    return copy;
  }
  return value;
}

function showMessage(text, kind) {
  const message = $("message");
  message.textContent = text;
  message.className = `message ${kind}`;
}

function clearMessage() {
  const message = $("message");
  message.textContent = "";
  message.className = "message";
}

function setBusy(busy) {
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = busy;
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function saveWorkspaceFields() {
  localStorage.setItem(
    "switchfleet.workspace",
    JSON.stringify({
      inventoryPath: inputValue("inventoryPath"),
      stateDir: inputValue("stateDir"),
    }),
  );
}

function loadWorkspaceFields() {
  try {
    const saved = JSON.parse(localStorage.getItem("switchfleet.workspace") || "{}");
    if (saved.inventoryPath) {
      $("inventoryPath").value = saved.inventoryPath;
    }
    if (saved.stateDir) {
      $("stateDir").value = saved.stateDir;
    }
  } catch {
    localStorage.removeItem("switchfleet.workspace");
  }
}

document.querySelectorAll("[data-command]").forEach((button) => {
  button.addEventListener("click", () => {
    saveWorkspaceFields();
    runCommand(button.dataset.command);
  });
});

document.querySelectorAll(".nav-button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-button").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    $(`tab-${button.dataset.tab}`).classList.add("active");
  });
});

$("copyJson").addEventListener("click", async () => {
  await navigator.clipboard.writeText(JSON.stringify(lastResult, null, 2));
  showMessage("JSON copied", "ok");
});

loadWorkspaceFields();
