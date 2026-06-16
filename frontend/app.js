/**
 * ClearDeck — Frontend application logic
 * Single-page app with 3 tabs: Projects, Anonymize, Restore
 */

// ============================================================
// State
// ============================================================

const state = {
  currentTab: 'anonymize',
  projects: [],          // saved clients (kept key name 'projects' for the list)
  editingClient: null,   // { id, name, terms } being created/edited
  // Anonymize
  anonFiles: [],         // all docs added in the selector (1 = single, 2+ = multi)
  batchJobId: null,      // current ZIP (fast-mode) job
  manualTerms: [],       // manual identification terms (also fed by client picks)
  // Each processed document is fully independent: own forgotten terms, version,
  // result ids and replacements. Single-file = a docs array of length 1.
  docs: [],            // [{ file, fileName, fileType, anonFileId, mappingFileId,
                       //    anonFilename, mappingFilename, replacements,
                       //    forgottenTerms, docVersion, error? }]
  docIndex: 0,         // which doc the result page is currently showing
  // Restore
  restoreFile: null,
  mappingFile: null,
  restoreResult: null,
  restoreHistory: [],  // { fileName, fileType, fileId }
};

// ============================================================
// Helpers
// ============================================================

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function show(el) { if (typeof el === 'string') el = $(el); if (el) el.style.display = ''; }
function hide(el) { if (typeof el === 'string') el = $(el); if (el) el.style.display = 'none'; }

/* ── Redaction loader animation ── */
let _redactTimers = [];
let _redactRunning = false;

function _resetRedactLoader() {
  // Clear all pending timers
  _redactTimers.forEach(t => clearTimeout(t));
  _redactTimers = [];
  // Reset all pages and bars to initial state
  const loader = document.querySelector('#loading .redact-loader');
  if (!loader) return;
  loader.querySelectorAll('.redact-page').forEach(p => {
    p.classList.remove('redact-page--lift', 'redact-page--drop', 'redact-page--settle');
  });
  loader.querySelectorAll('.redact-bar').forEach(b => b.classList.remove('is-visible'));
  // Restore initial front/back (first child = back, second = front)
  const pages = loader.querySelectorAll('.redact-page');
  if (pages.length >= 2) {
    pages[0].classList.remove('redact-page--front');
    pages[0].classList.add('redact-page--back');
    pages[1].classList.remove('redact-page--back');
    pages[1].classList.add('redact-page--front');
  }
}

function _startRedactAnimation() {
  if (_redactRunning) return;
  _redactRunning = true;
  const loader = document.querySelector('#loading .redact-loader');
  if (!loader) return;
  const pages = Array.from(loader.querySelectorAll('.redact-page'));
  if (pages.length < 2) return;

  function getFront() { return pages.find(p => p.classList.contains('redact-page--front')); }
  function getBack()  { return pages.find(p => p.classList.contains('redact-page--back')); }

  function t(fn, ms) { const id = setTimeout(fn, ms); _redactTimers.push(id); return id; }

  function cycle() {
    if (!_redactRunning) return;
    const front = getFront();
    const back = getBack();
    const b = front.querySelectorAll('.redact-bar');

    b[0]?.classList.add('is-visible');
    t(() => b[1]?.classList.add('is-visible'), 500);
    t(() => b[2]?.classList.add('is-visible'), 1000);

    t(() => {
      if (!_redactRunning) return;
      front.classList.add('redact-page--lift');

      t(() => {
        front.classList.remove('redact-page--lift');
        front.classList.add('redact-page--drop');
        b.forEach(bar => bar.classList.remove('is-visible'));

        t(() => {
          front.classList.remove('redact-page--front', 'redact-page--drop');
          front.classList.add('redact-page--back', 'redact-page--settle');
          back.classList.remove('redact-page--back');
          back.classList.add('redact-page--front');

          t(() => {
            front.classList.remove('redact-page--settle');
            t(cycle, 250);
          }, 450);
        }, 420);
      }, 380);
    }, 1800);
  }

  cycle();
}

function _stopRedactAnimation() {
  _redactRunning = false;
  _resetRedactLoader();
}

function showLoading(text = 'Traitement en cours...') {
  $('#loading-text').textContent = text;
  show('#loading');
  _startRedactAnimation();
}
function hideLoading() {
  hide('#loading');
  _stopRedactAnimation();
}

async function api(url, opts = {}) {
  const resp = await fetch(url, opts);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || 'Erreur serveur');
  }
  return resp.json();
}

// ============================================================
// Tab navigation
// ============================================================

