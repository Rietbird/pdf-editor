let sessionId = null;
let pagesData = null;

const pdfInput      = document.getElementById('pdf-input');
const fileNameSpan  = document.getElementById('file-name');
const uploadBtn     = document.getElementById('upload-btn');
const loadingDiv    = document.getElementById('loading');
const editorSection = document.getElementById('editor-section');
const editorDiv     = document.getElementById('editor');
const saveBtn       = document.getElementById('save-btn');
const resetBtn      = document.getElementById('reset-btn');
const colorPicker   = document.getElementById('color-picker');
const themeToggle   = document.getElementById('theme-toggle');

// ── Helper: show/hide loading ────────────────────────────────────────────────
function showLoading() { loadingDiv.classList.add('visible'); }
function hideLoading() { loadingDiv.classList.remove('visible'); }

// ── Thema wisselen ──────────────────────────────────────────────────────────
themeToggle.addEventListener('click', () => {
  const html = document.documentElement;
  const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  localStorage.setItem('vict-theme', next);
});

// ── Bestand selecteren ──────────────────────────────────────────────────────
pdfInput.addEventListener('change', () => {
  const file = pdfInput.files[0];
  if (file) {
    fileNameSpan.textContent = file.name;
    uploadBtn.disabled = false;
  }
});

// ── Upload & converteren ────────────────────────────────────────────────────
uploadBtn.addEventListener('click', async () => {
  const file = pdfInput.files[0];
  if (!file) return;

  uploadBtn.disabled = true;
  showLoading();
  editorSection.hidden = true;

  try {
    const formData = new FormData();
    formData.append('file', file);

    const res = await fetch('/upload', { method: 'POST', body: formData });
    const contentType = res.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
      throw new Error('Server gaf een onverwacht antwoord. Probeer het opnieuw.');
    }
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Upload mislukt');
    }
    sessionId = data.session_id;
    pagesData = data.pages;

    renderPages(data.pages);
    editorSection.hidden = false;
  } catch (e) {
    alert('Fout: ' + e.message);
    uploadBtn.disabled = false;
  } finally {
    hideLoading();
  }
});

// ── Toolbar: Bold / Italic / Underline ──────────────────────────────────────
document.querySelectorAll('#toolbar button[data-cmd]').forEach(btn => {
  btn.addEventListener('mousedown', (e) => {
    e.preventDefault();
    document.execCommand(btn.dataset.cmd, false, null);
  });
});

// ── Toolbar: Kleur picker ───────────────────────────────────────────────────
colorPicker.addEventListener('input', () => {
  const focused = document.querySelector('.text-block:focus');
  if (focused) {
    focused.style.color = colorPicker.value;
    focused.classList.add('modified');
  }
});

// ── Opnieuw knop ────────────────────────────────────────────────────────────
resetBtn.addEventListener('click', () => {
  if (!pagesData) return;
  if (!confirm('Alle bewerkingen ongedaan maken?')) return;
  renderPages(pagesData);
});

// ── PDF font name → CSS font-family mapping ────────────────────────────────
function mapPdfFont(pdfFont) {
  if (!pdfFont) return 'system-ui, sans-serif';
  const f = pdfFont.toLowerCase();
  // Verwijder subset prefix (bijv. "BCDFGH+Calibri" → "Calibri")
  const clean = pdfFont.replace(/^[A-Z]{6}\+/, '');
  // Map veelvoorkomende PDF fonts
  if (f.includes('calibri')) return 'Calibri, system-ui, sans-serif';
  if (f.includes('arial'))   return 'Arial, Helvetica, sans-serif';
  if (f.includes('times'))   return '"Times New Roman", Times, serif';
  if (f.includes('courier')) return '"Courier New", Courier, monospace';
  if (f.includes('verdana')) return 'Verdana, Geneva, sans-serif';
  if (f.includes('tahoma'))  return 'Tahoma, Geneva, sans-serif';
  if (f.includes('georgia')) return 'Georgia, serif';
  if (f.includes('trebuchet')) return '"Trebuchet MS", sans-serif';
  if (f.includes('comic'))   return '"Comic Sans MS", cursive';
  if (f.includes('impact'))  return 'Impact, sans-serif';
  // Gebruik de naam direct als fallback
  return `"${clean}", system-ui, sans-serif`;
}

// ── Pagina's renderen ───────────────────────────────────────────────────────
function renderPages(pages) {
  editorDiv.innerHTML = '';

  pages.forEach((page, pageIdx) => {
    const pageDiv = document.createElement('div');
    pageDiv.className = 'pdf-page';
    pageDiv.style.width = page.width + 'pt';
    pageDiv.style.height = page.height + 'pt';
    pageDiv.style.backgroundImage = `url(data:image/jpeg;base64,${page.image})`;
    pageDiv.style.backgroundSize = '100% 100%';
    pageDiv.dataset.pageIdx = pageIdx;

    // Tekst blokken als bewerkbare overlays
    page.blocks.forEach((block, blockIdx) => {
      const span = document.createElement('span');
      span.className = 'text-block';
      span.contentEditable = 'true';
      span.spellcheck = false;
      span.textContent = block.text;
      span.dataset.blockIdx = blockIdx;

      // Positie op basis van bbox
      span.style.left = block.bbox[0] + 'pt';
      span.style.top = block.bbox[1] + 'pt';
      span.style.fontSize = block.size + 'pt';
      span.style.color = block.color;
      span.style.fontFamily = mapPdfFont(block.font);

      // Font weight/style op basis van flags
      if (block.flags & 16) span.style.fontWeight = 'bold';
      if (block.flags & 2) span.style.fontStyle = 'italic';

      // Afmetingen op basis van bbox
      const blockWidth = block.bbox[2] - block.bbox[0];
      const blockHeight = block.bbox[3] - block.bbox[1];
      span.style.width = blockWidth + 'pt';
      span.style.height = blockHeight + 'pt';

      // Originele tekst onthouden
      span.dataset.originalText = block.text;

      span.addEventListener('input', () => {
        if (span.textContent !== span.dataset.originalText) {
          span.classList.add('modified');
          // Bewaar originele afmetingen als minimum zodat witte cover
          // de originele tekst in de achtergrond volledig afdekt
          span.style.minWidth = blockWidth + 'pt';
          span.style.minHeight = blockHeight + 'pt';
          span.style.width = 'auto';
          span.style.height = 'auto';
        } else {
          span.classList.remove('modified');
          span.style.minWidth = '';
          span.style.minHeight = '';
          span.style.width = blockWidth + 'pt';
          span.style.height = blockHeight + 'pt';
        }
      });

      pageDiv.appendChild(span);
    });

    editorDiv.appendChild(pageDiv);
  });
}

// ── Opslaan / PDF downloaden ────────────────────────────────────────────────
saveBtn.addEventListener('click', async () => {
  if (!sessionId || !pagesData) return;

  saveBtn.disabled = true;
  saveBtn.textContent = 'Bezig…';

  try {
    // Verzamel bewerkte tekst per pagina en blok
    const editedPages = [];
    const pageDivs = editorDiv.querySelectorAll('.pdf-page');

    pageDivs.forEach((pageDiv) => {
      const blocks = [];
      const spans = pageDiv.querySelectorAll('.text-block');
      spans.forEach((span) => {
        blocks.push({ text: span.textContent, color: span.style.color });
      });
      editedPages.push({ blocks });
    });

    const res = await fetch(`/save/${sessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pages: editedPages }),
    });

    if (!res.ok) throw new Error('Opslaan mislukt');

    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = 'bewerkt.pdf';
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert('Fout: ' + e.message);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = 'Download PDF';
  }
});
