/**
 * app.js — RTF-to-PDF Compiler frontend
 *
 * Responsibilities:
 *  - Collect form data and POST to /api/run
 *  - Poll /api/status/<job_id> every 1.5 s during job execution
 *  - Stream log lines into the log pane with colour coding
 *  - Update the progress bar
 *  - Enable Download button on job completion
 *  - Handle /api/load-config to pre-populate all fields from a JSON file
 */

'use strict';

// ── DOM refs ─────────────────────────────────────────────────────────────────
const btnRun             = document.getElementById('btn-run');
const btnDownload        = document.getElementById('btn-download');
const btnGenerateMapping = document.getElementById('btn-generate-mapping');
const btnClearCsv        = document.getElementById('btn-clear-csv');
const btnPreviewLayout   = document.getElementById('btn-preview-layout');
const btnClearLog        = document.getElementById('btn-clear-log');

const logBody           = document.getElementById('log-body');
const progressContainer = document.getElementById('progress-container');
const progressBarFill   = document.getElementById('progress-bar-fill');
const progressLabel     = document.getElementById('progress-label');
const jobErrorBox       = document.getElementById('job-error-box');
const configLoadStatus  = document.getElementById('config-load-status');

// ── State ─────────────────────────────────────────────────────────────────────
let activeJobId   = null;
let pollTimer     = null;
let logLinesSeen  = 0;   // track how many log lines we have already rendered

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Classify a raw log line into a CSS class token for colour.
 */
function lineClass(line) {
  const u = line.toUpperCase();
  if (u.includes('[ERR') || u.includes('[FATAL') || u.includes('→ ERROR'))
    return 'log-err';
  if (u.includes('[OK]') || u.includes('[DONE') || u.includes('→ OK'))
    return 'log-ok';
  if (u.includes('[SKIP') || u.includes('[WARN'))
    return 'log-warn';
  return 'log-info';
}

/**
 * Append new log lines to the log pane, colour-coded.
 * Only appends lines beyond `logLinesSeen` to avoid re-rendering.
 */
function appendLogLines(lines) {
  const newLines = lines.slice(logLinesSeen);
  if (newLines.length === 0) return;

  // If the log pane currently shows only the placeholder text, clear it.
  if (logLinesSeen === 0) {
    logBody.textContent = '';
  }

  newLines.forEach(line => {
    const span = document.createElement('span');
    span.className = lineClass(line);
    span.textContent = line + '\n';
    logBody.appendChild(span);
  });

  logLinesSeen += newLines.length;

  // Auto-scroll to bottom
  logBody.scrollTop = logBody.scrollHeight;
}

/**
 * Append lines directly to the log pane without touching logLinesSeen.
 * Used for out-of-band operations (template generation) that are not
 * part of a running job's polling stream.
 */
function appendDirectLines(lines) {
  if (logBody.textContent === 'Ready. Configure inputs and click Run Job.') {
    logBody.textContent = '';
  }
  lines.forEach(line => {
    const span = document.createElement('span');
    span.className = lineClass(line);
    span.textContent = line + '\n';
    logBody.appendChild(span);
  });
  logBody.scrollTop = logBody.scrollHeight;
}

function setProgress(pct, label) {
  progressBarFill.style.width = pct + '%';
  progressLabel.textContent = label ?? `${pct}%`;
}

function showProgressContainer() {
  progressContainer.classList.remove('hidden');
}

function resetUI() {
  logLinesSeen = 0;
  logBody.textContent = 'Ready. Configure inputs and click Run Job.';
  setProgress(0, 'Idle');
  jobErrorBox.classList.add('hidden');
  jobErrorBox.textContent = '';
  btnRun.disabled = false;
  btnDownload.disabled = true;
  btnDownload.dataset.jobId = '';
  activeJobId = null;
  progressContainer.classList.add('hidden');
}

// ── Field mapping ─────────────────────────────────────────────────────────────
/** List of field id → JSON config key mappings for load-config restoration. */
const FIELD_MAP = [
  ['rtf_directory',         'rtf_directory'],
  ['output_directory',      'output_directory'],
  ['header_left',           null],   // nested under "header"
  ['header_center',         null],
  ['header_right',          null],
  ['footer_left',           null],   // nested under "footer"
  ['footer_center',         null],
  ['footer_right',          null],
  ['header_top_margin_pts',         'header_top_margin_pts'],
  ['footer_bottom_margin_pts',      'footer_bottom_margin_pts'],
  ['page_number_right_margin_pts',  'page_number_right_margin_pts'],
  ['page_number_bottom_margin_pts', 'page_number_bottom_margin_pts'],
  ['page_number_font_size',         'page_number_font_size'],
  ['max_workers',                   'max_workers'],
];

