/**
 * ClearDeck — Frontend application logic
 * Single-page app with 3 tabs: Projects, Anonymize, Restore
 */

// ============================================================
// State
// ============================================================

const state = {
  currentTab: 'anonymize',
  projects: [],
  // Project form
  editingEntities: null, // { name, client, sector, ... , entities }
  logoFiles: [],       // File objects for logo upload
  logoHashes: [],      // computed phash strings
  logoThumbnail: null, // data URL of first logo for project button
  // Anonymize
  selectedFile: null,
  batchFiles: [],     // File[] when >= 2 files dropped
  batchJobId: null,
  selectedProjectId: '',
  forgottenTerms: [],  // terms the user adds after seeing the first version
  docVersion: 1,       // bumped on each regeneration (display only, not the filename)
  anonResult: null,
  anonHistory: [],     // { fileName, fileType, anonFileId, mappingFileId, replacements }
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
// Tab 1: Projects
// ============================================================

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
        <p>Aucun projet. Creez-en un pour commencer.</p>
      </div>`;
    return;
  }

  container.innerHTML = state.projects.map(p => {
    const logo = p.logo_thumbnail
      ? `<img class="project-card-logo" src="${p.logo_thumbnail}" alt="">`
      : '';
    return `
    <div class="project-card" data-id="${p.id}">
      <div class="card-actions">
        <button title="Modifier" onclick="editProject('${p.id}')">Edit</button>
        <button title="Supprimer" onclick="deleteProject('${p.id}')">&times;</button>
      </div>
      ${logo}
      <h4>${esc(p.name)}</h4>
      <p class="client">${esc(p.client)}</p>
      <p class="meta">${p.entity_count} entité${p.entity_count > 1 ? 's' : ''}${p.logo_count ? ` · ${p.logo_count} logo${p.logo_count > 1 ? 's' : ''}` : ''}</p>
    </div>`;
  }).join('');
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// New project form
$('#btn-new-project').addEventListener('click', () => {
  // Reset form
  ['pf-name', 'pf-client', 'pf-subsidiaries', 'pf-contacts', 'pf-notes']
    .forEach(id => $(`#${id}`).value = '');
  state.logoFiles = [];
  state.logoHashes = [];
  state.logoThumbnail = null;
  renderLogoPreview();
  hide('#entity-editor');
  show('#project-form');
});

// Logo file upload
$('#logo-browse').addEventListener('click', (e) => { e.stopPropagation(); $('#pf-logos').click(); });
$('#logo-drop-zone').addEventListener('click', () => $('#pf-logos').click());
$('#logo-drop-zone').addEventListener('dragover', e => { e.preventDefault(); $('#logo-drop-zone').classList.add('dragover'); });
$('#logo-drop-zone').addEventListener('dragleave', () => $('#logo-drop-zone').classList.remove('dragover'));
$('#logo-drop-zone').addEventListener('drop', e => {
  e.preventDefault();
  $('#logo-drop-zone').classList.remove('dragover');
  if (e.dataTransfer.files.length) {
    addLogoFiles(Array.from(e.dataTransfer.files));
  }
});
$('#pf-logos').addEventListener('change', () => {
  addLogoFiles(Array.from($('#pf-logos').files));
  $('#pf-logos').value = '';
});

function fileToDataURL(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.readAsDataURL(file);
  });
}

function addLogoFiles(files) {
  for (const f of files) {
    const ext = f.name.toLowerCase().split('.').pop();
    if (!['png', 'jpg', 'jpeg'].includes(ext)) {
      alert(`Format non supporte : .${ext}. Utilisez PNG ou JPG.`);
      continue;
    }
    state.logoFiles.push(f);
  }
  // Capture first logo as thumbnail
  if (state.logoFiles.length > 0 && !state.logoThumbnail) {
    fileToDataURL(state.logoFiles[0]).then(url => { state.logoThumbnail = url; });
  }
  if (state.logoFiles.length === 0) state.logoThumbnail = null;
  renderLogoPreview();
}

