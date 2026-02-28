const API = "/api/v1/reports";

let selectedPatient = null;
let selectedAccession = null;
let currentReport = null;

// ── DOM refs ──────────────────────────────────────────────
const $patientList = document.getElementById("patient-list");
const $examSection = document.getElementById("exam-section");
const $examTimeline = document.getElementById("exam-timeline");
const $btnGenerate = document.getElementById("btn-generate");
const $emptyState = document.getElementById("empty-state");
const $loadingOverlay = document.getElementById("loading-overlay");
const $reportContainer = document.getElementById("report-container");
const $btnCopy = document.getElementById("btn-copy");
const $btnExport = document.getElementById("btn-export");

// ── Init ──────────────────────────────────────────────────
loadPatients();
setupAccordions();
$btnGenerate.addEventListener("click", generateReport);
$btnCopy.addEventListener("click", copyAsText);
$btnExport.addEventListener("click", exportJSON);

// ── API helpers ───────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Patients ──────────────────────────────────────────────
async function loadPatients() {
  try {
    const patients = await api("GET", "/patients");
    $patientList.innerHTML = "";
    patients.forEach((pid) => {
      const el = document.createElement("div");
      el.className = "patient-card";
      el.textContent = pid;
      el.addEventListener("click", () => selectPatient(pid));
      $patientList.appendChild(el);
    });
  } catch (e) {
    $patientList.innerHTML = `<p style="color:#ef4444;font-size:.8rem">Failed to load patients: ${e.message}</p>`;
  }
}

function selectPatient(pid) {
  selectedPatient = pid;
  selectedAccession = null;
  $btnGenerate.disabled = true;

  document.querySelectorAll(".patient-card").forEach((el) => {
    el.classList.toggle("active", el.textContent === pid);
  });

  loadExams(pid);
}

// ── Exams ─────────────────────────────────────────────────
async function loadExams(pid) {
  $examSection.style.display = "";
  $examTimeline.innerHTML = '<div class="skeleton-line"></div>';

  try {
    const exams = await api("GET", `/patients/${pid}/exams`);
    $examTimeline.innerHTML = "";
    exams.forEach((exam) => {
      const el = document.createElement("div");
      el.className = "exam-item";
      const dateStr = exam.study_date || "—";
      el.innerHTML = `
        <div class="exam-date">${dateStr}</div>
        <div class="exam-accession">${exam.accession_number}</div>
        <div class="exam-meta">
          <span>${exam.serie}</span>
          <span class="badge badge-lesions">${exam.lesion_count} lesion${exam.lesion_count > 1 ? "s" : ""}</span>
        </div>
      `;
      el.addEventListener("click", () => selectExam(exam.accession_number));
      $examTimeline.appendChild(el);
    });
  } catch (e) {
    $examTimeline.innerHTML = `<p style="color:#ef4444;font-size:.8rem">${e.message}</p>`;
  }
}

function selectExam(accession) {
  selectedAccession = accession;
  $btnGenerate.disabled = false;

  document.querySelectorAll(".exam-item").forEach((el) => {
    const acc = el.querySelector(".exam-accession").textContent.trim();
    el.classList.toggle("active", acc === String(accession));
  });
}

// ── Generate ──────────────────────────────────────────────
async function generateReport() {
  if (!selectedPatient || !selectedAccession) return;

  $emptyState.style.display = "none";
  $reportContainer.style.display = "none";
  $loadingOverlay.style.display = "";
  $btnGenerate.disabled = true;

  try {
    const report = await api("POST", "/generate", {
      patient_id: selectedPatient,
      accession_number: selectedAccession,
    });
    currentReport = report;
    renderReport(report);
    $loadingOverlay.style.display = "none";
    $reportContainer.style.display = "";
  } catch (e) {
    $loadingOverlay.style.display = "none";
    $emptyState.style.display = "";
    alert("Report generation failed: " + e.message);
  } finally {
    $btnGenerate.disabled = false;
  }
}