function switchTab(tab) {
  state.currentTab = tab;
  $$('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  $$('.tab-content').forEach(t => t.classList.toggle('active', t.id === `tab-${tab}`));
  if (tab === 'anonymize') loadProjectsDropdown();
  if (tab === 'projects') loadProjects();
}

$$('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// ============================================================
// Tab 1: Clients (name + flat list of sensitive terms)
// ============================================================

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

async function loadProjects() {
  try {
    state.projects = await api('/api/projects');
    renderProjects();
  } catch (e) {
    console.error(e);
  }
}

function renderProjects() {
  const container = $('#projects-list');
  if (!state.projects.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">&mdash;</div>
        <p>Aucun client. Créez-en un pour réutiliser ses termes lors de l'anonymisation.</p>
      </div>`;
    return;
  }
  container.innerHTML = state.projects.map(c => `
    <div class="project-card" data-id="${esc(c.id)}">
      <div class="card-actions">
        <button title="Modifier" data-edit="${esc(c.id)}">Edit</button>
        <button title="Supprimer" data-del="${esc(c.id)}">&times;</button>
      </div>
      <h4>${esc(c.name)}</h4>
      <p class="meta">${c.term_count} terme${c.term_count > 1 ? 's' : ''}</p>
    </div>`).join('');
  container.querySelectorAll('button[data-edit]').forEach(b =>
    b.addEventListener('click', () => editClient(b.dataset.edit)));
  container.querySelectorAll('button[data-del]').forEach(b =>
    b.addEventListener('click', () => deleteClient(b.dataset.del)));
}

// ── Client form: name + a tag list of terms (like the "oublis" box) ──

function openClientForm(client) {
  state.editingClient = client || { id: null, name: '', terms: [] };
  $('#client-form-title').textContent = client ? 'Modifier le client' : 'Nouveau client';
  $('#cl-name').value = state.editingClient.name;
  $('#cl-term-input').value = '';
  renderClientTerms();
  show('#project-form');
  $('#cl-name').focus();
}

$('#btn-new-project').addEventListener('click', () => openClientForm(null));
$('#btn-cancel-project').addEventListener('click', () => {
  hide('#project-form');
  state.editingClient = null;
});

function renderClientTerms() {
  const c = state.editingClient;
  if (!c) return;
  const container = $('#cl-terms');
  container.innerHTML = c.terms.map((t, i) => `
    <span class="entity-tag">${esc(t)}
      <button class="remove-tag" data-idx="${i}" title="Retirer">&times;</button>
    </span>`).join('');
  container.querySelectorAll('.remove-tag').forEach(btn =>
    btn.addEventListener('click', () => {
      c.terms.splice(parseInt(btn.dataset.idx), 1);
      renderClientTerms();
    }));
}

// Split a raw input into individual terms (comma or newline separated).
function splitTerms(raw) {
  return (raw || '').split(/[,\n;]+/).map(s => s.trim()).filter(Boolean);
}

// Add `term` to `list` if not already present (case-insensitive). Returns true if added.
function pushUnique(list, term) {
  if (list.some(t => t.toLowerCase() === term.toLowerCase())) return false;
  list.push(term);
  return true;
}

function addClientTerm() {
  const c = state.editingClient;
  if (!c) return;
  const input = $('#cl-term-input');
  splitTerms(input.value).forEach(val => pushUnique(c.terms, val));
  input.value = '';
  renderClientTerms();
  input.focus();
}

$('#cl-term-add').addEventListener('click', addClientTerm);
$('#cl-term-input').addEventListener('keypress', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); addClientTerm(); }
});

$('#btn-save-project').addEventListener('click', async () => {
  const c = state.editingClient;
  if (!c) return;
  const name = $('#cl-name').value.trim();
  if (!name) { alert('Le nom du client est requis.'); return; }
  showLoading('Enregistrement…');
  try {
    await api('/api/projects/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: c.id, name, terms: c.terms }),
    });
    hide('#project-form');
    state.editingClient = null;
    await loadProjects();
  } catch (e) {
    alert(`Erreur: ${e.message}`);
  } finally {
    hideLoading();
  }
});

async function editClient(id) {
  showLoading('Chargement…');
  try {
    const c = await api(`/api/projects/${id}`);
    openClientForm({ id: c.id, name: c.name, terms: (c.terms || []).slice() });
  } catch (e) {
    alert(`Erreur: ${e.message}`);
  } finally {
    hideLoading();
  }
}

async function deleteClient(id) {
  if (!confirm('Supprimer ce client ?')) return;
  try {
    await api(`/api/projects/${id}`, { method: 'DELETE' });
    await loadProjects();
  } catch (e) {
    alert(`Erreur: ${e.message}`);
  }
}

// ============================================================
// Tab 2: Anonymize
// ============================================================

// Small SVG doc icons for history list lines
const ICON_DOCX_SMALL = `<svg class="filetype-icon-small" viewBox="0 0 48 56" fill="none"><rect x="4" y="0" width="40" height="56" rx="2" fill="#fff" stroke="#ccc" stroke-width="1.5"/><path d="M4 0h28l12 12H32a4 4 0 0 1-4-4V0z" fill="#e8e8e8" stroke="#ccc" stroke-width="1"/><rect x="10" y="30" width="28" height="2.5" rx="1" fill="#2B579A"/><rect x="10" y="36" width="22" height="2.5" rx="1" fill="#2B579A" opacity="0.6"/><rect x="10" y="42" width="26" height="2.5" rx="1" fill="#2B579A" opacity="0.35"/><text x="24" y="24" text-anchor="middle" font-family="Arial" font-weight="bold" font-size="8" fill="#2B579A">W</text></svg>`;
const ICON_PPTX_SMALL = `<svg class="filetype-icon-small" viewBox="0 0 56 42" fill="none"><rect x="0" y="0" width="56" height="42" rx="2" fill="#fff" stroke="#ccc" stroke-width="1.5"/><rect x="6" y="10" width="44" height="24" rx="1" fill="#D24726" opacity="0.1" stroke="#D24726" stroke-width="0.8"/><text x="28" y="28" text-anchor="middle" font-family="Arial" font-weight="bold" font-size="8" fill="#D24726">P</text></svg>`;

// Real Office icons for drop zone corner pop
const OFFICE_ICON_DOCX = '/static/icon-docx.png';
const OFFICE_ICON_PPTX = '/static/icon-pptx.png';

// Background colors per file type
const BG_DOCX = '#EDF1F8'; // very light Word blue
const BG_PPTX = '#FDF0ED'; // very light PowerPoint red

function getFileExt(fileName) {
  if (!fileName) return '';
  return fileName.toLowerCase().split('.').pop();
}

function getSmallIcon(fileName) {
  const ext = getFileExt(fileName);
  if (ext === 'pptx') return ICON_PPTX_SMALL;
  if (ext === 'docx') return ICON_DOCX_SMALL;
  return '';
}

function showFiletypePop(fileName, dropZoneId) {
  const drop = $(`#${dropZoneId}`);
  const ext = getFileExt(fileName);
  if (!ext) return;

  // Remove any existing pop
  drop.querySelector('.drop-corner-icon')?.remove();

  // Add Office icon in top-right corner of the drop zone
  const img = document.createElement('img');
  img.className = 'drop-corner-icon';
  img.src = ext === 'pptx' ? OFFICE_ICON_PPTX : OFFICE_ICON_DOCX;
  img.alt = ext.toUpperCase();
  drop.appendChild(img);

  // Set background color
  drop.style.background = ext === 'pptx' ? BG_PPTX : BG_DOCX;
}

function clearFiletypePop(dropZoneId) {
  const drop = $(`#${dropZoneId}`);
  drop.querySelector('.drop-corner-icon')?.remove();
  drop.style.background = '';
}

// Client picker on the anonymize page: each client is a one-click button that
// injects its saved terms into the manual identification list.
async function loadProjectsDropdown() {
  try {
    const clients = await api('/api/projects');
    state.projects = clients;
    const btnContainer = $('#project-buttons');
    if (clients.length === 0) {
      hide('#project-selector');
      return;
    }
    show('#project-selector');
    btnContainer.innerHTML = clients.map(c =>
      `<button class="project-btn" data-client-id="${esc(c.id)}">${esc(c.name)}</button>`
    ).join('');

    btnContainer.querySelectorAll('.project-btn').forEach(btn => {
      btn.addEventListener('click', () => addClientToManual(btn.dataset.clientId, btn));
    });
  } catch (e) {
    console.error(e);
  }
}

// Fetch a client and merge its terms into the manual identification tags.
async function addClientToManual(clientId, btn) {
  try {
    const client = await api(`/api/projects/${clientId}`);
    let added = 0;
    for (const t of (client.terms || [])) {
      if (!state.manualTerms.some(x => x.toLowerCase() === t.toLowerCase())) {
        state.manualTerms.push(t);
        added++;
      }
    }
    renderManualTerms();
    // Open the manual section so the user sees the injected terms.
    const details = $('#manual-entities-section');
    if (details) details.open = true;
    if (btn) {
      btn.classList.add('added');
      btn.textContent = `${client.name} ✓`;
      setTimeout(() => { btn.classList.remove('added'); btn.textContent = client.name; }, 1200);
    }
  } catch (e) {
    alert(`Erreur: ${e.message}`);
  }
}

// Client picker toggle
$('#project-selector-toggle').addEventListener('click', () => {
  const selector = $('#project-selector');
  const btns = $('#project-buttons');
  selector.classList.toggle('project-selector--collapsed');
  if (selector.classList.contains('project-selector--collapsed')) {
    hide(btns);
  } else {
    show(btns);
  }
});

// Hero drop zone setup
function setupHeroDrop(inputId, dropId, nameId, stateKey, opts = {}) {
  const input = $(`#${inputId}`);
  const drop = $(`#${dropId}`);
  const nameEl = $(`#${nameId}`);

  drop.addEventListener('click', (e) => {
    if (e.target.closest('.btn-link')) return;
    input.click();
  });
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('dragover'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('dragover'));
  drop.addEventListener('drop', e => {
    e.preventDefault();
    drop.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      input.dispatchEvent(new Event('change'));
    }
  });

  input.addEventListener('change', () => {
    // onFiles: caller manages an accumulating list itself (anonymize tab).
    if (opts.onFiles) {
      if (input.files.length) opts.onFiles(Array.from(input.files));
      input.value = '';  // let the same file be re-added after removal
      return;
    }
    if (input.files.length >= 2 && opts.onMultiple) {
      opts.onMultiple(Array.from(input.files));
      // Don't set selectedFile / nameEl in multi-file mode
    } else if (input.files.length) {
      state[stateKey] = input.files[0];
      nameEl.textContent = input.files[0].name;
      if (opts.onFile) opts.onFile(input.files[0]);
    } else {
      state[stateKey] = null;
      nameEl.textContent = '';
      if (opts.onClear) opts.onClear();
    }
    updatePreviewButton();
    updateRestoreButton();
  });
}

// Setup anon hero drop — accumulates dropped/picked files into a managed list.
const MAX_ANON_FILES = 50;
setupHeroDrop('anon-file', 'anon-drop-zone', null, 'selectedFile', {
  onFiles: (files) => addAnonFiles(files),
});

// Add files to the selector list (dedup by name+size, keep supported types).
function addAnonFiles(files) {
  const supported = files.filter(f => /\.(docx|pptx)$/i.test(f.name));
  if (supported.length === 0) {
    alert('Formats acceptés : .docx ou .pptx.');
    return;
  }
  for (const f of supported) {
    if (!state.anonFiles.some(x => x.name === f.name && x.size === f.size)) {
      state.anonFiles.push(f);
    }
  }
  if (state.anonFiles.length > MAX_ANON_FILES) {
    state.anonFiles = state.anonFiles.slice(0, MAX_ANON_FILES);
    alert(`Maximum ${MAX_ANON_FILES} documents.`);
  }
  hide('#anon-result-panel');
  hide('#batch-panel');
  renderAnonFileList();
}

// Render the list of added documents below the drop zone, with remove buttons.
function renderAnonFileList() {
  const list = $('#anon-file-list');
  const n = state.anonFiles.length;

  if (!n) {
    list.innerHTML = '';
    hide('#anon-file-list');
    clearFiletypePop('anon-drop-zone');
    updateAnonActionButton();
    return;
  }

  show('#anon-file-list');
  // Tint the drop zone after the first file's type (visual cue).
  showFiletypePop(state.anonFiles[0].name, 'anon-drop-zone');

  list.innerHTML = state.anonFiles.map((f, i) => `
    <div class="anon-file-row">
      <span class="anon-file-row-icon">${getSmallIcon(f.name)}</span>
      <span class="anon-file-row-name" title="${esc(f.name)}">${esc(f.name)}</span>
      <span class="anon-file-row-size">${_formatBytes(f.size)}</span>
      <button class="anon-file-remove" data-idx="${i}" title="Retirer ce document" aria-label="Retirer">&times;</button>
    </div>`).join('');

  list.querySelectorAll('.anon-file-remove').forEach(btn => {
    btn.addEventListener('click', () => {
      state.anonFiles.splice(parseInt(btn.dataset.idx), 1);
      renderAnonFileList();
    });
  });

  updateAnonActionButton();
}

// Update the action area: one button for a single doc, a fast-vs-edit choice
// (with an explanation) for several.
function updateAnonActionButton() {
  const n = state.anonFiles.length;
  const editBtn = $('#btn-anonymize');
  const zipBtn = $('#btn-anonymize-zip');
  const hint = $('#anon-actions-hint');

  if (!n) {
    hide('#anon-preview-actions');
    editBtn.disabled = true;
    return;
  }
  show('#anon-preview-actions');
  editBtn.disabled = false;

  if (n === 1) {
    editBtn.textContent = 'Anonymiser';
    hide(zipBtn);
    hide(hint);
    return;
  }

  // 2+ documents → offer both modes.
  editBtn.textContent = `Anonymiser et éditer (${n})`;
  zipBtn.textContent = `Mode rapide — ZIP (${n})`;
  show(zipBtn);
  show(hint);
  hint.innerHTML =
    '<strong>Anonymiser et éditer</strong> : une page par document (ajout d’oublis, ' +
    'régénération, détail des remplacements) — plus complet, mais plus lent.<br>' +
    '<strong>Mode rapide — ZIP</strong> : tous les documents anonymisés d’un coup dans ' +
    'une archive, sans édition individuelle — plus rapide.';
}

// Setup restore hero drop
setupHeroDrop('restore-file', 'restore-drop-zone', 'restore-file-name', 'restoreFile', {
  onFile: (file) => {
    showFiletypePop(file.name, 'restore-drop-zone');
    show('#restore-mapping-section');
  },
  onClear: () => {
    clearFiletypePop('restore-drop-zone');
    hide('#restore-mapping-section');
  }
});

// Setup mapping file drop (standard, not hero)
function setupFileInput(inputId, dropId, nameId, stateKey) {
  const input = $(`#${inputId}`);
  const drop = $(`#${dropId}`);
  const nameEl = $(`#${nameId}`);

  drop.addEventListener('click', (e) => {
    if (e.target.closest('.btn-link')) return;
    input.click();
  });
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('dragover'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('dragover'));
  drop.addEventListener('drop', e => {
    e.preventDefault();
    drop.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      input.dispatchEvent(new Event('change'));
    }
  });

  input.addEventListener('change', () => {
    if (input.files.length) {
      state[stateKey] = input.files[0];
      nameEl.textContent = input.files[0].name;
    } else {
      state[stateKey] = null;
      nameEl.textContent = '';
    }
    updatePreviewButton();
    updateRestoreButton();
  });
}

setupFileInput('restore-mapping', 'mapping-drop-zone', 'restore-mapping-name', 'mappingFile');

$('#anon-browse').addEventListener('click', (e) => { e.stopPropagation(); $('#anon-file').click(); });
$('#restore-browse').addEventListener('click', (e) => { e.stopPropagation(); $('#restore-file').click(); });
$('#mapping-browse').addEventListener('click', (e) => { e.stopPropagation(); $('#restore-mapping').click(); });

function updatePreviewButton() {
  // The anonymize button now reflects the queued document list.
  updateAnonActionButton();
}

// ── Manual identification: a single tag list (like the "oublis" box) ──

function renderManualTerms() {
  const container = $('#manual-terms');
  container.innerHTML = state.manualTerms.map((t, i) => `
    <span class="entity-tag">${esc(t)}
      <button class="remove-tag" data-idx="${i}" title="Retirer">&times;</button>
    </span>`).join('');
  container.querySelectorAll('.remove-tag').forEach(btn =>
    btn.addEventListener('click', () => {
      state.manualTerms.splice(parseInt(btn.dataset.idx), 1);
      renderManualTerms();
    }));
  const n = state.manualTerms.length;
  $('#manual-id-title').textContent = n
    ? `Identification manuelle (${n})`
    : 'Identification manuelle';
}

function addManualTerm() {
  const input = $('#manual-term-input');
  splitTerms(input.value).forEach(val => pushUnique(state.manualTerms, val));
  input.value = '';
  renderManualTerms();
  input.focus();
}

$('#manual-term-add').addEventListener('click', addManualTerm);
$('#manual-term-input').addEventListener('keypress', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); addManualTerm(); }
});

