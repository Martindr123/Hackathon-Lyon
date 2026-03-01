const API = "/api/v1/reports";

let selectedPatient = null;
let selectedAccession = null;
let currentReport = null;
let currentSessionId = null;
let currentStepData = null;
let stepResults = [];
let evidenceImagesByStep = {};
let viewedStepIndex = 0;
let currentStepIndex = -1;
let evidenceImages = null;
let eventSource = null;
let volumeData = { images: [], total_slices: 0 };
let volumeLoaded = false;
let volumeSliceIndex = 0;
let patientExams = [];
let previousComparisonData = null;
let viewingStepsAfterComplete = false;

// ── DOM refs ──────────────────────────────────────────────
const $patientList = document.getElementById("patient-list");
const $examSection = document.getElementById("exam-section");
const $examTimeline = document.getElementById("exam-timeline");
const $btnGenerate = document.getElementById("btn-generate");
const $btnQuick = document.getElementById("btn-quick-generate");
const $emptyState = document.getElementById("empty-state");
const $loadingOverlay = document.getElementById("loading-overlay");
const $reportContainer = document.getElementById("report-container");
const $reviewContainer = document.getElementById("review-container");
const $reviewProgress = document.getElementById("review-progress");
const $reviewStatus = document.getElementById("review-status");
const $reviewImages = document.getElementById("review-images");
const $reviewProposal = document.getElementById("review-proposal");
const $reviewActions = document.getElementById("review-actions");
const $btnValidate = document.getElementById("btn-validate");
const $reviewRefine = document.getElementById("review-refine");
const $refineRemark = document.getElementById("refine-remark");
const $btnRefine = document.getElementById("btn-refine");
const $refineError = document.getElementById("refine-error");
const $refineStatus = document.getElementById("refine-status");
const $btnCopy = document.getElementById("btn-copy");
const $btnExport = document.getElementById("btn-export");
const $btnExportPdf = document.getElementById("btn-export-pdf");
const $btnBackToSteps = document.getElementById("btn-back-to-steps");
const $btnBackToReport = document.getElementById("btn-back-to-report");
const $stepNavBackReport = document.getElementById("step-nav-back-report");

// ── Init ──────────────────────────────────────────────────
loadPatients();
setupAccordions();
$btnGenerate.addEventListener("click", startInteractive);
$btnQuick.addEventListener("click", quickGenerate);
$btnValidate.addEventListener("click", validateCurrentStep);
$btnRefine.addEventListener("click", refineCurrentStep);
$btnCopy.addEventListener("click", copyAsText);
$btnExport.addEventListener("click", exportJSON);
$btnExportPdf?.addEventListener("click", exportPDF);
$btnBackToSteps?.addEventListener("click", backToSteps);
$btnBackToReport?.addEventListener("click", backToReport);
document.getElementById("btn-step-prev")?.addEventListener("click", goToStepPrev);
document.getElementById("btn-step-next")?.addEventListener("click", goToStepNext);

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
  $btnQuick.disabled = true;
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
    patientExams = exams || [];
    $examTimeline.innerHTML = "";
    exams.forEach((exam) => {
      const el = document.createElement("div");
      el.className = "exam-item";
      const dateStr = exam.study_date || "\u2014";
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
  $btnQuick.disabled = false;
  document.querySelectorAll(".exam-item").forEach((el) => {
    const acc = el.querySelector(".exam-accession").textContent.trim();
    el.classList.toggle("active", acc === String(accession));
  });
}

// ══════════════════════════════════════════════════════════
//  INTERACTIVE PIPELINE (SSE)
// ══════════════════════════════════════════════════════════

function hideAll() {
  $emptyState.style.display = "none";
  $loadingOverlay.style.display = "none";
  $reportContainer.style.display = "none";
  $reviewContainer.style.display = "none";
  disposeVolume();
  previousComparisonData = null;
  stepResults = [];
  evidenceImagesByStep = {};
  viewedStepIndex = 0;
  currentStepIndex = -1;
  viewingStepsAfterComplete = false;
}

async function startInteractive() {
  if (!selectedPatient || !selectedAccession) return;
  hideAll();
  $reviewContainer.style.display = "";
  $reviewStatus.style.display = "flex";
  $reviewStatus.innerHTML = '<div class="spinner spinner-sm"></div><span>Initializing session&hellip;</span>';
  $reviewActions.style.display = "none";
  $reviewProposal.innerHTML = "";
  $reviewImages.style.display = "none";
  $btnGenerate.disabled = true;
  $btnQuick.disabled = true;
  evidenceImages = null;
  currentSessionId = null;
  updateProgressBar(-1);

  if (eventSource) { eventSource.close(); eventSource = null; }

  try {
    const res = await fetch(API + "/generate/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patient_id: selectedPatient, accession_number: selectedAccession }),
    });

    if (!res.ok) {
      let errMsg = `HTTP ${res.status}`;
      try {
        const errBody = await res.json();
        errMsg = errBody.detail || errMsg;
      } catch (_) { /* ignore parse error */ }
      $reviewStatus.innerHTML = `<span style="color:#ef4444">${errMsg}</span>`;
      $btnGenerate.disabled = false;
      $btnQuick.disabled = false;
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split("\n\n");
      buffer = parts.pop();

      for (const part of parts) {
        const lines = part.split("\n");
        let eventType = "message";
        let dataStr = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) eventType = line.slice(7);
          else if (line.startsWith("data: ")) dataStr += line.slice(6);
        }
        if (!dataStr) continue;

        try {
          const data = JSON.parse(dataStr);
          handleSSEEvent(eventType, data);
        } catch (e) {
          console.error("SSE parse error:", e, dataStr);
        }
      }
    }
  } catch (e) {
    $reviewStatus.innerHTML = `<span style="color:#ef4444">Error: ${e.message}</span>`;
    $btnGenerate.disabled = false;
    $btnQuick.disabled = false;
  }
}

function handleSSEEvent(type, data) {
  if (type === "session_init") {
    currentSessionId = data.session_id;
    $reviewStatus.innerHTML = '<div class="spinner spinner-sm"></div><span>Running first agent&hellip;</span>';
    $reviewImages.style.display = "";
    loadEvidenceImages(data.session_id);
    loadVolume(data.session_id);
  }

  else if (type === "step_result") {
    currentStepData = data;
    stepResults[data.step_index] = data;
    currentStepIndex = data.step_index;
    viewedStepIndex = data.step_index;
    $reviewStatus.style.display = "none";
    updateProgressBar(viewedStepIndex, currentStepIndex);
    renderProposal(data);
    loadEvidenceImages(data.session_id).then(function () {
      evidenceImagesByStep[data.step_index] = evidenceImages ? evidenceImages.slice() : [];
    });
    if (!volumeLoaded) loadVolume(data.session_id);
    updateStepNav();
    updateActionsVisibility();
    if ($refineError) $refineError.textContent = "";
    if ($refineStatus) $refineStatus.textContent = "";
  }

  else if (type === "complete") {
    currentReport = data.report;
    $emptyState.style.display = "none";
    $loadingOverlay.style.display = "none";
    $reviewContainer.style.display = "none";
    $reportContainer.style.display = "";
    renderReport(data.report);
    $btnGenerate.disabled = false;
    $btnQuick.disabled = false;
    showToast("Report complete!");
  }

  else if (type === "error") {
    $reviewStatus.style.display = "flex";
    $reviewStatus.innerHTML = `<span style="color:#ef4444">Error: ${data.message}</span>`;
    $btnGenerate.disabled = false;
    $btnQuick.disabled = false;
  }
}

async function loadEvidenceImages(sessionId) {
  try {
    const res = await api("GET", `/generate/${sessionId}/images`);
    evidenceImages = res.images;
    renderImageCarousel(evidenceImages);
  } catch (e) {
    console.error("Failed to load evidence images:", e);
  }
}