function populateFieldsFromConfig(cfg) {
  const hdr = cfg.header || {};
  const ftr = cfg.footer || {};

  const valueMap = {
    rtf_directory:          cfg.rtf_directory        ?? '',
    output_directory:       cfg.output_directory     ?? '',
    header_left:            hdr.left                 ?? '',
    header_center:          hdr.center               ?? '',
    header_right:           hdr.right                ?? '',
    footer_left:            ftr.left                 ?? '',
    footer_center:          ftr.center               ?? '',
    footer_right:           ftr.right                ?? '',
    header_top_margin_pts:         cfg.header_top_margin_pts         ?? 28,
    footer_bottom_margin_pts:      cfg.footer_bottom_margin_pts      ?? 35,
    page_number_right_margin_pts:  cfg.page_number_right_margin_pts  ?? 55,
    page_number_bottom_margin_pts: cfg.page_number_bottom_margin_pts ?? 18,
    page_number_font_size:         cfg.page_number_font_size         ?? 8,
    max_workers:                   cfg.max_workers                   ?? 8,
  };

  for (const [fieldId, _] of FIELD_MAP) {
    const el = document.getElementById(fieldId);
    if (el && valueMap[fieldId] !== undefined) {
      el.value = valueMap[fieldId];
    }
  }

  configLoadStatus.textContent =
    `Config loaded (saved ${cfg.timestamp ?? 'unknown time'})`;
  setTimeout(() => { configLoadStatus.textContent = ''; }, 5000);
}

// ── Collect form data ─────────────────────────────────────────────────────────
function buildFormData() {
  const fd = new FormData();

  const textFields = [
    'rtf_directory', 'output_directory',
    'header_left', 'header_center', 'header_right',
    'footer_left', 'footer_center', 'footer_right',
    'header_top_margin_pts', 'footer_bottom_margin_pts',
    'page_number_right_margin_pts', 'page_number_bottom_margin_pts', 'page_number_font_size',
    'max_workers',
  ];

  textFields.forEach(id => {
    const el = document.getElementById(id);
    if (el) fd.append(id, el.value);
  });

  const csvEl = document.getElementById('csv_file');
  if (csvEl && csvEl.files.length > 0) {
    fd.append('csv_file', csvEl.files[0]);
  }

  return fd;
}