// Switch to the result view (document ready + add-missed-terms box)
function showResultPanel() {
  hide('#anon-drop-zone');
  hide('#anon-file-list');
  hide('#anon-preview-actions');
  hide('#project-selector');
  // The per-document "oublis" box covers manual additions here, so the
  // bottom-of-page manual identification section is hidden on result pages.
  hide('#manual-entities-section');
  show('#anon-result-panel');
}

// Return to the upload view (e.g. "Anonymiser d'autres documents")
function showUploadView() {
  hide('#anon-result-panel');
  hide('#batch-panel');
  show('#anon-drop-zone');
  show('#project-selector');
  show('#manual-entities-section');
  clearFiletypePop('anon-drop-zone');
  state.anonFiles = [];
  state.docs = [];
  state.docIndex = 0;
  state.batchJobId = null;
  $('#anon-file').value = '';
  renderAnonFileList();
}

// Pull a flat [{original, placeholder}] list out of the mapping JSON.
function extractReplacements(mapping) {
  if (!mapping || !Array.isArray(mapping.entities)) return [];
  return mapping.entities.map(e => ({
    original: e.original,
    placeholder: e.placeholder,
    source: e.source,  // "project" (manual/client) | "ai" | "alt_text"
  }));
}

function buildManualEntities() {
  // All manual identification terms map to the "autres" category → [SENSIBLE_x].
  return { autres: state.manualTerms.slice() };
}