async function loadVolume(sessionId) {
  if (volumeLoaded) return;
  const $img = document.getElementById("image-viewer-img");
  const $volumeViewer = document.getElementById("volume-viewer");
  const $loading = document.getElementById("volume-loading");
  const $info = document.getElementById("volume-info");
  if (!$volumeViewer) return;
  if ($loading) $loading.style.display = "flex";
  try {
    const res = await api("GET", `/generate/${sessionId}/volume?max_slices=80`);
    volumeData = { images: res.images || [], total_slices: res.total_slices || 0 };
    if ($loading) $loading.style.display = "none";
    if (volumeData.images.length === 0) return;
    volumeLoaded = true;
    if ($img) $img.style.display = "none";
    $volumeViewer.style.display = "flex";
    if ($info) $info.style.display = "block";
    const $total = document.getElementById("volume-total");
    if ($total) $total.textContent = volumeData.total_slices;
    const slider = document.getElementById("volume-side-slider");
    if (slider) {
      slider.min = 0;
      slider.max = volumeData.images.length - 1;
      slider.value = 0;
      slider.addEventListener("input", function () { showVolumeSlice(parseInt(this.value, 10)); });
    }
    const $volImg = document.getElementById("volume-viewer-img");
    if ($volImg) {
      $volImg.addEventListener("wheel", function (e) {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 1 : -1;
        showVolumeSlice(volumeSliceIndex + delta);
      }, { passive: false });
    }
    showVolumeSlice(0);
    loadComparison();
  } catch (e) {
    console.error("Failed to load volume:", e);
    if ($loading) $loading.style.display = "none";
  }
}

function showVolumeSlice(idx) {
  if (!volumeData.images.length) return;
  idx = Math.max(0, Math.min(idx, volumeData.images.length - 1));
  volumeSliceIndex = idx;
  const img = volumeData.images[idx];
  const $volImg = document.getElementById("volume-viewer-img");
  if ($volImg) $volImg.src = "data:image/png;base64," + img.base64;
  const gIdx = img.global_index != null ? img.global_index + 1 : idx + 1;
  const $cur = document.getElementById("volume-current");
  if ($cur) $cur.textContent = gIdx;
  const slider = document.getElementById("volume-side-slider");
  if (slider) slider.value = idx;
  updateComparisonSlice(idx);
}

async function loadComparison() {
  if (!selectedPatient || !selectedAccession || !patientExams.length) return;
  const idx = patientExams.findIndex((e) => e.accession_number === selectedAccession);
  if (idx <= 0) return;
  const prevExam = patientExams[idx - 1];
  const prevAccession = prevExam.accession_number;
  const $placeholder = document.getElementById("comparison-placeholder");
  const $loading = document.getElementById("comparison-loading");
  const $viewer = document.getElementById("comparison-viewer");
  const $info = document.getElementById("comparison-info");
  if ($placeholder) $placeholder.style.display = "none";
  if ($loading) $loading.style.display = "flex";
  try {
    const res = await api("GET", `/patients/${selectedPatient}/exams/${prevAccession}/comparison`);
    previousComparisonData = res;
    if ($loading) $loading.style.display = "none";
    if (!res.volume || !res.volume.images || res.volume.images.length === 0) {
      if ($placeholder) { $placeholder.textContent = "Aucun volume pour l'examen précédent"; $placeholder.style.display = "flex"; }
      return;
    }
    const vol = res.volume;
    $viewer.style.display = "flex";
    $info.style.display = "block";
    const $total = document.getElementById("comparison-total");
    if ($total) $total.textContent = vol.total_slices;
    const slider = document.getElementById("comparison-side-slider");
    if (slider) {
      slider.min = 0;
      slider.max = vol.images.length - 1;
      slider.value = 0;
      slider.disabled = true;
    }
    updateComparisonSlice(volumeSliceIndex);
  } catch (e) {
    console.error("Failed to load comparison:", e);
    if ($loading) $loading.style.display = "none";
    if ($placeholder) { $placeholder.textContent = "Impossible de charger l'examen précédent"; $placeholder.style.display = "flex"; }
  }
}

function updateComparisonSlice(leftIndex) {
  if (!previousComparisonData || !previousComparisonData.volume || !previousComparisonData.volume.images.length) return;
  const vol = previousComparisonData.volume.images;
  const rightIndex = Math.min(Math.max(0, leftIndex), vol.length - 1);
  const img = vol[rightIndex];
  const $cmpImg = document.getElementById("comparison-viewer-img");
  if ($cmpImg) $cmpImg.src = "data:image/png;base64," + img.base64;
  const gIdx = img.global_index != null ? img.global_index + 1 : rightIndex + 1;
  const $cur = document.getElementById("comparison-current");
  if ($cur) $cur.textContent = gIdx;
  const slider = document.getElementById("comparison-side-slider");
  if (slider) slider.value = rightIndex;
}

function disposeVolume() {
  volumeLoaded = false;
  volumeData = { images: [], total_slices: 0 };
  volumeSliceIndex = 0;
  previousComparisonData = null;
  const $volumeViewer = document.getElementById("volume-viewer");
  const $img = document.getElementById("image-viewer-img");
  const $info = document.getElementById("volume-info");
  if ($volumeViewer) $volumeViewer.style.display = "none";
  if ($info) $info.style.display = "none";
  if ($img) $img.style.display = "";
  const $placeholder = document.getElementById("comparison-placeholder");
  const $cmpViewer = document.getElementById("comparison-viewer");
  const $cmpInfo = document.getElementById("comparison-info");
  if ($placeholder) { $placeholder.style.display = "flex"; $placeholder.textContent = "Aucun examen précédent"; }
  if ($cmpViewer) $cmpViewer.style.display = "none";
  if ($cmpInfo) $cmpInfo.style.display = "none";
}

async function validateCurrentStep() {
  if (!currentSessionId || !currentStepData) return;

  const validatedData = collectFormData(currentStepData.step);
  $reviewActions.style.display = "none";
  $reviewStatus.style.display = "flex";

  const nextStep = currentStepData.step_index + 1;
  const totalSteps = currentStepData.total_steps;
  if (nextStep < totalSteps) {
    $reviewStatus.innerHTML = `<div class="spinner spinner-sm"></div><span>Running next agent&hellip;</span>`;
  } else {
    $reviewStatus.innerHTML = `<div class="spinner spinner-sm"></div><span>Assembling final report&hellip;</span>`;
  }

  try {
    await api("POST", `/generate/${currentSessionId}/validate`, { data: validatedData });
  } catch (e) {
    $reviewStatus.innerHTML = `<span style="color:#ef4444">Validation error: ${e.message}</span>`;
    $reviewActions.style.display = "flex";
  }
}

async function refineCurrentStep() {
  if (!currentSessionId) return;
  const remark = ($refineRemark && $refineRemark.value) ? $refineRemark.value.trim() : "";
  if ($refineError) $refineError.textContent = "";
  if ($refineStatus) $refineStatus.textContent = "Relance en cours…";
  if ($btnRefine) $btnRefine.disabled = true;

  try {
    const res = await fetch(API + `/generate/${currentSessionId}/refine`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ remark }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = body.detail?.message || (typeof body.detail === "string" ? body.detail : body.detail?.error) || res.statusText;
      if ($refineError) $refineError.textContent = msg;
      if ($refineStatus) $refineStatus.textContent = "";
      if ($btnRefine) $btnRefine.disabled = false;
      return;
    }
    currentStepData = body;
    if (currentStepIndex >= 0) stepResults[currentStepIndex] = body;
    renderProposal(body);
    loadEvidenceImages(currentSessionId);
    if ($reviewActions) $reviewActions.style.display = "flex";
    if ($refineRemark) $refineRemark.value = "";
    if ($refineStatus) $refineStatus.textContent = "";
    if ($refineError) $refineError.textContent = "";
    showToast("Proposition mise à jour");
  } catch (e) {
    if ($refineError) $refineError.textContent = e.message || "Erreur réseau.";
    if ($refineStatus) $refineStatus.textContent = "";
  }
  if ($btnRefine) $btnRefine.disabled = false;
}

// ── Progress bar & step navigation ───────────────────────
function updateProgressBar(viewedStep, latestStep) {
  if (latestStep == null) latestStep = viewedStep;
  document.querySelectorAll(".progress-step").forEach((el) => {
    const s = parseInt(el.dataset.step);
    el.classList.toggle("active", s === viewedStep);
    el.classList.toggle("done", s < latestStep);
  });
  const pct = latestStep < 0 ? 0 : ((latestStep + 1) / 6) * 100;
  document.getElementById("progress-bar-fill").style.width = pct + "%";
}

function updateStepNav() {
  const $prev = document.getElementById("btn-step-prev");
  const $next = document.getElementById("btn-step-next");
  const $label = document.getElementById("step-nav-label");
  if ($prev) $prev.disabled = viewedStepIndex <= 0;
  if ($next) $next.disabled = currentStepIndex < 0 || viewedStepIndex >= currentStepIndex;
  if ($label) $label.textContent = `Étape ${viewedStepIndex + 1} / ${Math.max(1, currentStepIndex + 1)}`;
}