function renderLogoPreview() {
  const container = $('#logo-preview-list');
  container.innerHTML = '';
  state.logoFiles.forEach((f, i) => {
    const item = document.createElement('div');
    item.className = 'logo-preview-item';
    const img = document.createElement('img');
    img.src = URL.createObjectURL(f);
    img.alt = f.name;
    const btn = document.createElement('button');
    btn.className = 'remove-logo';
    btn.textContent = '\u00d7';
    btn.addEventListener('click', () => {
      state.logoFiles.splice(i, 1);
      renderLogoPreview();
    });
    item.appendChild(img);
    item.appendChild(btn);
    container.appendChild(item);
  });
}

$('#btn-cancel-project').addEventListener('click', () => {
  hide('#project-form');
});

$('#btn-cancel-entities').addEventListener('click', () => {
  hide('#entity-editor');
  state.editingEntities = null;
});

// Create project — seeds entities locally from the form, then opens the editor
$('#btn-generate-entities').addEventListener('click', async () => {
  const name = $('#pf-name').value.trim();
  const client = $('#pf-client').value.trim();
  if (!name || !client) {
    alert('Nom du projet et nom du client sont requis.');
    return;
  }

  showLoading('Création du projet...');
  try {
    // Upload logos in parallel with entity seeding if any
    let logoHashesPromise = Promise.resolve([]);
    if (state.logoFiles.length > 0) {
      const logoForm = new FormData();
      state.logoFiles.forEach(f => logoForm.append('logos', f));
      logoHashesPromise = api('/api/projects/upload-logos', {
        method: 'POST',
        body: logoForm,
      }).then(r => r.logo_hashes);
    }

    const [result, logoHashes] = await Promise.all([
      api('/api/projects/seed-entities', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          client,
          subsidiaries: $('#pf-subsidiaries').value,
          contacts: $('#pf-contacts').value,
          notes: $('#pf-notes').value,
        }),
      }),
      logoHashesPromise,
    ]);

    state.logoHashes = logoHashes;

    state.editingEntities = {
      name, client,
      subsidiaries: $('#pf-subsidiaries').value,
      contacts: $('#pf-contacts').value,
      notes: $('#pf-notes').value,
      entities: result.entities,
      logo_hashes: logoHashes,
      logo_thumbnail: state.logoThumbnail || '',
    };

    hide('#project-form');
    renderEntityEditor();
    show('#entity-editor');
  } catch (e) {
    alert(`Erreur: ${e.message}`);
  } finally {
    hideLoading();
  }
});

function renderEntityEditor() {
  if (!state.editingEntities) return;
  $('#entity-editor-title').textContent = state.editingEntities.name;
  const ents = state.editingEntities.entities;
  for (const cat of ['entreprises', 'personnes', 'lieux', 'autres']) {
    renderTags(cat, ents[cat] || []);
  }
}

function renderTags(category, tags) {
  const container = $(`#tags-${category}`);
  container.innerHTML = tags.map((t, i) => `
    <span class="entity-tag">
      ${esc(t)}
      <button class="remove-tag" data-cat="${category}" data-idx="${i}">&times;</button>
    </span>
  `).join('');

  // Bind remove buttons
  container.querySelectorAll('.remove-tag').forEach(btn => {
    btn.addEventListener('click', () => {
      const cat = btn.dataset.cat;
      const idx = parseInt(btn.dataset.idx);
      state.editingEntities.entities[cat].splice(idx, 1);
      renderTags(cat, state.editingEntities.entities[cat]);
    });
  });
}

// Add entity buttons
$$('.entity-add .btn-add').forEach(btn => {
  btn.addEventListener('click', () => {
    const input = btn.previousElementSibling;
    const cat = btn.closest('.entity-cat').dataset.cat;
    const val = input.value.trim();
    if (!val) return;
    if (!state.editingEntities) return;
    if (!state.editingEntities.entities[cat]) state.editingEntities.entities[cat] = [];
    state.editingEntities.entities[cat].push(val);
    input.value = '';
    renderTags(cat, state.editingEntities.entities[cat]);
  });
});

// Enter key on entity inputs
$$('.entity-add .entity-input').forEach(input => {
  input.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      input.nextElementSibling.click();
    }
  });
});