// Anonymize one file and return an independent "doc" result object.
async function anonymizeFile(file, extraTerms) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('manual_entities', JSON.stringify(buildManualEntities()));
  formData.append('extra_terms', JSON.stringify(extraTerms || []));

  const res = await api('/api/anonymize', { method: 'POST', body: formData });
  return {
    file,
    fileName: file.name,
    fileType: file.name.toLowerCase().split('.').pop(),
    anonFileId: res.anon_file_id,
    mappingFileId: res.mapping_file_id,
    anonFilename: res.anon_filename,
    mappingFilename: res.mapping_filename,
    replacements: extractReplacements(res.mapping),
    forgottenTerms: (extraTerms || []).slice(),
    docVersion: 1,
  };
}

function currentDoc() { return state.docs[state.docIndex]; }

// "Edit" mode: process every queued document into its own result page.
$('#btn-anonymize').addEventListener('click', () => processAnonFiles());
// "Fast" mode: anonymize all into a single ZIP (no per-doc editing).
$('#btn-anonymize-zip').addEventListener('click', () => startBatch());

async function processAnonFiles() {
  const files = state.anonFiles.slice();
  if (!files.length) return;
  const multi = files.length > 1;

  if (multi) _showBatchLoadingOverlay(files.length);
  else showLoading('Anonymisation en cours...');

  state.docs = [];
  try {
    for (let i = 0; i < files.length; i++) {
      if (multi) _updateBatchLoadingOverlay(i, files.length, files[i].name);
      try {
        const doc = await anonymizeFile(files[i], []);
        state.docs.push(doc);
      } catch (e) {
        // Don't abort the whole batch on one bad file — record and continue.
        state.docs.push({
          fileName: files[i].name,
          fileType: files[i].name.toLowerCase().split('.').pop(),
          error: e.message,
        });
      }
    }
    if (multi) _updateBatchLoadingOverlay(files.length, files.length, '');

    state.docIndex = 0;
    renderCurrentDoc();
    showResultPanel();
  } finally {
    multi ? _hideBatchLoadingOverlay() : hideLoading();
  }
}