function updateActionsVisibility() {
  const hideActions = viewingStepsAfterComplete;
  const isViewingCurrent = viewedStepIndex === currentStepIndex;
  if ($reviewActions) $reviewActions.style.display = hideActions || !isViewingCurrent ? "none" : "flex";
  if ($reviewRefine) $reviewRefine.style.display = hideActions || !isViewingCurrent ? "none" : "block";
}

function backToSteps() {
  if (!stepResults.length) return;
  viewingStepsAfterComplete = true;
  $reportContainer.style.display = "none";
  $reviewContainer.style.display = "";
  if ($stepNavBackReport) $stepNavBackReport.style.display = "";
  viewedStepIndex = currentStepIndex >= 0 ? currentStepIndex : 0;
  const data = stepResults[viewedStepIndex];
  if ($reviewStatus) {
    $reviewStatus.style.display = "flex";
    $reviewStatus.innerHTML = "<span>Rapport généré. Parcourez les étapes avec les flèches.</span>";
  }
  if (data) {
    updateProgressBar(viewedStepIndex, currentStepIndex);
    renderProposal(data);
    applyCarouselForViewedStep();
  }
  updateStepNav();
  updateActionsVisibility();
}

function backToReport() {
  $reviewContainer.style.display = "none";
  $reportContainer.style.display = "";
  if ($stepNavBackReport) $stepNavBackReport.style.display = "none";
}

function applyCarouselForViewedStep() {
  const stored = evidenceImagesByStep[viewedStepIndex];
  if (stored && stored.length) {
    evidenceImages = stored;
    renderImageCarousel(evidenceImages);
  }
}

function goToStepPrev() {
  if (viewedStepIndex <= 0) return;
  viewedStepIndex--;
  const data = stepResults[viewedStepIndex];
  if (data) {
    updateProgressBar(viewedStepIndex, currentStepIndex);
    renderProposal(data);
    applyCarouselForViewedStep();
    updateStepNav();
    updateActionsVisibility();
  }
}

function goToStepNext() {
  if (currentStepIndex < 0 || viewedStepIndex >= currentStepIndex) return;
  viewedStepIndex++;
  const data = stepResults[viewedStepIndex];
  if (data) {
    updateProgressBar(viewedStepIndex, currentStepIndex);
    renderProposal(data);
    applyCarouselForViewedStep();
    updateStepNav();
    updateActionsVisibility();
  }
}

// ── Image carousel ────────────────────────────────────────
function renderImageCarousel(images) {
  if (!images || !images.length) { $reviewImages.style.display = "none"; return; }
  $reviewImages.style.display = "";
  const $thumbs = document.getElementById("image-thumbnails");
  $thumbs.innerHTML = "";
  images.forEach((img, i) => {
    const thumb = document.createElement("div");
    thumb.className = "image-thumb" + (img.is_best_slice ? " best-slice" : "");
    const reason = img.reason || img.label || "";
    thumb.title = reason;
    thumb.innerHTML = `<img src="data:image/png;base64,${img.base64}" alt="${esc(img.label)}" />`;
    if (img.is_best_slice) {
      thumb.innerHTML += `<span class="thumb-badge">S${img.segment}</span>`;
    }
    thumb.addEventListener("click", () => onCarouselThumbClick(i));
    $thumbs.appendChild(thumb);
  });
  if (!volumeLoaded) showImage(images.findIndex(i => i.is_best_slice) || 0);
}

function onCarouselThumbClick(idx) {
  if (!evidenceImages || idx < 0) return;
  document.querySelectorAll(".image-thumb").forEach((el, i) => {
    el.classList.toggle("selected", i === idx);
  });
  if (volumeLoaded && volumeData.images.length) {
    const wantGlobal = evidenceImages[idx].global_index;
    if (wantGlobal != null) {
      let bestJ = 0;
      let bestDist = Infinity;
      volumeData.images.forEach((img, j) => {
        const g = img.global_index != null ? img.global_index : j;
        const d = Math.abs(g - wantGlobal);
        if (d < bestDist) {
          bestDist = d;
          bestJ = j;
        }
      });
      showVolumeSlice(bestJ);
    }
  } else {
    showImage(idx);
  }
}

function showImage(idx) {
  if (!evidenceImages || idx < 0 || volumeLoaded) return;
  const img = evidenceImages[idx];
  const $imgEl = document.getElementById("image-viewer-img");
  if ($imgEl) $imgEl.src = "data:image/png;base64," + img.base64;
  document.getElementById("image-viewer-label").textContent = img.label || "";
  const $reason = document.getElementById("image-viewer-reason");
  if ($reason) $reason.textContent = img.reason || "";
  document.querySelectorAll(".image-thumb").forEach((el, i) => {
    el.classList.toggle("selected", i === idx);
  });
}

// ══════════════════════════════════════════════════════════
//  EDITABLE PROPOSAL FORMS
// ══════════════════════════════════════════════════════════

function renderProposal(stepData) {
  const { step, proposal, num_sub_agents, agent_info, image_legend } = stepData;
  let html = `<h3 class="review-step-title">${stepLabel(step)}</h3>`;

  const n = num_sub_agents != null ? num_sub_agents : 1;
  html += `<p class="review-step-agents">${n} agent${n > 1 ? "s" : ""} sur cette tâche</p>`;
  if (n > 1) {
    html += `<p class="review-step-meta">La confiance affichée est la moyenne des ${n} analyses.</p>`;
  }

  if (agent_info && (agent_info.name || agent_info.role || agent_info.model_id)) {
    html += `<div class="review-agent-info">`;
    if (agent_info.name) html += `<span class="agent-name">${esc(agent_info.name)}</span>`;
    if (agent_info.model_id) html += `<span class="agent-model">Modèle : ${esc(agent_info.model_id)}</span>`;
    if (agent_info.role) html += `<span class="agent-role">${esc(agent_info.role)}</span>`;
    html += `</div>`;
  }

  const $legend = document.getElementById("image-legend");
  if ($legend) {
    $legend.textContent = "";
    if (image_legend) {
      $legend.innerHTML = `<strong>Pourquoi ces images ?</strong> ${esc(image_legend)}`;
    }
  }

  if (step === "lesions") {
    html += renderLesionsForm(proposal);
  } else if (step === "infiltration") {
    html += renderInfiltrationForm(proposal);
  } else if (step === "negative_findings") {
    html += renderNegativeFindingsForm(proposal);
  } else if (step === "organ_assessments") {
    html += renderOrganAssessmentsForm(proposal);
  } else if (step === "incidental_findings") {
    html += renderIncidentalFindingsForm(proposal);
  } else if (step === "conclusions") {
    html += renderConclusionsForm(proposal);
  }

  $reviewProposal.innerHTML = html;
}

function stepLabel(step) {
  const labels = {
    lesions: "Lesion Location & Characterization",
    infiltration: "Infiltration Assessment",
    negative_findings: "Negative Findings",
    organ_assessments: "Organ Assessments",
    incidental_findings: "Incidental Findings",
    conclusions: "Conclusions",
  };
  return labels[step] || step;
}

// ── Lesions form ──────────────────────────────────────────
function renderLesionsForm(lesions) {
  if (!lesions.length) return '<p class="form-empty">No lesions detected by the agent.</p>';
  let html = '<div class="form-list" id="form-lesions">';
  lesions.forEach((l, i) => {
    html += `
      <div class="form-card" data-idx="${i}">
        <div class="form-card-header">
          <span class="form-card-num">#${i + 1}</span>
          <button class="btn-icon-sm btn-remove" onclick="removeLesion(${i})" title="Remove">&times;</button>
        </div>
        <label class="form-label">Location</label>
        <input type="text" class="form-input" name="location" value="${esc(l.location)}" />
        <label class="form-label">Characterization</label>
        <textarea class="form-textarea" name="characterization" rows="3">${esc(l.characterization || "")}</textarea>
        ${confDisplayRow(Math.round((l.confidence || 0) * 100), "confidence")}
      </div>`;
  });
  html += '</div>';
  html += '<button class="btn btn-secondary btn-add" onclick="addLesion()">+ Add lesion</button>';
  return html;
}