// Save project
$('#btn-save-project').addEventListener('click', async () => {
  if (!state.editingEntities) return;
  showLoading('Sauvegarde du projet...');
  try {
    await api('/api/projects/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state.editingEntities),
    });
    hide('#entity-editor');
    state.editingEntities = null;
    await loadProjects();
  } catch (e) {
    alert(`Erreur: ${e.message}`);
  } finally {
    hideLoading();
  }
});

// Edit project
window.editProject = async function(id) {
  showLoading('Chargement...');
  try {
    const project = await api(`/api/projects/${id}`);
    state.editingEntities = {
      name: project.name,
      client: project.client,
      subsidiaries: project.subsidiaries || '',
      contacts: project.contacts || '',
      notes: project.notes || '',
      entities: project.entities,
      logo_hashes: project.logo_hashes || [],
      logo_thumbnail: project.logo_thumbnail || '',
    };
    state.logoHashes = project.logo_hashes || [];
    state.logoThumbnail = project.logo_thumbnail || null;
    hide('#project-form');
    renderEntityEditor();
    show('#entity-editor');
  } catch (e) {
    alert(`Erreur: ${e.message}`);
  } finally {
    hideLoading();
  }
};

// Delete project
window.deleteProject = async function(id) {
  if (!confirm('Supprimer ce projet ?')) return;
  try {
    await api(`/api/projects/${id}`, { method: 'DELETE' });
    await loadProjects();
  } catch (e) {
    alert(`Erreur: ${e.message}`);
  }
};

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

async function loadProjectsDropdown() {
  try {
    const projects = await api('/api/projects');
    const select = $('#anon-project');
    select.innerHTML = '<option value="">Sans projet</option>';
    projects.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = `${p.name} (${p.client})`;
      select.appendChild(opt);
    });

    // Render project buttons with logo thumbnails
    const btnContainer = $('#project-buttons');
    if (projects.length === 0) {
      hide('#project-selector');
    } else {
      show('#project-selector');
      btnContainer.innerHTML = projects.map(p => {
        const thumb = p.logo_thumbnail
          ? `<img class="project-btn-logo" src="${p.logo_thumbnail}" alt="">`
          : '';
        return `<button class="project-btn${state.selectedProjectId === p.id ? ' active' : ''}" data-project-id="${p.id}">${thumb}${esc(p.name)}</button>`;
      }).join('');
    }

    // Bind project button clicks (toggle selection)
    btnContainer.querySelectorAll('.project-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const pid = btn.dataset.projectId;
        if (state.selectedProjectId === pid) {
          state.selectedProjectId = '';
          select.value = '';
          btn.classList.remove('active');
          updateProjectSelectorLabel();
        } else {
          state.selectedProjectId = pid;
          select.value = pid;
          btnContainer.querySelectorAll('.project-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          updateProjectSelectorLabel();
        }

        const manual = $('#manual-entities-section');
        if (state.selectedProjectId) {
          hide(manual);
        } else {
          show(manual);
        }
        updatePreviewButton();
      });
    });
  } catch (e) {
    console.error(e);
  }
}

// Project selector toggle
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

function updateProjectSelectorLabel() {
  const label = $('#project-selector-label');
  if (state.selectedProjectId) {
    const proj = state.projects.find(p => p.id === state.selectedProjectId);
    label.textContent = proj ? proj.name : 'Projet sélectionné';
  } else {
    label.textContent = 'Associer un projet (optionnel)';
  }
}

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