// ── Document navigation (dropdown + arrows), shown only for 2+ documents ──

function renderDocNav() {
  const nav = $('#doc-nav');
  if (state.docs.length <= 1) { hide(nav); return; }
  show(nav);
  const sel = $('#doc-select');
  sel.innerHTML = state.docs.map((d, i) =>
    `<option value="${i}">${esc(`${i + 1}/${state.docs.length} — ${d.fileName}`)}</option>`
  ).join('');
  sel.value = String(state.docIndex);
  $('#doc-prev').disabled = state.docIndex === 0;
  $('#doc-next').disabled = state.docIndex === state.docs.length - 1;
}

function goToDoc(idx) {
  if (idx < 0 || idx >= state.docs.length) return;
  state.docIndex = idx;
  renderCurrentDoc();
}

$('#doc-select').addEventListener('change', (e) => goToDoc(parseInt(e.target.value)));
$('#doc-prev').addEventListener('click', () => goToDoc(state.docIndex - 1));
$('#doc-next').addEventListener('click', () => goToDoc(state.docIndex + 1));

// ── Render the result page for the current document ──

function renderCurrentDoc() {
  const doc = currentDoc();
  if (!doc) return;
  renderDocNav();

  // Per-file failure state.
  if (doc.error) {
    $('#version-badge').style.display = 'none';
    $('#result-summary').textContent = `Échec de l'anonymisation : ${doc.error}`;
    $('#result-mapping').innerHTML = '';
    $('#forgotten-tags').innerHTML = '';
    $('#btn-download-anon').disabled = true;
    $('#btn-download-mapping').disabled = true;
    hide('#btn-regenerate');
    return;
  }

  $('#btn-download-anon').disabled = false;
  $('#btn-download-mapping').disabled = false;
  $('#version-badge').style.display = '';
  $('#version-badge').textContent = `V${doc.docVersion}`;

  const n = doc.replacements.length;
  $('#result-summary').textContent = n > 0
    ? `${n} terme${n > 1 ? 's' : ''} masqué${n > 1 ? 's' : ''}. Téléchargez le document, ou complétez les oublis ci-dessous.`
    : "Aucun terme détecté. Ajoutez les termes à masquer ci-dessous, puis régénérez.";

  // Categorise by the mapping source: alt texts get their own collapsible
  // section; manual/client/forgotten terms (source "project") are "added by
  // hand"; everything else is AI-detected.
  const isAlt = (r) => (r.placeholder || '').startsWith('[ALT_') || r.source === 'alt_text';
  const alt = doc.replacements.filter(isAlt);
  const rest = doc.replacements.filter(r => !isAlt(r));
  const manual = rest.filter(r => r.source === 'project');
  const ai = rest.filter(r => r.source !== 'project');

  const renderList = (items) => `<div class="result-mapping-list">${items.map(r =>
    `<span class="anon-mapping-entry"><span class="anon-mapping-original">${esc(r.original)}</span> → ${esc(r.placeholder)}</span>`
  ).join('')}</div>`;

  const renderGroup = (title, items, modifier) => items.length
    ? `<div class="mapping-group${modifier ? ' ' + modifier : ''}">
         <h5 class="mapping-group-title">${title} · ${items.length}</h5>
         ${renderList(items)}
       </div>`
    : '';

  const renderAltGroup = (items) => items.length
    ? `<details class="mapping-details">
         <summary class="mapping-details-summary">Textes alternatifs d’images · ${items.length}</summary>
         ${renderList(items)}
       </details>`
    : '';

  $('#result-mapping').innerHTML =
    renderGroup('Ajoutés à la main', manual, 'mapping-group--manual') +
    renderGroup('Détectés par l’IA', ai) +
    renderAltGroup(alt);

  renderForgottenTags();
}