function addLesion() {
  const list = document.getElementById("form-lesions");
  const idx = list.children.length;
  const card = document.createElement("div");
  card.className = "form-card";
  card.dataset.idx = idx;
  card.innerHTML = `
    <div class="form-card-header">
      <span class="form-card-num">#${idx + 1}</span>
      <button class="btn-icon-sm btn-remove" onclick="removeLesion(${idx})" title="Remove">&times;</button>
    </div>
    <label class="form-label">Location</label>
    <input type="text" class="form-input" name="location" value="" />
    <label class="form-label">Characterization</label>
    <textarea class="form-textarea" name="characterization" rows="3"></textarea>
    ${confDisplayRow(50, "confidence")}
  `;
  list.appendChild(card);
}

function removeLesion(idx) {
  const list = document.getElementById("form-lesions");
  const card = list.querySelector(`[data-idx="${idx}"]`);
  if (card) card.remove();
}

// ── Infiltration form ─────────────────────────────────────
function renderInfiltrationForm(inf) {
  let html = '<div id="form-infiltration">';
  html += `<label class="form-label">Summary</label>
    <textarea class="form-textarea" name="summary" rows="2">${esc(inf.summary || "")}</textarea>`;
  html += confDisplayRow(Math.round((inf.confidence || 0) * 100), "confidence");

  if (inf.indicators && inf.indicators.length) {
    html += '<div class="form-label" style="margin-top:.8rem">Indicators</div>';
    inf.indicators.forEach((ind, i) => {
      html += `
        <div class="form-checkbox-row">
          <input type="checkbox" id="ind-${i}" data-idx="${i}" ${ind.present ? "checked" : ""} />
          <label for="ind-${i}">${ind.name.replace(/_/g, " ")} <span style="color:#64748b">(${ind.certainty ?? "—"})</span></label>
          <input type="hidden" name="ind-name-${i}" value="${esc(ind.name)}" />
          <input type="hidden" name="ind-cat-${i}" value="${esc(ind.category)}" />
          <input type="hidden" name="ind-cert-${i}" value="${esc(ind.certainty ?? "")}" />
          <input type="hidden" name="ind-desc-${i}" value="${esc(ind.description || "")}" />
        </div>`;
    });
  }
  html += '</div>';
  return html;
}

// ── Negative findings form ────────────────────────────────
function renderNegativeFindingsForm(data) {
  const findings = data.findings || [];
  let html = '<div id="form-neg-findings">';
  html += confDisplayRow(Math.round((data.confidence || 0) * 100), "confidence");
  html += '<div class="form-label">Findings (uncheck to remove)</div>';
  findings.forEach((nf, i) => {
    html += `
      <div class="form-checkbox-row">
        <input type="checkbox" id="nf-${i}" checked />
        <label for="nf-${i}">${esc(nf)}</label>
      </div>`;
  });
  html += `<div style="margin-top:.5rem">
    <input type="text" class="form-input" id="nf-add-input" placeholder="Add a finding&hellip;" style="display:inline-block;width:70%" />
    <button class="btn btn-secondary" onclick="addNegFinding()" style="display:inline-block;width:25%">+ Add</button>
  </div>`;
  html += '</div>';
  return html;
}

function addNegFinding() {
  const input = document.getElementById("nf-add-input");
  const val = input.value.trim();
  if (!val) return;
  const container = document.getElementById("form-neg-findings");
  const idx = container.querySelectorAll(".form-checkbox-row").length;
  const row = document.createElement("div");
  row.className = "form-checkbox-row";
  row.innerHTML = `<input type="checkbox" id="nf-${idx}" checked /><label for="nf-${idx}">${esc(val)}</label>`;
  container.querySelector("div[style]").before(row);
  input.value = "";
}

// ── Organ assessments form ────────────────────────────────
function renderOrganAssessmentsForm(assessments) {
  let html = '<div class="form-list" id="form-organs">';
  assessments.forEach((oa, i) => {
    html += `
      <div class="form-card form-card--compact" data-idx="${i}">
        <div class="form-card-header">
          <span class="organ-icon">${oa.is_normal ? "\u2705" : "\u274C"}</span>
          <input type="text" class="form-input form-input--inline" name="organ" value="${esc(oa.organ)}" style="font-weight:600;width:160px" />
          <label class="form-toggle-label">
            <input type="checkbox" name="is_normal" ${oa.is_normal ? "checked" : ""} onchange="this.closest('.form-card').querySelector('.organ-icon').textContent=this.checked?'\u2705':'\u274C'" />
            Normal
          </label>
          <button class="btn-icon-sm btn-remove" onclick="this.closest('.form-card').remove()" title="Remove">&times;</button>
        </div>
        <textarea class="form-textarea" name="finding" rows="2">${esc(oa.finding)}</textarea>
      </div>`;
  });
  html += '</div>';
  return html;
}

// ── Incidental findings form ──────────────────────────────
function renderIncidentalFindingsForm(findings) {
  let html = '<div class="form-list" id="form-incidentals">';
  findings.forEach((inc, i) => {
    html += `
      <div class="form-card form-card--compact" data-idx="${i}">
        <div class="form-card-header">
          <label class="form-toggle-label">
            <input type="checkbox" name="is_new" ${inc.is_new ? "checked" : ""} />
            NEW
          </label>
          <button class="btn-icon-sm btn-remove" onclick="this.closest('.form-card').remove()" title="Remove">&times;</button>
        </div>
        <label class="form-label">Location</label>
        <input type="text" class="form-input" name="location" value="${esc(inc.location)}" />
        <label class="form-label">Description</label>
        <input type="text" class="form-input" name="description" value="${esc(inc.description)}" />
      </div>`;
  });
  html += '</div>';
  html += '<button class="btn btn-secondary btn-add" onclick="addIncidental()">+ Add finding</button>';
  return html;
}

function addIncidental() {
  const list = document.getElementById("form-incidentals");
  const idx = list.children.length;
  const card = document.createElement("div");
  card.className = "form-card form-card--compact";
  card.dataset.idx = idx;
  card.innerHTML = `
    <div class="form-card-header">
      <label class="form-toggle-label"><input type="checkbox" name="is_new" checked /> NEW</label>
      <button class="btn-icon-sm btn-remove" onclick="this.closest('.form-card').remove()" title="Remove">&times;</button>
    </div>
    <label class="form-label">Location</label>
    <input type="text" class="form-input" name="location" value="" />
    <label class="form-label">Description</label>
    <input type="text" class="form-input" name="description" value="" />
  `;
  list.appendChild(card);
}

// ── Conclusions form ──────────────────────────────────────
function renderConclusionsForm(data) {
  let html = '<div id="form-conclusions">';
  if (data.recist_response) {
    html += `<div style="margin-bottom:.75rem">
      <span class="recist-badge recist-${data.recist_response}" style="font-size:1rem;padding:.3rem .8rem">${data.recist_response}</span>
      <span style="margin-left:.5rem;font-size:.8rem;color:#94a3b8">RECIST 1.1</span>
    </div>`;
    if (data.recist_justification) {
      html += `<p style="font-size:.85rem;color:#94a3b8;margin-bottom:.75rem">${esc(data.recist_justification)}</p>`;
    }
  }
  html += '<div class="form-label">Key Findings</div>';
  html += '<div id="kf-list">';
  (data.key_findings || []).forEach((kf, i) => {
    html += `<div class="form-kf-row">
      <textarea class="form-textarea" name="kf" rows="2">${esc(kf)}</textarea>
      <button class="btn-icon-sm btn-remove" onclick="this.parentElement.remove()" title="Remove">&times;</button>
    </div>`;
  });
  html += '</div>';
  html += '<button class="btn btn-secondary btn-add" onclick="addKeyFinding()" style="margin-bottom:.75rem">+ Add finding</button>';
  html += `<label class="form-label">Recommendation</label>
    <textarea class="form-textarea" name="recommendation" rows="3">${esc(data.recommendation || "")}</textarea>`;
  html += confDisplayRow(Math.round(((data.conclusions_confidence || 0.5) * 100)), "confidence");
  html += '</div>';
  return html;
}

function addKeyFinding() {
  const list = document.getElementById("kf-list");
  const row = document.createElement("div");
  row.className = "form-kf-row";
  row.innerHTML = `<textarea class="form-textarea" name="kf" rows="2"></textarea>
    <button class="btn-icon-sm btn-remove" onclick="this.parentElement.remove()" title="Remove">&times;</button>`;
  list.appendChild(row);
}

// ══════════════════════════════════════════════════════════
//  COLLECT EDITED DATA
// ══════════════════════════════════════════════════════════