// Setup anon hero drop
setupHeroDrop('anon-file', 'anon-drop-zone', 'anon-file-name', 'selectedFile', {
  onFile: (file) => {
    showFiletypePop(file.name, 'anon-drop-zone');
    show('#anon-preview-actions');
    hide('#batch-panel');
    hide('#anon-result-panel');
    state.batchFiles = [];
    state.forgottenTerms = [];
  },
  onClear: () => {
    clearFiletypePop('anon-drop-zone');
    hide('#anon-preview-actions');
    state.forgottenTerms = [];
  },
  onMultiple: (files) => {
    // Filter to supported types
    const supported = files.filter(f => /\.(docx|pptx)$/i.test(f.name));
    if (supported.length === 0) {
      alert('Aucun document .docx ou .pptx parmi les fichiers déposés.');
      return;
    }
    if (supported.length > 50) {
      alert('Maximum 50 fichiers par lot. Seuls les 50 premiers seront traités.');
      state.batchFiles = supported.slice(0, 50);
    } else {
      state.batchFiles = supported;
    }
    enterBatchMode();
  }
});

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
  const hasFile = !!state.selectedFile;
  $('#btn-anonymize').disabled = !hasFile;
}

// Manual entity fields update preview button
['manual-companies', 'manual-persons', 'manual-other'].forEach(id => {
  $(`#${id}`)?.addEventListener('input', updatePreviewButton);
});

// Switch to the result view (document ready + add-missed-terms box)
function showResultPanel() {
  hide('#anon-drop-zone');
  hide('#anon-preview-actions');
  hide('#manual-entities-section');
  hide('#project-selector');
  show('#anon-result-panel');
}

// Return to the upload view (e.g. "Anonymiser un autre document")
function showUploadView() {
  hide('#anon-result-panel');
  show('#anon-drop-zone');
  show('#project-selector');
  hide('#anon-preview-actions');
  clearFiletypePop('anon-drop-zone');
  // Reset selection
  state.selectedFile = null;
  state.forgottenTerms = [];
  state.anonResult = null;
  $('#anon-file-name').textContent = '';
  $('#anon-file').value = '';
  if (!state.selectedProjectId) show('#manual-entities-section');
}

// Run anonymization (auto-confirm all detections) and show the result.
// `extraTerms` are the forgotten terms the user added after the first pass.
async function runAnonymize(extraTerms) {
  if (!state.selectedFile) return;
  const fileName = state.selectedFile.name;

  showLoading('Anonymisation en cours...');
  try {
    const formData = new FormData();
    formData.append('file', state.selectedFile);
    if (state.selectedProjectId) {
      formData.append('project_id', state.selectedProjectId);
    } else {
      formData.append('manual_entities', JSON.stringify(buildManualEntities()));
    }
    formData.append('extra_terms', JSON.stringify(extraTerms || []));

    state.anonResult = await api('/api/anonymize', { method: 'POST', body: formData });
    const replacements = extractReplacements(state.anonResult.mapping);

    // Update or create the matching history entry (regenerations replace it)
    const ext = fileName.toLowerCase().split('.').pop();
    const entry = {
      fileName,
      fileType: ext,
      anonFileId: state.anonResult.anon_file_id,
      mappingFileId: state.anonResult.mapping_file_id,
      anonFileName: state.anonResult.anon_filename,
      mappingFileName: state.anonResult.mapping_filename,
      replacements,
    };
    if (state._currentHistoryId && state.anonHistory[0] &&
        state.anonHistory[0]._id === state._currentHistoryId) {
      state.anonHistory[0] = { ...entry, _id: state._currentHistoryId };
    } else {
      state._currentHistoryId = `h${Date.now()}`;
      state.anonHistory.unshift({ ...entry, _id: state._currentHistoryId });
    }

    renderAnonResult(replacements);
    renderAnonHistory();
    showResultPanel();
  } catch (e) {
    alert(`Erreur: ${e.message}`);
  } finally {
    hideLoading();
  }
}

// Pull a flat [{original, placeholder}] list out of the mapping JSON.
function extractReplacements(mapping) {
  if (!mapping || !Array.isArray(mapping.entities)) return [];
  return mapping.entities.map(e => ({
    original: e.original,
    placeholder: e.placeholder,
  }));
}

// First anonymization (from the upload view)
$('#btn-anonymize').addEventListener('click', () => {
  state.forgottenTerms = [];
  state.docVersion = 1;
  state._currentHistoryId = null;  // this is a brand new document
  runAnonymize([]);
});