// ── Forgotten terms (missed by the AI) — operate on the current document ──

function renderForgottenTags() {
  const doc = currentDoc();
  if (!doc || doc.error) return;
  const container = $('#forgotten-tags');
  container.innerHTML = doc.forgottenTerms.map((t, i) => `
    <span class="entity-tag">
      ${esc(t)}
      <button class="remove-tag" data-idx="${i}" title="Retirer">&times;</button>
    </span>
  `).join('');
  container.querySelectorAll('.remove-tag').forEach(btn => {
    btn.addEventListener('click', () => {
      doc.forgottenTerms.splice(parseInt(btn.dataset.idx), 1);
      renderForgottenTags();
    });
  });
  // Show "Régénérer" as soon as there is at least one term to add
  $('#btn-regenerate').style.display = doc.forgottenTerms.length ? '' : 'none';
}

function addForgottenTerm() {
  const doc = currentDoc();
  if (!doc || doc.error) return;
  const input = $('#forgotten-input');
  // Comma/newline separated → several terms at once.
  splitTerms(input.value).forEach(val => pushUnique(doc.forgottenTerms, val));
  input.value = '';
  renderForgottenTags();
}

$('#forgotten-add').addEventListener('click', addForgottenTerm);
$('#forgotten-input').addEventListener('keypress', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); addForgottenTerm(); }
});

// Regenerate the current document (only it) with its forgotten terms.
$('#btn-regenerate').addEventListener('click', async () => {
  const doc = currentDoc();
  if (!doc || !doc.forgottenTerms.length) return;
  showLoading('Régénération en cours...');
  try {
    const updated = await anonymizeFile(doc.file, doc.forgottenTerms);
    updated.docVersion = doc.docVersion + 1;
    state.docs[state.docIndex] = updated;
    renderCurrentDoc();
  } catch (e) {
    alert(`Erreur: ${e.message}`);
  } finally {
    hideLoading();
  }
});