function collectFormData(step) {
  if (step === "lesions") {
    const cards = document.querySelectorAll("#form-lesions .form-card");
    const lesions = [];
    cards.forEach((card) => {
      lesions.push({
        location: card.querySelector('[name="location"]').value,
        characterization: card.querySelector('[name="characterization"]').value,
        confidence: parseInt(card.querySelector('[name="confidence"]').value) / 100,
      });
    });
    return { lesions };
  }

  if (step === "infiltration") {
    const form = document.getElementById("form-infiltration");
    const indicators = [];
    form.querySelectorAll('.form-checkbox-row').forEach((row, i) => {
      indicators.push({
        name: row.querySelector(`[name="ind-name-${i}"]`).value,
        category: row.querySelector(`[name="ind-cat-${i}"]`).value,
        present: row.querySelector('input[type="checkbox"]').checked,
        certainty: row.querySelector(`[name="ind-cert-${i}"]`).value,
        description: row.querySelector(`[name="ind-desc-${i}"]`).value,
      });
    });
    return {
      summary: form.querySelector('[name="summary"]').value,
      confidence: parseInt(form.querySelector('[name="confidence"]').value) / 100,
      indicators,
      mimic_context: currentStepData.proposal.mimic_context || {},
      temporal: currentStepData.proposal.temporal || {},
    };
  }

  if (step === "negative_findings") {
    const form = document.getElementById("form-neg-findings");
    const findings = [];
    form.querySelectorAll('.form-checkbox-row').forEach((row) => {
      if (row.querySelector('input[type="checkbox"]').checked) {
        findings.push(row.querySelector('label').textContent.trim());
      }
    });
    return {
      findings,
      confidence: parseInt(form.querySelector('[name="confidence"]').value) / 100,
    };
  }

  if (step === "organ_assessments") {
    const cards = document.querySelectorAll("#form-organs .form-card");
    const assessments = [];
    cards.forEach((card) => {
      assessments.push({
        organ: card.querySelector('[name="organ"]').value,
        finding: card.querySelector('[name="finding"]').value,
        is_normal: card.querySelector('[name="is_normal"]').checked,
        confidence: 0.8,
      });
    });
    return { assessments };
  }

  if (step === "incidental_findings") {
    const cards = document.querySelectorAll("#form-incidentals .form-card");
    const findings = [];
    cards.forEach((card) => {
      findings.push({
        location: card.querySelector('[name="location"]').value,
        description: card.querySelector('[name="description"]').value,
        is_new: card.querySelector('[name="is_new"]').checked,
        confidence: 0.8,
      });
    });
    return { findings };
  }

  if (step === "conclusions") {
    const form = document.getElementById("form-conclusions");
    const kfs = [];
    form.querySelectorAll('[name="kf"]').forEach((ta) => {
      const v = ta.value.trim();
      if (v) kfs.push(v);
    });
    return {
      key_findings: kfs,
      recommendation: form.querySelector('[name="recommendation"]').value || null,
      conclusions_confidence: parseInt(form.querySelector('[name="confidence"]').value) / 100,
    };
  }

  return {};
}

// ── Escape helper ─────────────────────────────────────────
function esc(s) {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

// ══════════════════════════════════════════════════════════
//  QUICK GENERATE (one-shot, backward compatible)
// ══════════════════════════════════════════════════════════

async function quickGenerate() {
  if (!selectedPatient || !selectedAccession) return;
  hideAll();
  $loadingOverlay.style.display = "";
  $btnGenerate.disabled = true;
  $btnQuick.disabled = true;

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
    $btnQuick.disabled = false;
  }
}

// ══════════════════════════════════════════════════════════
//  REPORT RENDERING (final report, same as before)
// ══════════════════════════════════════════════════════════

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
        <div class="kv-item"><div class="kv-label">${k}</div><div class="kv-value">${v}</div></div>
      `).join("")}
    </div>`;
}

