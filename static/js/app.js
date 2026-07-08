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
const fileProgress        = document.getElementById('file-progress');
const fileProgressSummary = document.getElementById('file-progress-summary');
const fileProgressList    = document.getElementById('file-progress-list');
const stepProgress        = document.getElementById('step-progress');
const stepProgressRow     = document.getElementById('step-progress-row');

// ── State ─────────────────────────────────────────────────────────────────────
let activeJobId   = null;
let pollTimer     = null;
let clockTimer    = null;
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

/** Format seconds as a M:SS stopwatch string (e.g. 83.4 -> "1:23"). */
function fmtClock(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/**
 * Advance every live stopwatch between polls: each clock element carries the
 * server-reported elapsed seconds plus the client time it was rendered, so
 * the display ticks smoothly at 1 Hz while re-anchoring on every poll.
 */
function tickClocks() {
  document.querySelectorAll('.file-row-clock[data-run]').forEach(el => {
    const base = parseFloat(el.dataset.run);
    const at = parseInt(el.dataset.at, 10);
    el.textContent = fmtClock(base + (Date.now() - at) / 1000);
  });
}

/**
 * Render the per-file conversion panel: a summary line plus one progress
 * row per file currently converting (bounded by the worker count).
 */
function renderFileProgress(files) {
  if (!files.length) {
    fileProgress.classList.add('hidden');
    return;
  }
  fileProgress.classList.remove('hidden');

  const counts = { queued: 0, converting: 0, done: 0, failed: 0 };
  files.forEach(f => { counts[f.status] = (counts[f.status] ?? 0) + 1; });
  fileProgressSummary.textContent =
    `${counts.done} done · ${counts.failed} failed · ` +
    `${counts.converting} converting · ${counts.queued} queued (of ${files.length})`;

  fileProgressList.textContent = '';
  files.forEach(f => {
    // Converting files get a live bar; failed files stay visible in red so
    // missing content can never scroll silently out of sight.
    if (f.status !== 'converting' && f.status !== 'failed') return;
    const failed = f.status === 'failed';
    const row = document.createElement('div');
    row.className = 'file-row'
      + (failed ? ' file-row-failed'
                : (f.pct === 0 ? ' file-row-indeterminate' : ''));

    const name = document.createElement('div');
    name.className = 'file-row-name';
    name.textContent = f.name;
    name.title = f.name;

    const track = document.createElement('div');
    track.className = 'file-bar-track';
    const fill = document.createElement('div');
    fill.className = 'file-bar-fill';
    fill.style.width = (failed ? 100 : f.pct) + '%';
    track.appendChild(fill);

    const pct = document.createElement('div');
    pct.className = 'file-row-pct';
    pct.textContent = failed ? 'FAILED' : f.pct + '%';

    // Stopwatch: live M:SS for converting files (ticked by tickClocks
    // between polls), final elapsed time for failed ones.
    const clock = document.createElement('div');
    clock.className = 'file-row-clock';
    if (failed) {
      clock.textContent = f.elapsed != null ? fmtClock(f.elapsed) : '';
    } else {
      clock.dataset.run = f.running ?? 0;
      clock.dataset.at = Date.now();
      clock.textContent = fmtClock(f.running ?? 0);
    }

    row.append(name, track, pct, clock);
    fileProgressList.appendChild(row);
  });
}

/**
 * Render the post-processing step row (page numbering, final save…):
 * label | bar | pct | live M:SS stopwatch. `step.pct === null` renders as
 * indeterminate (pulsing bar) for steps that cannot report granular
 * progress. Hidden whenever no step is active.
 */
function renderStepProgress(step) {
  if (!step) {
    stepProgress.classList.add('hidden');
    stepProgressRow.textContent = '';
    return;
  }
  stepProgress.classList.remove('hidden');
  stepProgressRow.textContent = '';

  const indeterminate = step.pct == null;
  const row = document.createElement('div');
  row.className = 'file-row' + (indeterminate ? ' file-row-indeterminate' : '');

  const name = document.createElement('div');
  name.className = 'file-row-name';
  name.textContent = step.label;
  name.title = step.label;

  const track = document.createElement('div');
  track.className = 'file-bar-track';
  const fill = document.createElement('div');
  fill.className = 'file-bar-fill';
  fill.style.width = (indeterminate ? 0 : step.pct) + '%';
  track.appendChild(fill);

  const pct = document.createElement('div');
  pct.className = 'file-row-pct';
  pct.textContent = indeterminate ? '…' : step.pct + '%';

  const clock = document.createElement('div');
  clock.className = 'file-row-clock';
  clock.dataset.run = step.running ?? 0;
  clock.dataset.at = Date.now();
  clock.textContent = fmtClock(step.running ?? 0);

  row.append(name, track, pct, clock);
  stepProgressRow.appendChild(row);
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
  fileProgress.classList.add('hidden');
  fileProgressSummary.textContent = '';
  fileProgressList.textContent = '';
  stepProgress.classList.add('hidden');
  stepProgressRow.textContent = '';
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
  ['toc_landscape',                 'toc_landscape'],
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
    toc_landscape:                 cfg.toc_landscape                 ?? false,
  };

  for (const [fieldId, _] of FIELD_MAP) {
    const el = document.getElementById(fieldId);
    if (el && valueMap[fieldId] !== undefined) {
      if (el.type === 'checkbox') {
        el.checked = !!valueMap[fieldId];
      } else {
        el.value = valueMap[fieldId];
      }
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

  const tocLandscapeEl = document.getElementById('toc_landscape');
  if (tocLandscapeEl) fd.append('toc_landscape', tocLandscapeEl.checked ? '1' : '0');

  const csvEl = document.getElementById('csv_file');
  if (csvEl && csvEl.files.length > 0) {
    fd.append('csv_file', csvEl.files[0]);
  }

  return fd;
}

// ── Polling ───────────────────────────────────────────────────────────────────
function startPolling(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  if (clockTimer) clearInterval(clockTimer);
  clockTimer = setInterval(tickClocks, 1000);

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
      renderFileProgress(data.files || []);
      renderStepProgress(data.step || null);

      if (data.status === 'complete') {
        stopPolling();
        btnRun.disabled = false;
        btnDownload.disabled = false;
        btnDownload.dataset.jobId = jobId;
        const missing = (data.failed_files || []).concat(data.skipped_files || []);
        if (missing.length) {
          // The output PDF exists but content is missing — say so loudly.
          setProgress(100, `100% — ${missing.length} FILE(S) MISSING`);
          jobErrorBox.textContent =
            `Warning: the output PDF is MISSING content from ` +
            `${missing.length} file(s): ${missing.join(', ')}`;
          jobErrorBox.classList.remove('hidden');
          appendLogLines([
            `[DONE] Job ${jobId} completed WITH MISSING CONTENT (${missing.length} file(s)).`,
          ]);
        } else {
          setProgress(100, '100% — Complete');
          appendLogLines([`[DONE] Job ${jobId} completed successfully.`]);
        }
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
  if (clockTimer) {
    clearInterval(clockTimer);
    clockTimer = null;
  }
}

// ── Event: Run Job ────────────────────────────────────────────────────────────
btnRun.addEventListener('click', async () => {
  // Reset previous job state
  stopPolling();
  logLinesSeen = 0;
  logBody.textContent = '';
  setProgress(0, 'Starting…');
  renderFileProgress([]);
  renderStepProgress(null);
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