$('#btn-download-anon').addEventListener('click', () => {
  const doc = currentDoc();
  if (doc && doc.anonFileId) downloadFile(doc.anonFileId, doc.anonFilename);
});
$('#btn-download-mapping').addEventListener('click', () => {
  const doc = currentDoc();
  if (doc && doc.mappingFileId) downloadFile(doc.mappingFileId, doc.mappingFilename);
});
$('#btn-new-doc').addEventListener('click', showUploadView);

function truncateMiddle(str, maxLen) {
  if (str.length <= maxLen) return str;
  const half = Math.floor((maxLen - 3) / 2);
  return str.slice(0, half) + '...' + str.slice(-half);
}

// Trigger a download via a temporary <a>. Works both in a normal browser and
// inside the pywebview/WebView2 native window, where window.open('_blank')
// would pop a blank window instead of downloading.
//
// IMPORTANT: only set the `download` attribute when we know the real filename.
// An empty `download=""` makes the browser name the file after the URL
// (e.g. the download UUID) instead of honouring the server's
// Content-Disposition (anonymise_...). When no name is given we omit the
// attribute entirely so the server-provided filename wins.
function triggerDownload(url, filename) {
  const a = document.createElement('a');
  a.href = url;
  if (filename) a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function downloadFile(fileId, filename) {
  triggerDownload(`/api/download/${fileId}`, filename);
}
window.downloadFile = downloadFile;

// ============================================================
// Tab 3: Restore
// ============================================================

function updateRestoreButton() {
  const btn = $('#btn-restore');
  if (btn) btn.disabled = !(state.restoreFile && state.mappingFile);
}

$('#btn-restore').addEventListener('click', async () => {
  if (!state.restoreFile || !state.mappingFile) return;
  const fileName = state.restoreFile.name;

  showLoading('Restauration en cours...');
  try {
    const formData = new FormData();
    formData.append('file', state.restoreFile);
    formData.append('mapping_file', state.mappingFile);

    state.restoreResult = await api('/api/deanonymize', { method: 'POST', body: formData });

    // Add to restore history
    const ext = fileName.toLowerCase().split('.').pop();
    state.restoreHistory.unshift({
      fileName,
      fileType: ext,
      fileId: state.restoreResult.file_id,
    });

    // Reset
    hide('#restore-mapping-section');
    clearFiletypePop('restore-drop-zone');
    state.restoreFile = null;
    state.mappingFile = null;
    $('#restore-file-name').textContent = '';
    $('#restore-mapping-name').textContent = '';
    $('#restore-file').value = '';
    $('#restore-mapping').value = '';

    renderRestoreHistory();
  } catch (e) {
    alert(`Erreur: ${e.message}`);
  } finally {
    hideLoading();
  }
});

function renderRestoreHistory() {
  const container = $('#restore-history');
  if (!state.restoreHistory.length) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = state.restoreHistory.map(item => `
    <div class="anon-history-item">
      <div class="anon-history-icon">${item.fileType === 'pptx' ? ICON_PPTX_SMALL : ICON_DOCX_SMALL}</div>
      <div class="anon-history-name" title="${esc(item.fileName)}">${esc(truncateMiddle(item.fileName, 40))}</div>
      <div class="anon-history-actions">
        <button class="btn btn-primary" onclick="downloadRestored('${item.fileId}')">Telecharger</button>
      </div>
    </div>
  `).join('');
}

function downloadRestored(fileId) {
  triggerDownload(`/api/download-restored/${fileId}`);
}
window.downloadRestored = downloadRestored;

// ============================================================
// Multi-document progress overlay (shared by processAnonFiles)
// ============================================================

function _formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function _showBatchLoadingOverlay(total) {
  showLoading(`Anonymisation du lot — 0 / ${total}`);
  show('#loading-batch-progress');
  $('#loading-batch-bar').style.width = '0%';
  $('#loading-batch-text').textContent = 'Préparation…';
}

function _updateBatchLoadingOverlay(done, total, currentFile) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  $('#loading-text').textContent = `Anonymisation du lot — ${done} / ${total}`;
  $('#loading-batch-bar').style.width = `${pct}%`;
  $('#loading-batch-text').textContent = currentFile
    ? `Document en cours : ${currentFile}`
    : '';
}

function _hideBatchLoadingOverlay() {
  hide('#loading-batch-progress');
  hideLoading();
}

// ── Fast mode (ZIP): one server-side batch job, no per-doc editing ──