function renderStudyTechnique(st) {
  const items = [
    ["Study Description", st.study_description],
    ["Contrast", [st.contrast, st.contrast_agent].filter(Boolean).join(" \u2014 ") || null],
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
        <div class="kv-item"><div class="kv-label">${k}</div><div class="kv-value kv-value--mono">${v}</div></div>
      `).join("")}
    </div>`;
}

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

function fmtDims(dims) { if (!dims || !dims.length) return "\u2014"; return dims.map(d => d.toFixed(1)).join(" x ") + " mm"; }
function fmtPct(v) { if (v == null) return "\u2014"; return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`; }
function fmtVol(v) { if (v == null) return "\u2014"; return v >= 1000 ? `${(v / 1000).toFixed(2)} mL` : `${v.toFixed(0)} mm\u00B3`; }

function renderDeterminist(det) {
  let html = "";

  // ── RECIST badges (classic + volumetric) ───────────────
  const adv = det.advanced_metrics || {};
  if (det.recist_conclusion || adv.v_recist_conclusion) {
    html += `<div class="recist-row">`;
    if (det.recist_conclusion) {
      html += `<div class="recist-item"><span class="recist-badge recist-${det.recist_conclusion}">${det.recist_conclusion}</span><span class="recist-sub">RECIST 1.1</span></div>`;
    }
    if (adv.v_recist_conclusion) {
      html += `<div class="recist-item"><span class="recist-badge recist-${adv.v_recist_conclusion}">${adv.v_recist_conclusion}</span><span class="recist-sub">Volumetric RECIST</span></div>`;
    }
    html += `</div>`;
    if (adv.v_recist_justification) {
      html += `<p class="v-recist-justification">${esc(adv.v_recist_justification)}</p>`;
    }
  }

  // ── Tumor Burden + Kinetics summary cards ──────────────
  const hasAdvCards = adv.total_tumor_burden_ml != null || adv.days_since_previous_exam != null || adv.trend_direction;
  if (hasAdvCards) {
    html += `<div class="metrics-cards">`;

    if (adv.total_tumor_burden_ml != null) {
      const pctClass = adv.tumor_burden_change_percent != null
        ? (adv.tumor_burden_change_percent > 5 ? "metric-bad" : adv.tumor_burden_change_percent < -5 ? "metric-good" : "metric-neutral")
        : "";
      html += `<div class="metric-card">
        <div class="metric-label">Tumor Burden</div>
        <div class="metric-value">${adv.total_tumor_burden_ml.toFixed(1)} <span class="metric-unit">mL</span></div>
        ${adv.previous_total_tumor_burden_ml != null ? `<div class="metric-prev">prev. ${adv.previous_total_tumor_burden_ml.toFixed(1)} mL</div>` : ""}
        ${adv.tumor_burden_change_percent != null ? `<div class="metric-change ${pctClass}">${fmtPct(adv.tumor_burden_change_percent)}</div>` : ""}
      </div>`;
    }

    if (adv.days_since_previous_exam != null) {
      html += `<div class="metric-card">
        <div class="metric-label">Interval</div>
        <div class="metric-value">${adv.days_since_previous_exam} <span class="metric-unit">days</span></div>
      </div>`;
    }

    if (adv.trend_direction) {
      const trendIcon = { improving: "\u2198\uFE0F", stable: "\u27A1\uFE0F", worsening: "\u2197\uFE0F", accelerating: "\u26A0\uFE0F", mixed: "\u2194\uFE0F" };
      html += `<div class="metric-card">
        <div class="metric-label">Trend</div>
        <div class="metric-value trend-${adv.trend_direction}">${trendIcon[adv.trend_direction] || ""} ${adv.trend_direction}</div>
        ${adv.consecutive_stable_exams ? `<div class="metric-prev">${adv.consecutive_stable_exams} consecutive stable</div>` : ""}
        ${adv.change_from_nadir_percent != null && adv.change_from_nadir_percent > 0 ? `<div class="metric-change metric-bad">+${adv.change_from_nadir_percent.toFixed(1)}% from nadir</div>` : ""}
      </div>`;
    }

    if (adv.nadir_sum_of_diameters_mm != null) {
      html += `<div class="metric-card">
        <div class="metric-label">Nadir (best response)</div>
        <div class="metric-value">${adv.nadir_sum_of_diameters_mm.toFixed(1)} <span class="metric-unit">mm</span></div>
        <div class="metric-prev">sum of diameters</div>
      </div>`;
    }

    html += `</div>`;
  }

  // ── Lesion table with advanced columns ─────────────────
  if (det.lesions.length) {
    const lmMap = {};
    (adv.lesion_metrics || []).forEach(lm => { lmMap[lm.segment_number] = lm; });

    html += `<table class="lesion-table"><thead><tr>
      <th>#</th><th>Long. Diam.</th><th>Short Axis</th><th>Previous</th><th>Evolution</th><th>Change</th>
      <th>Volume</th><th>Vol. Change</th>
      <th>TGR</th><th>Doubling</th><th>HU</th>
      <th>Slice</th>
    </tr></thead><tbody>`;

    det.lesions.forEach((l, i) => {
      const lm = lmMap[i + 1] || {};
      const tgr = lm.growth_rate_percent_per_month != null ? `${lm.growth_rate_percent_per_month >= 0 ? "+" : ""}${lm.growth_rate_percent_per_month.toFixed(1)}%/mo` : "\u2014";
      const tdt = lm.doubling_time_days != null ? `${lm.doubling_time_days.toFixed(0)}d` : "\u2014";

      let huCell = "\u2014";
      if (lm.hu_heterogeneity_index != null) {
        const hetClass = lm.hu_heterogeneity_index > 0.5 ? "het-high" : lm.hu_heterogeneity_index > 0.3 ? "het-med" : "het-low";
        huCell = `<span class="hu-badge ${hetClass}" title="Mean: ${lm.hu_mean?.toFixed(0)} HU, Std: ${lm.hu_std?.toFixed(0)} HU">${lm.hu_mean?.toFixed(0)}\u00B1${lm.hu_std?.toFixed(0)} <span class="het-idx">(${lm.hu_heterogeneity_index.toFixed(2)})</span></span>`;
      }

      const tdtClass = lm.doubling_time_days != null && lm.doubling_time_days > 0 && lm.doubling_time_days < 400 ? "tdt-fast" : "";
      const tgrClass = lm.growth_rate_percent_per_month != null && lm.growth_rate_percent_per_month > 5 ? "tgr-fast" : "";

      html += `<tr>
        <td>${i + 1}</td>
        <td class="mono">${fmtDims(l.dimensions_mm)}</td>
        <td class="mono">${l.short_axis_mm != null ? l.short_axis_mm.toFixed(1) + " mm" : "\u2014"}</td>
        <td class="mono">${fmtDims(l.previous_dimensions_mm)}</td>
        <td>${evolutionTag(l.evolution)}</td>
        <td class="mono">${fmtPct(l.change_percent)}</td>
        <td class="mono">${fmtVol(l.volume_mm3)}</td>
        <td class="mono">${fmtPct(l.volume_change_percent)}</td>
        <td class="mono ${tgrClass}">${tgr}</td>
        <td class="mono ${tdtClass}">${tdt}</td>
        <td class="mono">${huCell}</td>
        <td class="mono">${l.slice_index != null ? "img " + l.slice_index : "\u2014"}</td>
      </tr>`;
    });
    html += `</tbody></table>`;
  }

  // ── Trend chart (sparkline-style) ──────────────────────
  if (adv.trend && adv.trend.length >= 2) {
    html += `<div class="trend-section">`;
    html += `<div class="trend-title">Tumor Burden Trajectory</div>`;
    html += `<div class="trend-timeline">`;
    adv.trend.forEach((pt, i) => {
      const isLast = i === adv.trend.length - 1;
      const vol = pt.total_volume_ml != null ? `${pt.total_volume_ml.toFixed(1)} mL` : "\u2014";
      const sum = pt.sum_of_diameters_mm != null ? `\u2211 ${pt.sum_of_diameters_mm.toFixed(1)} mm` : "";
      html += `<div class="trend-point ${isLast ? "trend-current" : ""}">
        <div class="trend-date">${pt.study_date}</div>
        <div class="trend-dot"></div>
        <div class="trend-details">
          <span class="trend-vol">${vol}</span>
          <span class="trend-sum">${sum}</span>
          <span class="trend-count">${pt.lesion_count} lesion${pt.lesion_count > 1 ? "s" : ""}</span>
        </div>
      </div>`;
    });
    html += `</div></div>`;
  }

  document.getElementById("report-det-body").innerHTML = html || "<p style='color:#64748b'>No deterministic findings.</p>";
}

function confBadge(score) {
  if (score == null) return "";
  const pct = Math.round(score * 100);
  const cls = score >= 0.7 ? "conf-high" : score >= 0.4 ? "conf-med" : "conf-low";
  return `<span class="confidence-badge ${cls}"><span class="conf-donut" style="--pct: ${pct}%"></span>${pct}%</span>`;
}

function confDisplayRow(pct, name) {
  const cls = pct >= 70 ? "conf-high" : pct >= 40 ? "conf-med" : "conf-low";
  return `<div class="conf-display-row"><span class="form-label">Confidence</span><span class="confidence-badge ${cls}"><span class="conf-donut" style="--pct: ${pct}%"></span>${pct}%</span><input type="hidden" name="${name}" value="${pct}" /></div>`;
}

function renderInfiltration(inf) {
  if (!inf) return "";
  const level = inf.level || "none";
  const hasIndicators = inf.present_indicators && inf.present_indicators.length > 0;
  if (level === "none" && !hasIndicators) {
    return `<div class="agent-subsection"><div class="agent-subsection-title">Infiltration ${confBadge(inf.confidence)}</div><div class="infiltration-box">No signs of infiltration detected.</div></div>`;
  }
  const levelLabel = level.replace(/_/g, " ");
  let html = `<div class="agent-subsection"><div class="agent-subsection-title">Infiltration Assessment ${confBadge(inf.confidence)}</div><div class="infiltration-box"><div class="infiltration-header"><span class="infiltration-level level-${level}">${levelLabel}</span><span class="infiltration-score">Score: ${(inf.final_score || 0).toFixed(2)} (raw: ${(inf.raw_score || 0).toFixed(2)})</span></div>`;
  if (inf.summary) html += `<div class="infiltration-summary">${inf.summary}</div>`;
  if (inf.indicators && inf.indicators.length) {
    const present = inf.indicators.filter(i => i.present);
    if (present.length) {
      html += `<div style="font-size:.7rem;text-transform:uppercase;color:#64748b;margin-top:.5rem;font-weight:600">Indicators</div><div class="indicators-grid">${present.map(ind => `<div class="indicator-item present"><span class="indicator-name">${ind.name.replace(/_/g, " ")}</span><span class="indicator-certainty">${ind.certainty ?? "—"}</span></div>`).join("")}</div>`;
    }
  }
  html += `</div></div>`;
  return html;
}

function renderAgent(agt) {
  let html = "";
  if (agt.lesions.length) {
    html += `<div class="agent-subsection"><div class="agent-subsection-title">Lesion Location & Characterization</div><table class="lesion-table"><thead><tr><th>#</th><th>Location</th><th>Characterization</th><th>Conf.</th></tr></thead><tbody>${agt.lesions.map((l, i) => `<tr><td>${i + 1}</td><td>${l.location}</td><td>${l.characterization || "\u2014"}</td><td>${confBadge(l.confidence)}</td></tr>`).join("")}</tbody></table></div>`;
  }
  html += renderInfiltration(agt.infiltration);
  if (agt.organ_assessments.length) {
    html += `<div class="agent-subsection"><div class="agent-subsection-title">Organ Assessments</div><div class="organ-list">${agt.organ_assessments.map(oa => `<div class="organ-item"><span class="organ-icon">${oa.is_normal ? "\u2705" : "\u274C"}</span><span class="organ-name">${oa.organ}</span><span class="organ-finding">${oa.finding}</span>${confBadge(oa.confidence)}</div>`).join("")}</div></div>`;
  }
  if (agt.negative_findings.length) {
    html += `<div class="agent-subsection"><div class="agent-subsection-title">Negative Findings ${confBadge(agt.negative_findings_confidence)}</div><div class="pills">${agt.negative_findings.map(nf => `<span class="pill">${nf}</span>`).join("")}</div></div>`;
  }
  if (agt.incidental_findings.length) {
    html += `<div class="agent-subsection"><div class="agent-subsection-title">Incidental Findings</div>${agt.incidental_findings.map(inc => `<div class="incidental-item">${inc.is_new ? '<span class="badge-new">NEW</span>' : ""}<strong>${inc.location}</strong>: ${inc.description} ${confBadge(inc.confidence)}</div>`).join("")}</div>`;
  }
  document.getElementById("report-agent-body").innerHTML = html || "<p style='color:#64748b'>No agent findings.</p>";
}