function buildManualEntities() {
  const lines = (id) => $(`#${id}`).value.split('\n').map(s => s.trim()).filter(Boolean);
  return {
    entreprises: lines('manual-companies'),
    personnes: lines('manual-persons'),
    lieux: [],
    autres: lines('manual-other'),
  };
}

// Render the result view after an anonymization pass.
function renderAnonResult(replacements) {
  $('#version-badge').textContent = `V${state.docVersion}`;

  const n = replacements.length;
  $('#result-summary').textContent = n > 0
    ? `${n} terme${n > 1 ? 's' : ''} masqué${n > 1 ? 's' : ''}. Téléchargez le document, ou complétez les oublis ci-dessous.`
    : "Aucun terme détecté. Ajoutez les termes à masquer ci-dessous, puis régénérez.";

  // Categorise: image alt texts (placeholder [ALT_x]) get their own discreet,
  // collapsible section; the rest splits into "added by hand" vs "found by AI".
  const manualSet = new Set(state.forgottenTerms.map(t => t.toLowerCase()));
  const isAlt = (r) => (r.placeholder || '').startsWith('[ALT_');
  const alt = replacements.filter(isAlt);
  const rest = replacements.filter(r => !isAlt(r));
  const manual = rest.filter(r => manualSet.has((r.original || '').toLowerCase()));
  const ai = rest.filter(r => !manualSet.has((r.original || '').toLowerCase()));

  const renderList = (items) => `<div class="result-mapping-list">${items.map(r =>
    `<span class="anon-mapping-entry"><span class="anon-mapping-original">${esc(r.original)}</span> → ${esc(r.placeholder)}</span>`
  ).join('')}</div>`;

  const renderGroup = (title, items, modifier) => items.length
    ? `<div class="mapping-group${modifier ? ' ' + modifier : ''}">
         <h5 class="mapping-group-title">${title} · ${items.length}</h5>
         ${renderList(items)}
       </div>`
    : '';

  // Alt texts: collapsed by default, expand to read.
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

// ── Forgotten terms (missed by the AI) ──

function renderForgottenTags() {
  const container = $('#forgotten-tags');
  container.innerHTML = state.forgottenTerms.map((t, i) => `
    <span class="entity-tag">
      ${esc(t)}
      <button class="remove-tag" data-idx="${i}" title="Retirer">&times;</button>
    </span>
  `).join('');
  container.querySelectorAll('.remove-tag').forEach(btn => {
    btn.addEventListener('click', () => {
      state.forgottenTerms.splice(parseInt(btn.dataset.idx), 1);
      renderForgottenTags();
    });
  });
  // Show "Régénérer" as soon as there is at least one term to add
  $('#btn-regenerate').style.display = state.forgottenTerms.length ? '' : 'none';
}

function addForgottenTerm() {
  const input = $('#forgotten-input');
  const val = input.value.trim();
  if (!val) return;
  // De-dup case-insensitively (matching is case-insensitive anyway)
  if (!state.forgottenTerms.some(t => t.toLowerCase() === val.toLowerCase())) {
    state.forgottenTerms.push(val);
  }
  input.value = '';
  renderForgottenTags();
}

$('#forgotten-add').addEventListener('click', addForgottenTerm);
$('#forgotten-input').addEventListener('keypress', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); addForgottenTerm(); }
});

$('#btn-regenerate').addEventListener('click', () => {
  if (!state.forgottenTerms.length) return;
  state.docVersion += 1;
  runAnonymize(state.forgottenTerms);
});

$('#btn-download-anon').addEventListener('click', () => {
  if (state.anonResult) downloadFile(state.anonResult.anon_file_id, state.anonResult.anon_filename);
});
$('#btn-download-mapping').addEventListener('click', () => {
  if (state.anonResult) downloadFile(state.anonResult.mapping_file_id, state.anonResult.mapping_filename);
});
$('#btn-new-doc').addEventListener('click', showUploadView);

function truncateMiddle(str, maxLen) {
  if (str.length <= maxLen) return str;
  const half = Math.floor((maxLen - 3) / 2);
  return str.slice(0, half) + '...' + str.slice(-half);
}