async function startBatch() {
  if (state.anonFiles.length < 2) return;
  _showBatchLoadingOverlay(state.anonFiles.length);

  const form = new FormData();
  state.anonFiles.forEach(f => form.append('files', f));
  form.append('manual_entities', JSON.stringify(buildManualEntities()));

  try {
    const res = await fetch('/api/anonymize-batch', { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Erreur serveur');
    }
    const { job_id, total } = await res.json();
    state.batchJobId = job_id;
    await pollBatchStatus(job_id, total);
  } catch (e) {
    _hideBatchLoadingOverlay();
    alert(`Erreur: ${e.message}`);
  }
}

async function pollBatchStatus(jobId, total) {
  while (true) {
    let data;
    try {
      const res = await fetch(`/api/batch-status/${jobId}`);
      data = await res.json();
    } catch (e) {
      await new Promise(r => setTimeout(r, 1500));
      continue;
    }
    _updateBatchLoadingOverlay(data.done, total, data.current_file);

    if (data.status === 'completed') {
      _hideBatchLoadingOverlay();
      // Hide the selection UI, show the ZIP result.
      hide('#anon-drop-zone');
      hide('#anon-file-list');
      hide('#anon-preview-actions');
      hide('#project-selector');
      hide('#manual-entities-section');
      show('#batch-panel');
      const errCount = (data.file_errors || []).length;
      const skipCount = (data.skipped || []).length;
      let summary = `${data.done - errCount - skipCount} document(s) anonymisé(s).`;
      if (errCount) summary += ` ${errCount} erreur(s).`;
      if (skipCount) summary += ` ${skipCount} ignoré(s) (format non supporté).`;
      $('#batch-result-summary').textContent = summary;
      return;
    }
    if (data.status === 'failed') {
      _hideBatchLoadingOverlay();
      alert(`Anonymisation echouee: ${data.error}`);
      return;
    }
    await new Promise(r => setTimeout(r, 800));
  }
}

$('#btn-batch-download').addEventListener('click', () => {
  if (state.batchJobId) triggerDownload(`/api/batch-download/${state.batchJobId}`);
});
$('#btn-batch-reset').addEventListener('click', showUploadView);

// ============================================================
// Init
// ============================================================

// First-launch install modal. The NER model must be loaded into memory on
// every launch (~10 s when cached, a ~400 Mo download the very first time).
// We ask for explicit consent the first time, then auto-load on later launches.
const MODEL_INSTALLED_FLAG = 'cleardeck_model_installed';

function setInstallState(state, { title, text, btn } = {}) {
  const card = document.querySelector('#install-modal .install-card');
  if (card) card.setAttribute('data-state', state);
  if (title !== undefined) document.getElementById('install-title').textContent = title;
  if (text !== undefined) document.getElementById('install-text').textContent = text;
  if (btn !== undefined) document.getElementById('install-btn').textContent = btn;
}

function showInstallModal() {
  const m = document.getElementById('install-modal');
  if (m) m.style.display = 'flex';
}

function hideInstallModal() {
  const m = document.getElementById('install-modal');
  if (!m) return;
  m.classList.add('install-modal--closing');
  setTimeout(() => {
    m.style.display = 'none';
    m.classList.remove('install-modal--closing');
  }, 260);
}

async function fetchHealth() {
  try {
    const res = await fetch('/api/health');
    return await res.json();
  } catch (e) {
    return null;
  }
}

async function pollUntilReady() {
  setInstallState('installing', {
    title: 'Installation en cours…',
    text: localStorage.getItem(MODEL_INSTALLED_FLAG)
      ? 'Chargement du modèle d\'anonymisation…'
      : 'Téléchargement du modèle (~400 Mo). Selon votre connexion, cela peut prendre quelques minutes.',
  });
  while (true) {
    const data = await fetchHealth();
    if (data && data.model_error) {
      setInstallState('error', {
        title: 'Échec de l\'installation',
        text: data.model_error,
        btn: 'Réessayer',
      });
      return;
    }
    if (data && data.model_ready) {
      localStorage.setItem(MODEL_INSTALLED_FLAG, '1');
      setInstallState('ready', {
        title: 'Modèle prêt',
        text: 'L\'anonymiseur est prêt à l\'emploi.',
      });
      setTimeout(hideInstallModal, 1100);
      return;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
}

async function startInstall() {
  try {
    await fetch('/api/install-model', { method: 'POST' });
  } catch (e) {
    /* the poll loop will surface a persistent failure */
  }
  pollUntilReady();
}

async function initModelGate() {
  const data = await fetchHealth();
  if (data === null) {
    setTimeout(initModelGate, 1500);  // server not up yet
    return;
  }
  if (data.model_ready) {
    hideInstallModal();
    return;
  }

  showInstallModal();
  document.getElementById('install-btn').onclick = startInstall;

  if (data.model_error) {
    setInstallState('error', {
      title: 'Échec de l\'installation',
      text: data.model_error,
      btn: 'Réessayer',
    });
  } else if (localStorage.getItem(MODEL_INSTALLED_FLAG) || data.installing) {
    // Already installed once (or a load is already running) → auto-load.
    startInstall();
  } else {
    // First ever launch → ask for consent before the ~400 Mo download.
    setInstallState('idle', {
      title: 'Préparer l\'anonymiseur',
      text: 'Au premier lancement, ClearDeck télécharge le modèle d\'IA d\'anonymisation (~400 Mo, une seule fois). Tout reste en local sur votre machine.',
      btn: 'Lancer l\'installation',
    });
  }
}

initModelGate();
loadProjectsDropdown();
loadProjects();
renderManualTerms();