// ── Polling ───────────────────────────────────────────────────────────────────
function startPolling(jobId) {
  if (pollTimer) clearInterval(pollTimer);

  pollTimer = setInterval(async () => {
    try {
      const resp = await fetch(`/api/status/${jobId}`);
      if (!resp.ok) {
        appendLogLines([`[ERR] Status fetch failed: HTTP ${resp.status}`]);
        return;
      }
      const data = await resp.json();

      appendLogLines(data.log || []);
      setProgress(data.progress ?? 0, `${data.progress ?? 0}%`);

      if (data.status === 'complete') {
        stopPolling();
        setProgress(100, '100% — Complete');
        btnRun.disabled = false;
        btnDownload.disabled = false;
        btnDownload.dataset.jobId = jobId;
        appendLogLines([`[DONE] Job ${jobId} completed successfully.`]);
      } else if (data.status === 'error') {
        stopPolling();
        btnRun.disabled = false;
        jobErrorBox.textContent = data.error ?? 'An unknown error occurred.';
        jobErrorBox.classList.remove('hidden');
        setProgress(0, 'Error');
      }
    } catch (fetchErr) {
      appendLogLines([`[ERR] Polling error: ${fetchErr.message}`]);
    }
  }, 1500);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

// ── Event: Run Job ────────────────────────────────────────────────────────────
btnRun.addEventListener('click', async () => {
  // Reset previous job state
  stopPolling();
  logLinesSeen = 0;
  logBody.textContent = '';
  setProgress(0, 'Starting…');
  jobErrorBox.classList.add('hidden');
  jobErrorBox.textContent = '';
  btnRun.disabled = true;
  btnDownload.disabled = true;
  showProgressContainer();

  const fd = buildFormData();

  try {
    const resp = await fetch('/api/run', {
      method: 'POST',
      body: fd,
    });

    const data = await resp.json();

    if (!resp.ok || data.error) {
      const msg = data.error ?? `Server error: HTTP ${resp.status}`;
      appendLogLines([`[ERR] ${msg}`]);
      jobErrorBox.textContent = msg;
      jobErrorBox.classList.remove('hidden');
      setProgress(0, 'Error');
      btnRun.disabled = false;
      return;
    }

    activeJobId = data.job_id;
    appendLogLines([`[INFO] Job started: ${activeJobId}`]);
    startPolling(activeJobId);

  } catch (err) {
    appendLogLines([`[ERR] Failed to start job: ${err.message}`]);
    jobErrorBox.textContent = err.message;
    jobErrorBox.classList.remove('hidden');
    setProgress(0, 'Error');
    btnRun.disabled = false;
  }
});

// ── Event: Download PDF ───────────────────────────────────────────────────────
btnDownload.addEventListener('click', () => {
  const jobId = btnDownload.dataset.jobId;
  if (!jobId) return;
  // Trigger download via anchor click
  const a = document.createElement('a');
  a.href = `/api/download/${jobId}`;
  a.download = 'compiled_output.pdf';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
});

// ── Event: Load Config ────────────────────────────────────────────────────────
async function loadConfigFile() {
  const fileEl = document.getElementById('config_file');
  if (!fileEl || fileEl.files.length === 0) return;

  const fd = new FormData();
  fd.append('config_file', fileEl.files[0]);

  try {
    const resp = await fetch('/api/load-config', { method: 'POST', body: fd });
    const data = await resp.json();

    if (!resp.ok || data.error) {
      configLoadStatus.style.color = 'var(--text-error)';
      configLoadStatus.textContent = `Error: ${data.error ?? 'Unknown error'}`;
      setTimeout(() => { configLoadStatus.textContent = ''; configLoadStatus.style.color = ''; }, 4000);
      return;
    }

    configLoadStatus.style.color = '';
    populateFieldsFromConfig(data);

  } catch (err) {
    configLoadStatus.style.color = 'var(--text-error)';
    configLoadStatus.textContent = `Failed: ${err.message}`;
    setTimeout(() => { configLoadStatus.textContent = ''; configLoadStatus.style.color = ''; }, 4000);
  }
}

document.getElementById('config_file').addEventListener('change', loadConfigFile);

// ── Event: Preview Layout ─────────────────────────────────────────────────────
btnPreviewLayout.addEventListener('click', async () => {
  btnPreviewLayout.disabled = true;
  try {
    const resp = await fetch('/api/preview-layout', { method: 'POST', body: buildFormData() });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({ error: `HTTP ${resp.status}` }));
      appendDirectLines([`[ERR]  Layout preview: ${data.error ?? resp.statusText}`]);
      return;
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank');
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (err) {
    appendDirectLines([`[ERR]  Layout preview: ${err.message}`]);
  } finally {
    btnPreviewLayout.disabled = false;
  }
});

// ── Event: Generate Mapping from Directory ────────────────────────────────────
btnGenerateMapping.addEventListener('click', async () => {
  const rtfDir = document.getElementById('rtf_directory').value.trim();
  if (!rtfDir) {
    appendDirectLines(['[WARN] Enter an RTF Directory path before generating.']);
    return;
  }

  appendDirectLines(['[INFO] Scanning RTF directory for mapping template…']);
  btnGenerateMapping.disabled = true;

  try {
    const fd = new FormData();
    fd.append('rtf_directory', rtfDir);

    const resp = await fetch('/api/generate-mapping-template', { method: 'POST', body: fd });
    const data = await resp.json();

    if (!resp.ok || data.error) {
      appendDirectLines([`[ERR]  ${data.error ?? 'Unknown error'}`]);
      return;
    }

    appendDirectLines(data.log || []);

    if (data.xlsx_base64) {
      const bytes = atob(data.xlsx_base64);
      const buf = new Uint8Array(bytes.length);
      for (let i = 0; i < bytes.length; i++) buf[i] = bytes.charCodeAt(i);
      const blob = new Blob([buf], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'csv_mapping_from_directory.xlsx';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }
  } catch (err) {
    appendDirectLines([`[ERR]  ${err.message}`]);
  } finally {
    btnGenerateMapping.disabled = false;
  }
});

// ── Event: Clear CSV selection ───────────────────────────────────────────────
btnClearCsv.addEventListener('click', () => {
  const csvEl = document.getElementById('csv_file');
  if (csvEl) csvEl.value = '';
});

// ── Event: Clear log ──────────────────────────────────────────────────────────
btnClearLog.addEventListener('click', () => {
  logBody.textContent = '';
  logLinesSeen = 0;
});