// ── Render report ─────────────────────────────────────────
function renderReport(r) {
  document.getElementById("report-header").innerHTML = `
    <h2>Clinical Report</h2>
    <div class="report-header-meta">
      <span>Patient: <strong>${r.patient_id}</strong></span>
      <span>Accession: <strong>${r.accession_number}</strong></span>
    </div>
  `;

  renderClinicalInfo(r.clinical_information);
  renderStudyTechnique(r.study_technique);
  renderDeterminist(r.report.report_determinist);
  renderAgent(r.report.report_agent);
  renderConclusions(r.conclusions);
}

// ── Clinical Information ──────────────────────────────────
function renderClinicalInfo(ci) {
  const items = [
    ["Primary Diagnosis", ci.primary_diagnosis],
    ["Clinical Context", ci.clinical_context],
    ["Patient Sex", ci.patient_sex],
    ["Patient Age", ci.patient_age],
  ];
  document.getElementById("clinical-info-body").innerHTML = `
    <div class="kv-grid">
      ${items.filter(([, v]) => v).map(([k, v]) => `
        <div class="kv-item">
          <div class="kv-label">${k}</div>
          <div class="kv-value">${v}</div>
        </div>
      `).join("")}
    </div>
  `;
}

// ── Study Technique ───────────────────────────────────────
function renderStudyTechnique(st) {
  const items = [
    ["Study Description", st.study_description],
    ["Contrast", [st.contrast, st.contrast_agent].filter(Boolean).join(" — ") || null],
    ["Scanner", st.scanner_model],
    ["Tube Voltage", st.tube_voltage_kvp ? `${st.tube_voltage_kvp} kVp` : null],
    ["Slice Thickness", st.slice_thickness_mm ? `${st.slice_thickness_mm} mm` : null],
    ["Kernel", st.reconstruction_kernel],
    ["Scan Mode", st.scan_mode],
    ["Comparison Date", st.comparison_study_date],
    ["Comparison Accession", st.comparison_accession_number],
  ];
  document.getElementById("study-technique-body").innerHTML = `
    <div class="kv-grid">
      ${items.filter(([, v]) => v != null).map(([k, v]) => `
        <div class="kv-item">
          <div class="kv-label">${k}</div>
          <div class="kv-value kv-value--mono">${v}</div>
        </div>
      `).join("")}
    </div>
  `;
}

// ── Deterministic findings ────────────────────────────────
function evolutionTag(evo) {
  if (!evo) return "";
  const lower = evo.toLowerCase();
  let cls = "tag-stable";
  if (lower.includes("significant increase")) cls = "tag-significant-increase";
  else if (lower.includes("increase")) cls = "tag-increase";
  else if (lower.includes("significant decrease")) cls = "tag-significant-decrease";
  else if (lower.includes("decrease")) cls = "tag-decrease";
  else if (lower.includes("new")) cls = "tag-new";
  return `<span class="tag ${cls}">${evo}</span>`;
}

function fmtDims(dims) {
  if (!dims || !dims.length) return "—";
  return dims.map((d) => d.toFixed(1)).join(" x ") + " mm";
}