function renderConclusions(c) {
  let html = "";
  if (c.recist_response) {
    html += `<div class="conclusions-recist"><span class="recist-badge recist-${c.recist_response}" style="font-size:1.1rem;padding:.35rem 1rem">${c.recist_response}</span><span style="font-size:.85rem;color:#94a3b8">RECIST 1.1 Response</span></div>`;
  }
  if (c.recist_justification) html += `<div class="conclusions-justification">${c.recist_justification}</div>`;
  if (c.sum_of_diameters_mm != null) {
    html += `<div class="kv-grid" style="margin-bottom:.75rem"><div class="kv-item"><div class="kv-label">Sum of Diameters (current)</div><div class="kv-value kv-value--mono">${c.sum_of_diameters_mm.toFixed(1)} mm</div></div>${c.previous_sum_of_diameters_mm != null ? `<div class="kv-item"><div class="kv-label">Sum of Diameters (previous)</div><div class="kv-value kv-value--mono">${c.previous_sum_of_diameters_mm.toFixed(1)} mm</div></div>` : ""}</div>`;
  }
  if (c.key_findings.length) {
    html += `<div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.4rem"><span style="font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;color:#64748b;font-weight:600">Key Findings</span>${confBadge(c.conclusions_confidence)}</div><ul class="key-findings-list">${c.key_findings.map(kf => `<li>${kf}</li>`).join("")}</ul>`;
  }
  if (c.recommendation) {
    html += `<div class="recommendation-box"><div class="recommendation-label">Recommendation</div>${c.recommendation}</div>`;
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

function exportPDF() {
  if (!currentReport) {
    showToast("No report to export");
    return;
  }
  const JsPDF = (typeof jspdf !== "undefined" && jspdf.jsPDF) ? jspdf.jsPDF : (typeof window !== "undefined" && window.jspdf && window.jspdf.jsPDF) ? window.jspdf.jsPDF : null;
  if (!JsPDF) {
    showToast("PDF library not loaded");
    return;
  }
  const r = currentReport;
  const M = 20;
  const MR = 20;
  const W = 210 - M - MR;
  const pageH = 297;
  const footerH = 14;
  const maxY = pageH - M - footerH;
  const lineH = 5;
  const doc = new JsPDF({ unit: "mm", format: "a4", orientation: "portrait" });
  let y = M;
  let pageNum = 1;

  const COL_PRIMARY = [41, 98, 168];
  const COL_TEXT = [40, 40, 40];
  const COL_MUTED = [110, 110, 110];
  const COL_LINE = [200, 210, 225];
  const COL_BG_HEADER = [235, 242, 250];

  function sanitize(text) {
    return String(text || "")
      .replace(/\u2265/g, ">=")
      .replace(/\u2264/g, "<=")
      .replace(/\u00b1/g, "+/-")
      .replace(/\u00d7/g, "x")
      .replace(/\u2013/g, "-")
      .replace(/\u2014/g, " - ")
      .replace(/\u2018|\u2019/g, "'")
      .replace(/\u201c|\u201d/g, '"')
      .replace(/\u2022/g, "-")
      .replace(/\u00e9/g, "e")
      .replace(/\u00e8/g, "e")
      .replace(/\u00ea/g, "e")
      .replace(/\u00eb/g, "e")
      .replace(/\u00e0/g, "a")
      .replace(/\u00e2/g, "a")
      .replace(/\u00f4/g, "o")
      .replace(/\u00f9/g, "u")
      .replace(/\u00fb/g, "u")
      .replace(/\u00ee/g, "i")
      .replace(/\u00ef/g, "i")
      .replace(/\u00e7/g, "c")
      .replace(/[^\x20-\x7E\n]/g, "");
  }

  function addFooter() {
    doc.setFontSize(7);
    doc.setFont("helvetica", "normal");
    doc.setTextColor(...COL_MUTED);
    const footY = pageH - 10;
    doc.setDrawColor(...COL_LINE);
    doc.setLineWidth(0.3);
    doc.line(M, footY - 3, 210 - MR, footY - 3);
    doc.text(`Page ${pageNum}`, 210 - MR, footY, { align: "right" });
    doc.text("Generated by OncoAssist AI", M, footY);
    doc.setTextColor(...COL_TEXT);
  }

  function newPage() {
    addFooter();
    doc.addPage();
    pageNum++;
    y = M;
  }

  function ensureSpace(needed) {
    if (y + needed > maxY) newPage();
  }

  function addLine(text, opts = {}) {
    const size = opts.size || 9;
    const style = opts.bold ? "bold" : "normal";
    doc.setFontSize(size);
    doc.setFont("helvetica", style);
    if (opts.color) doc.setTextColor(...opts.color);
    else doc.setTextColor(...COL_TEXT);
    const clean = sanitize(text);
    const lines = doc.splitTextToSize(clean, opts.indent ? W - opts.indent : W);
    const xBase = M + (opts.indent || 0);
    for (const line of lines) {
      ensureSpace(lineH);
      doc.text(line, xBase, y);
      y += lineH;
    }
    if (opts.space) y += opts.space;
    return y;
  }

  function addHRule() {
    doc.setDrawColor(...COL_LINE);
    doc.setLineWidth(0.3);
    doc.line(M, y, 210 - MR, y);
    y += 2;
  }

  function addSection(title) {
    ensureSpace(14);
    y += 3;
    doc.setFillColor(...COL_BG_HEADER);
    doc.roundedRect(M, y - 4, W, 7, 1.5, 1.5, "F");
    doc.setFontSize(10);
    doc.setFont("helvetica", "bold");
    doc.setTextColor(...COL_PRIMARY);
    doc.text(sanitize(title), M + 3, y);
    doc.setTextColor(...COL_TEXT);
    y += 6;
  }

  function addLabelValue(label, value, opts = {}) {
    const size = opts.size || 9;
    doc.setFontSize(size);
    doc.setFont("helvetica", "bold");
    doc.setTextColor(...COL_MUTED);
    const labelW = doc.getTextWidth(sanitize(label) + "  ");
    ensureSpace(lineH);
    doc.text(sanitize(label), M + (opts.indent || 0), y);
    doc.setFont("helvetica", "normal");
    doc.setTextColor(...COL_TEXT);
    const valLines = doc.splitTextToSize(sanitize(value), W - labelW - (opts.indent || 0));
    valLines.forEach((vl, vi) => {
      if (vi > 0) { ensureSpace(lineH); }
      doc.text(vl, M + (opts.indent || 0) + labelW, y);
      if (vi < valLines.length - 1) y += lineH;
    });
    y += lineH;
    if (opts.space) y += opts.space;
  }

  doc.setFillColor(...COL_PRIMARY);
  doc.rect(0, 0, 210, 32, "F");
  doc.setFontSize(18);
  doc.setFont("helvetica", "bold");
  doc.setTextColor(255, 255, 255);
  doc.text("Clinical Report", M, 16);
  doc.setFontSize(10);
  doc.setFont("helvetica", "normal");
  doc.text(sanitize(`Patient: ${r.patient_id}  |  Accession: ${r.accession_number}`), M, 24);
  doc.setTextColor(...COL_TEXT);
  y = 40;

  addSection("Clinical Information");
  const ci = r.clinical_information;
  if (ci.primary_diagnosis) addLabelValue("Primary diagnosis:", ci.primary_diagnosis);
  if (ci.clinical_context) addLabelValue("Context:", ci.clinical_context);
  if (ci.patient_sex) addLabelValue("Sex:", ci.patient_sex);
  if (ci.patient_age) addLabelValue("Age:", String(ci.patient_age));

  addSection("Study Technique");
  const st = r.study_technique;
  if (st.study_description) addLine(st.study_description);
  if (st.contrast || st.contrast_agent) addLabelValue("Contrast:", [st.contrast, st.contrast_agent].filter(Boolean).join(" - ") || "-");
  if (st.scanner_model) addLabelValue("Scanner:", st.scanner_model);
  if (st.slice_thickness_mm) addLabelValue("Slice thickness:", st.slice_thickness_mm + " mm");
  if (st.comparison_study_date) addLabelValue("Comparison:", st.comparison_study_date);

  addSection("Findings - Deterministic");
  const det = r.report.report_determinist;
  if (det.recist_conclusion) addLabelValue("RECIST 1.1:", det.recist_conclusion);
  const pdfAdv = det.advanced_metrics || {};
  if (pdfAdv.v_recist_conclusion) addLabelValue("Volumetric RECIST:", pdfAdv.v_recist_conclusion);
  if (pdfAdv.total_tumor_burden_ml != null) {
    let burdenVal = pdfAdv.total_tumor_burden_ml.toFixed(1) + " mL";
    if (pdfAdv.tumor_burden_change_percent != null) burdenVal += ` (${pdfAdv.tumor_burden_change_percent >= 0 ? "+" : ""}${pdfAdv.tumor_burden_change_percent.toFixed(1)}%)`;
    addLabelValue("Total tumor burden:", burdenVal);
  }
  if (pdfAdv.days_since_previous_exam != null) addLabelValue("Interval:", pdfAdv.days_since_previous_exam + " days");
  if (pdfAdv.trend_direction) {
    let trendVal = pdfAdv.trend_direction;
    if (pdfAdv.consecutive_stable_exams) trendVal += ` (${pdfAdv.consecutive_stable_exams} consecutive stable)`;
    addLabelValue("Trend:", trendVal);
  }
  if (det.lesions && det.lesions.length) {
    y += 1;
    addLine("Lesion measurements:", { bold: true, size: 9, color: COL_MUTED, space: 1 });
    const pdfLmMap = {};
    (pdfAdv.lesion_metrics || []).forEach(lm => { pdfLmMap[lm.segment_number] = lm; });
    det.lesions.forEach((l, i) => {
      const dims = l.dimensions_mm ? l.dimensions_mm.map((d) => d.toFixed(1)).join(" x ") + " mm" : "-";
      const evo = l.evolution || "-";
      const lm = pdfLmMap[i + 1] || {};
      let extra = "";
      if (lm.growth_rate_percent_per_month != null) extra += ` | TGR: ${lm.growth_rate_percent_per_month >= 0 ? "+" : ""}${lm.growth_rate_percent_per_month.toFixed(1)}%/mo`;
      if (lm.doubling_time_days != null) extra += ` | TDT: ${lm.doubling_time_days.toFixed(0)}d`;
      if (lm.hu_heterogeneity_index != null) extra += ` | HU: ${lm.hu_mean?.toFixed(0)}+/-${lm.hu_std?.toFixed(0)} (het: ${lm.hu_heterogeneity_index.toFixed(2)})`;
      addLine(`${i + 1}. ${dims}  |  Evolution: ${evo}${extra}`, { indent: 4 });
    });
  }

  addSection("Findings - AI Agent");
  const agt = r.report.report_agent;
  if (agt.infiltration && (agt.infiltration.level || agt.infiltration.summary)) {
    const inf = agt.infiltration;
    const level = (inf.level || "none").replace(/_/g, " ");
    addLabelValue("Infiltration:", level + ". " + (inf.summary || ""));
  }
  if (agt.lesions && agt.lesions.length) {
    y += 1;
    agt.lesions.forEach((l, i) => {
      addLine(`Lesion ${i + 1}: ${l.location}`, { bold: true, size: 9, space: 0.5 });
      if (l.characterization) addLine(l.characterization, { indent: 4 });
      if (l.clinically_relevant_measurement) addLabelValue("Measurement:", l.clinically_relevant_measurement, { indent: 4 });
      if (l.comparison_to_previous) addLabelValue("Comparison:", l.comparison_to_previous, { indent: 4 });
      y += 1;
    });
  }
  if (agt.organ_assessments && agt.organ_assessments.length) {
    agt.organ_assessments.forEach((oa) => {
      const prefix = oa.is_normal ? "Normal" : "Abnormal";
      addLabelValue(`${prefix}: ${oa.organ} -`, oa.finding);
    });
  }
  if (agt.negative_findings && agt.negative_findings.length) {
    addLabelValue("Negative findings:", agt.negative_findings.join(", "));
  }
  if (agt.incidental_findings && agt.incidental_findings.length) {
    agt.incidental_findings.forEach((inc) => {
      const prefix = inc.is_new ? "[NEW] " : "";
      addLabelValue(`${prefix}${inc.location}:`, inc.description);
    });
  }

  addSection("Conclusions");
  const c = r.conclusions;
  if (c.recist_response) addLabelValue("RECIST response:", c.recist_response);
  if (c.recist_justification) addLine(c.recist_justification, { space: 1 });
  if (c.sum_of_diameters_mm != null) addLabelValue("Sum of diameters:", c.sum_of_diameters_mm.toFixed(1) + " mm");
  if (c.key_findings && c.key_findings.length) {
    y += 1;
    addLine("Key findings:", { bold: true, size: 9, color: COL_MUTED, space: 0.5 });
    c.key_findings.forEach((kf) => addLine("- " + kf, { indent: 4 }));
  }
  if (c.recommendation) {
    y += 1;
    addLabelValue("Recommendation:", c.recommendation);
  }

  addFooter();
  const filename = `rapport_${r.patient_id}_${r.accession_number}.pdf`;
  doc.save(filename);
  showToast("PDF telecharge");
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
    const d = det.lesions[i]; const a = agt.lesions[i];
    const loc = a ? a.location : `Lesion ${i + 1}`;
    const dims = d ? d.dimensions_mm.map(v => v.toFixed(0)).join("x") + "mm" : "?";
    let line = `- ${loc}: ${dims}`;
    if (d && d.short_axis_mm != null) line += ` (short axis ${d.short_axis_mm.toFixed(0)}mm)`;
    if (d && d.previous_dimensions_mm) { line += ` (anterior ${d.previous_dimensions_mm.map(v => v.toFixed(0)).join("x")}mm)`; }
    if (d && d.evolution) line += `. ${d.evolution}`;
    if (a && a.characterization) line += `. ${a.characterization}`;
    reportLines.push(line);
  }
  if (det.recist_conclusion) reportLines.push(`RECIST 1.1: ${det.recist_conclusion}`);
  const txtAdv = det.advanced_metrics || {};
  if (txtAdv.v_recist_conclusion) reportLines.push(`Volumetric RECIST: ${txtAdv.v_recist_conclusion}`);
  if (txtAdv.total_tumor_burden_ml != null) {
    let bl = `Total tumor burden: ${txtAdv.total_tumor_burden_ml.toFixed(1)} mL`;
    if (txtAdv.tumor_burden_change_percent != null) bl += ` (${txtAdv.tumor_burden_change_percent >= 0 ? "+" : ""}${txtAdv.tumor_burden_change_percent.toFixed(1)}%)`;
    reportLines.push(bl);
  }
  if (txtAdv.trend_direction) reportLines.push(`Trend: ${txtAdv.trend_direction}`);
  (txtAdv.lesion_metrics || []).forEach(lm => {
    const parts = [];
    if (lm.growth_rate_percent_per_month != null) parts.push(`TGR ${lm.growth_rate_percent_per_month >= 0 ? "+" : ""}${lm.growth_rate_percent_per_month.toFixed(1)}%/mo`);
    if (lm.doubling_time_days != null) parts.push(`doubling time ${lm.doubling_time_days.toFixed(0)}d`);
    if (lm.hu_heterogeneity_index != null) parts.push(`HU ${lm.hu_mean?.toFixed(0)}\u00B1${lm.hu_std?.toFixed(0)} (het: ${lm.hu_heterogeneity_index.toFixed(2)})`);
    if (parts.length) reportLines.push(`- Lesion ${lm.segment_number}: ${parts.join(", ")}`);
  });
  const inf = agt.infiltration;
  if (inf && inf.present_indicators && inf.present_indicators.length) { reportLines.push(`- Infiltration (${inf.level}): ${inf.summary || "See indicators"}`); }
  agt.organ_assessments.forEach(oa => reportLines.push(`- ${oa.organ}: ${oa.finding}`));
  agt.negative_findings.forEach(nf => reportLines.push(`- ${nf}`));
  agt.incidental_findings.forEach(inc => reportLines.push(`- ${inc.location}: ${inc.description}`));
  lines.push(reportLines.join("\n"));
  const cl = r.conclusions;
  const concl = ["CONCLUSIONS."];
  if (cl.recist_response) concl.push(`Findings compatible with ${cl.recist_response} according to RECIST criteria.`);
  if (cl.recist_justification) concl.push(cl.recist_justification);
  cl.key_findings.forEach(kf => concl.push(`- ${kf}`));
  if (cl.recommendation) concl.push(cl.recommendation);
  lines.push(concl.join(" "));
  return lines.join("\n\n");
}

// ── Toast ─────────────────────────────────────────────────
function showToast(msg) {
  let toast = document.querySelector(".toast");
  if (!toast) { toast = document.createElement("div"); toast.className = "toast"; document.body.appendChild(toast); }
  toast.textContent = msg;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2000);
}