function renderAnonHistory() {
  const container = $('#anon-history');
  if (!state.anonHistory.length) {
    container.innerHTML = '';
    return;
  }
  // The full mapping is shown in the result panel above — keep the history
  // compact (file + download actions) to avoid duplicating the long list.
  // Filenames go in data-* attributes (escaped) and clicks are bound below,
  // so names containing apostrophes/quotes can't break an inline onclick.
  container.innerHTML = state.anonHistory.map(item => `
    <div class="anon-history-item">
      <div class="anon-history-icon">${item.fileType === 'pptx' ? ICON_PPTX_SMALL : ICON_DOCX_SMALL}</div>
      <div class="anon-history-name" title="${esc(item.fileName)}">${esc(truncateMiddle(item.fileName, 40))}</div>
      <div class="anon-history-actions">
        <button class="btn btn-primary" data-dl="${esc(item.anonFileId)}" data-name="${esc(item.anonFileName || '')}">Telecharger</button>
        <button class="btn btn-secondary" data-dl="${esc(item.mappingFileId)}" data-name="${esc(item.mappingFileName || '')}">Table de corres.</button>
      </div>
    </div>`).join('');

  container.querySelectorAll('button[data-dl]').forEach(btn => {
    btn.addEventListener('click', () => downloadFile(btn.dataset.dl, btn.dataset.name || undefined));
  });
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
// Batch mode (multi-file upload + ZIP download)
// ============================================================

function _formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function enterBatchMode() {
  hide('#anon-preview-actions');
  hide('#anon-result-panel');
  hide('#batch-result');
  show('#batch-panel');

  $('#batch-file-count').textContent = state.batchFiles.length;
  const list = $('#batch-file-list');
  list.innerHTML = '';
  state.batchFiles.forEach(f => {
    const li = document.createElement('li');
    li.style.display = 'flex';
    li.style.justifyContent = 'space-between';
    li.style.padding = '4px 0';
    li.style.borderBottom = '1px solid #e5e7eb';
    li.innerHTML = `<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:75%;">${f.name}</span><span style="color:#6b7280;">${_formatBytes(f.size)}</span>`;
    list.appendChild(li);
  });

  $('#btn-batch-start').disabled = false;
  $('#btn-batch-start').textContent = "Lancer l'anonymisation du lot";
}

function exitBatchMode() {
  state.batchFiles = [];
  state.batchJobId = null;
  hide('#batch-panel');
  $('#anon-file').value = '';
}

$('#btn-batch-cancel').addEventListener('click', exitBatchMode);

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

$('#btn-batch-start').addEventListener('click', async () => {
  if (!state.batchFiles.length) return;
  const btn = $('#btn-batch-start');
  btn.disabled = true;
  btn.textContent = 'Anonymisation en cours...';

  _showBatchLoadingOverlay(state.batchFiles.length);

  const form = new FormData();
  state.batchFiles.forEach(f => form.append('files', f));
  if (state.selectedProjectId) form.append('project_id', state.selectedProjectId);

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
    btn.disabled = false;
    btn.textContent = "Lancer l'anonymisation du lot";
  }
});

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
      show('#batch-result');
      const errCount = (data.file_errors || []).length;
      const skipCount = (data.skipped || []).length;
      let summary = `${data.done - errCount - skipCount} document(s) anonymise(s).`;
      if (errCount) summary += ` ${errCount} erreur(s).`;
      if (skipCount) summary += ` ${skipCount} ignore(s) (format non supporte).`;
      $('#batch-result-summary').textContent = summary;
      $('#btn-batch-start').disabled = true;
      return;
    }
    if (data.status === 'failed') {
      _hideBatchLoadingOverlay();
      alert(`Anonymisation echouee: ${data.error}`);
      $('#btn-batch-start').disabled = false;
      $('#btn-batch-start').textContent = "Lancer l'anonymisation du lot";
      return;
    }
    await new Promise(r => setTimeout(r, 800));
  }
}

$('#btn-batch-download').addEventListener('click', () => {
  if (!state.batchJobId) return;
  triggerDownload(`/api/batch-download/${state.batchJobId}`);
});

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