function fmtPct(v) {
  if (v == null) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

function fmtVol(v) {
  if (v == null) return "—";
  return v >= 1000 ? `${(v / 1000).toFixed(2)} mL` : `${v.toFixed(0)} mm\u00B3`;
}

function renderDeterminist(det) {
  const recist = det.recist_conclusion;
  let html = "";

  if (recist) {
    html += `<div style="margin-bottom:.75rem">
      <span class="recist-badge recist-${recist}">${recist}</span>
      <span style="margin-left:.5rem;font-size:.8rem;color:#94a3b8">RECIST 1.1</span>
    </div>`;
  }

  if (det.lesions.length) {
    html += `<table class="lesion-table">
      <thead><tr>
        <th>#</th>
        <th>Dimensions</th>
        <th>Previous</th>
        <th>Evolution</th>
        <th>Change</th>
        <th>Volume</th>
        <th>Vol. Change</th>
        <th>Slice</th>
      </tr></thead>
      <tbody>
        ${det.lesions.map((l, i) => `<tr>
          <td>${i + 1}</td>
          <td class="mono">${fmtDims(l.dimensions_mm)}</td>
          <td class="mono">${fmtDims(l.previous_dimensions_mm)}</td>
          <td>${evolutionTag(l.evolution)}</td>
          <td class="mono">${fmtPct(l.change_percent)}</td>
          <td class="mono">${fmtVol(l.volume_mm3)}</td>
          <td class="mono">${fmtPct(l.volume_change_percent)}</td>
          <td class="mono">${l.slice_index != null ? "img " + l.slice_index : "—"}</td>
        </tr>`).join("")}
      </tbody>
    </table>`;
  }

  document.getElementById("report-det-body").innerHTML = html || "<p style='color:#64748b'>No deterministic findings.</p>";
}

// ── Confidence badge helper ──────────────────────────────
function confBadge(score) {
  if (score == null) return "";
  const pct = Math.round(score * 100);
  const cls = score >= 0.7 ? "conf-high" : score >= 0.4 ? "conf-med" : "conf-low";
  return `<span class="confidence-badge ${cls}">
    <span class="conf-bar"><span class="conf-fill" style="width:${pct}%"></span></span>
    ${pct}%
  </span>`;
}

// ── Infiltration rendering ───────────────────────────────
function renderInfiltration(inf) {
  if (!inf) return "";

  const level = inf.level || "none";
  const hasIndicators = inf.present_indicators && inf.present_indicators.length > 0;

  if (level === "none" && !hasIndicators) {
    return `<div class="agent-subsection">
      <div class="agent-subsection-title">Infiltration ${confBadge(inf.confidence)}</div>
      <div class="infiltration-box">No signs of infiltration detected.</div>
    </div>`;
  }

  const levelLabel = level.replace(/_/g, " ");
  let html = `<div class="agent-subsection">
    <div class="agent-subsection-title">Infiltration Assessment ${confBadge(inf.confidence)}</div>
    <div class="infiltration-box">
      <div class="infiltration-header">
        <span class="infiltration-level level-${level}">${levelLabel}</span>
        <span class="infiltration-score">Score: ${(inf.final_score || 0).toFixed(2)} (raw: ${(inf.raw_score || 0).toFixed(2)})</span>
      </div>`;

  if (inf.summary) {
    html += `<div class="infiltration-summary">${inf.summary}</div>`;
  }

  if (inf.indicators && inf.indicators.length) {
    const present = inf.indicators.filter(i => i.present);
    if (present.length) {
      html += `<div style="font-size:.7rem;text-transform:uppercase;color:#64748b;margin-top:.5rem;font-weight:600">Indicators</div>
        <div class="indicators-grid">
          ${present.map((ind) => `
            <div class="indicator-item present">
              <span class="indicator-name">${ind.name.replace(/_/g, " ")}</span>
              <span class="indicator-certainty">${ind.certainty}</span>
            </div>
          `).join("")}
        </div>`;
    }
  }

  const mimic = inf.mimic_context;
  if (mimic) {
    const fields = ["inflammation", "fibrosis", "atelectasis", "post_therapy_changes", "artifact_present"];
    const activeAny = fields.some(f => mimic[f]);
    if (activeAny) {
      html += `<div style="font-size:.7rem;text-transform:uppercase;color:#64748b;margin-top:.5rem;font-weight:600">Mimic Context</div>
        <div class="mimic-section">
          ${fields.filter(f => mimic[f]).map(f => `<span class="mimic-pill active">${f.replace(/_/g, " ")}</span>`).join("")}
        </div>`;
    }
  }

  const temporal = inf.temporal;
  if (temporal && (temporal.progression_toward_structure || temporal.new_loss_of_interface)) {
    html += `<div style="font-size:.7rem;text-transform:uppercase;color:#64748b;margin-top:.5rem;font-weight:600">Temporal Evolution</div>
      <div class="mimic-section">
        ${temporal.progression_toward_structure ? '<span class="mimic-pill active">progression toward structure</span>' : ""}
        ${temporal.new_loss_of_interface ? '<span class="mimic-pill active">new loss of interface</span>' : ""}
      </div>`;
  }

  html += `</div></div>`;
  return html;
}

// ── Agent findings ────────────────────────────────────────
function renderAgent(agt) {
  let html = "";

  if (agt.lesions.length) {
    html += `<div class="agent-subsection">
      <div class="agent-subsection-title">Lesion Location & Characterization</div>
      <table class="lesion-table">
        <thead><tr><th>#</th><th>Location</th><th>Characterization</th><th>Conf.</th></tr></thead>
        <tbody>
          ${agt.lesions.map((l, i) => `<tr>
            <td>${i + 1}</td>
            <td>${l.location}</td>
            <td>${l.characterization || "—"}</td>
            <td>${confBadge(l.confidence)}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>`;
  }

  html += renderInfiltration(agt.infiltration);

  if (agt.organ_assessments.length) {
    html += `<div class="agent-subsection">
      <div class="agent-subsection-title">Organ Assessments</div>
      <div class="organ-list">
        ${agt.organ_assessments.map((oa) => `
          <div class="organ-item">
            <span class="organ-icon">${oa.is_normal ? "\u2705" : "\u274C"}</span>
            <span class="organ-name">${oa.organ}</span>
            <span class="organ-finding">${oa.finding}</span>
            ${confBadge(oa.confidence)}
          </div>
        `).join("")}
      </div>
    </div>`;
  }

  if (agt.negative_findings.length) {
    html += `<div class="agent-subsection">
      <div class="agent-subsection-title">Negative Findings ${confBadge(agt.negative_findings_confidence)}</div>
      <div class="pills">
        ${agt.negative_findings.map((nf) => `<span class="pill">${nf}</span>`).join("")}
      </div>
    </div>`;
  }

  if (agt.incidental_findings.length) {
    html += `<div class="agent-subsection">
      <div class="agent-subsection-title">Incidental Findings</div>
      ${agt.incidental_findings.map((inc) => `
        <div class="incidental-item">
          ${inc.is_new ? '<span class="badge-new">NEW</span>' : ""}
          <strong>${inc.location}</strong>: ${inc.description}
          ${confBadge(inc.confidence)}
        </div>
      `).join("")}
    </div>`;
  }

  document.getElementById("report-agent-body").innerHTML = html || "<p style='color:#64748b'>No agent findings.</p>";
}

// ── Conclusions ───────────────────────────────────────────
function renderConclusions(c) {
  let html = "";

  if (c.recist_response) {
    html += `<div class="conclusions-recist">
      <span class="recist-badge recist-${c.recist_response}" style="font-size:1.1rem;padding:.35rem 1rem">
        ${c.recist_response}
      </span>
      <span style="font-size:.85rem;color:#94a3b8">RECIST 1.1 Response</span>
    </div>`;
  }

  if (c.recist_justification) {
    html += `<div class="conclusions-justification">${c.recist_justification}</div>`;
  }

  if (c.sum_of_diameters_mm != null) {
    html += `<div class="kv-grid" style="margin-bottom:.75rem">
      <div class="kv-item">
        <div class="kv-label">Sum of Diameters (current)</div>
        <div class="kv-value kv-value--mono">${c.sum_of_diameters_mm.toFixed(1)} mm</div>
      </div>
      ${c.previous_sum_of_diameters_mm != null ? `
        <div class="kv-item">
          <div class="kv-label">Sum of Diameters (previous)</div>
          <div class="kv-value kv-value--mono">${c.previous_sum_of_diameters_mm.toFixed(1)} mm</div>
        </div>
      ` : ""}
    </div>`;
  }

  if (c.key_findings.length) {
    html += `<div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.4rem">
      <span style="font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;color:#64748b;font-weight:600">Key Findings</span>
      ${confBadge(c.conclusions_confidence)}
    </div>
    <ul class="key-findings-list">
      ${c.key_findings.map((kf) => `<li>${kf}</li>`).join("")}
    </ul>`;
  }

  if (c.recommendation) {
    html += `<div class="recommendation-box">
      <div class="recommendation-label">Recommendation</div>
      ${c.recommendation}
    </div>`;
  }

  document.getElementById("conclusions-body").innerHTML = html || "<p style='color:#64748b'>No conclusions.</p>";
}

// ── Accordion toggle ──────────────────────────────────────
function setupAccordions() {
  document.querySelectorAll(".card-title[data-toggle]").forEach((title) => {
    title.addEventListener("click", () => {
      const bodyId = title.getAttribute("data-toggle");
      const body = document.getElementById(bodyId);
      title.classList.toggle("collapsed");
      body.classList.toggle("collapsed");
    });
  });
}

// ── Copy / Export ─────────────────────────────────────────
function copyAsText() {
  if (!currentReport) return;
  const text = reportToText(currentReport);
  navigator.clipboard.writeText(text).then(() => showToast("Copied to clipboard"));
}

function exportJSON() {
  if (!currentReport) return;
  const blob = new Blob([JSON.stringify(currentReport, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `report_${currentReport.patient_id}_${currentReport.accession_number}.json`;
  a.click();
  URL.revokeObjectURL(url);
  showToast("JSON exported");
}

function reportToText(r) {
  const lines = [];
  const ci = r.clinical_information;
  lines.push(`CLINICAL INFORMATION. ${ci.primary_diagnosis}. ${ci.clinical_context}`);

  const st = r.study_technique;
  let tech = `STUDY TECHNIQUE. ${st.study_description}`;
  if (st.contrast) tech += ` after administration of ${st.contrast} contrast`;
  if (st.contrast_agent) tech += ` (${st.contrast_agent})`;
  tech += ".";
  if (st.comparison_study_date) tech += ` Compares to previous CT available on ${st.comparison_study_date}.`;
  lines.push(tech);

  const det = r.report.report_determinist;
  const agt = r.report.report_agent;
  const reportLines = ["REPORT."];
  const n = Math.max(det.lesions.length, agt.lesions.length);
  for (let i = 0; i < n; i++) {
    const d = det.lesions[i];
    const a = agt.lesions[i];
    const loc = a ? a.location : `Lesion ${i + 1}`;
    const dims = d ? d.dimensions_mm.map((v) => v.toFixed(0)).join("x") + "mm" : "?";
    let line = `- ${loc}: ${dims}`;
    if (d && d.previous_dimensions_mm) {
      const prev = d.previous_dimensions_mm.map((v) => v.toFixed(0)).join("x");
      line += ` (anterior ${prev}mm)`;
    }
    if (d && d.evolution) line += `. ${d.evolution}`;
    if (a && a.characterization) line += `. ${a.characterization}`;
    reportLines.push(line);
  }
  if (det.recist_conclusion) reportLines.push(`RECIST 1.1: ${det.recist_conclusion}`);

  const inf = agt.infiltration;
  if (inf && inf.present_indicators && inf.present_indicators.length) {
    reportLines.push(`- Infiltration (${inf.level}): ${inf.summary || "See indicators"}`);
  }
  agt.organ_assessments.forEach((oa) => reportLines.push(`- ${oa.organ}: ${oa.finding}`));
  agt.negative_findings.forEach((nf) => reportLines.push(`- ${nf}`));
  agt.incidental_findings.forEach((inc) => reportLines.push(`- ${inc.location}: ${inc.description}`));
  lines.push(reportLines.join("\n"));

  const cl = r.conclusions;
  const concl = ["CONCLUSIONS."];
  if (cl.recist_response) concl.push(`Findings compatible with ${cl.recist_response} according to RECIST criteria.`);
  if (cl.recist_justification) concl.push(cl.recist_justification);
  cl.key_findings.forEach((kf) => concl.push(`- ${kf}`));
  if (cl.recommendation) concl.push(cl.recommendation);
  lines.push(concl.join(" "));

  return lines.join("\n\n");
}

// ── Toast ─────────────────────────────────────────────────
function showToast(msg) {
  let toast = document.querySelector(".toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.className = "toast";
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2000);
}
