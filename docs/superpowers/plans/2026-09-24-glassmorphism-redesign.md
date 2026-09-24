# Glassmorphism UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete redesign of Local Drop's web interface with glassmorphism aesthetic, animated isometric dot grid background, responsive layouts, and ZIP bulk download functionality.

**Architecture:** Single-file Python server with embedded HTML/CSS/JavaScript. Canvas-based animated background, CSS Grid responsive layout, glassmorphism via backdrop-filter, localStorage theme persistence, and server-side ZIP generation for bulk downloads.

**Tech Stack:** Python 3.10+ (http.server, zipfile), HTML5 Canvas, CSS Grid, Vanilla JavaScript, QRious library (existing)

**Spec:** `docs/superpowers/specs/2026-09-24-glassmorphism-redesign.md`

## Global Constraints

- Python 3.10 minimum (existing constraint)
- Zero external Python dependencies (existing constraint)
- Single-file architecture in `local_share.py` with embedded HTML
- Responsive breakpoints: Mobile (<768px), Tablet (768-1024px), Desktop (>1024px)
- Theme transition: 0.4s cubic-bezier(0.4, 0.0, 0.2, 1)
- Accessibility: 4.5:1 color contrast minimum, keyboard navigation, ARIA labels
- Performance: 60fps canvas animation, <100ms interaction response
- Browser support: Chrome 90+, Firefox 88+, Safari 14+, Edge 90+

---

## File Structure

This plan modifies a single file:

**Modified:**
- `local_share.py` - Python HTTP server with embedded HTML/CSS/JS in `PAGE` variable
  - Add new endpoint: `/api/download-bulk` for ZIP generation
  - Replace entire `PAGE` variable with new glassmorphism design
  - HTML structure: Canvas background, header, stats, grid layout, file list, upload queue
  - CSS: CSS variables for theming, glassmorphism styles, responsive grid, animations
  - JavaScript: Canvas animation, theme toggle, file list layouts, ZIP download, existing features

---

### Task 1: Backend - ZIP Bulk Download Endpoint

**Files:**
- Modify: `local_share.py` (add new handler method and route)

**Interfaces:**
- Consumes: Existing `SHARED_DIRECTORY: Path`, `is_safe()` function
- Produces: `handle_bulk_download(self) -> None` - Creates ZIP from query params, streams to client

- [ ] **Step 1: Import zipfile module**

Add to imports section (after line 21):

```python
import zipfile
from io import BytesIO
```

- [ ] **Step 2: Write test for bulk download endpoint**

Create test file:

```python
# test_bulk_download.py (temporary test file)
import urllib.request
import urllib.parse

def test_bulk_download():
    # Assumes server running on localhost:8080 with test files
    params = urllib.parse.urlencode([('files', 'test1.txt'), ('files', 'test2.txt')])
    url = f'http://localhost:8080/api/download-bulk?{params}'
    
    response = urllib.request.urlopen(url)
    assert response.status == 200
    assert response.headers['Content-Type'] == 'application/zip'
    assert 'selected-files-' in response.headers['Content-Disposition']
    
    # Verify ZIP contents
    data = response.read()
    assert len(data) > 0
    print("✓ Bulk download returns valid ZIP")

if __name__ == '__main__':
    test_bulk_download()
```

- [ ] **Step 3: Add bulk download handler method**

Find the `RequestHandler` class (around line 200) and add this method before `do_GET`:

```python
def handle_bulk_download(self) -> None:
    """Create ZIP of requested files and stream to client."""
    try:
        # Parse file list from query parameters
        query = urlparse(self.path).query
        params = dict(
            (k, v if len(v) > 1 else v[0])
            for k, v in urllib.parse.parse_qs(query).items()
        )
        
        file_names = params.get('files', [])
        if isinstance(file_names, str):
            file_names = [file_names]
        
        if not file_names:
            self.send_error(HTTPStatus.BAD_REQUEST, "No files specified")
            return
        
        # Validate all files exist and are safe
        file_paths = []
        for name in file_names:
            if not is_safe(name):
                self.send_error(HTTPStatus.BAD_REQUEST, f"Invalid filename: {name}")
                return
            
            path = SHARED_DIRECTORY / name
            if not path.exists() or not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, f"File not found: {name}")
                return
            
            file_paths.append((name, path))
        
        # Calculate total size
        total_size = sum(p.stat().st_size for _, p in file_paths)
        if total_size > 500 * 1024 * 1024:  # 500MB limit
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, 
                          "Total size exceeds 500MB limit")
            return
        
        # Create ZIP in memory
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for name, path in file_paths:
                zip_file.write(path, name)
        
        zip_data = zip_buffer.getvalue()
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y-%m-%d-%H%M%S')
        filename = f'selected-files-{timestamp}.zip'
        
        # Send response
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', 'application/zip')
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Content-Length', str(len(zip_data)))
        self.end_headers()
        self.wfile.write(zip_data)
        
        logger.info(f"Bulk download: {len(file_names)} files ({total_size} bytes)")
        
    except Exception as e:
        logger.error(f"Bulk download error: {e}")
        self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))
```

- [ ] **Step 4: Add route to do_GET method**

Find `do_GET` method and add this condition at the beginning (after authentication check):

```python
if self.path.startswith('/api/download-bulk'):
    self.handle_bulk_download()
    return
```

Insert this after the existing `/api/files` check (around line 250).

- [ ] **Step 5: Manual test the endpoint**

Start server:
```bash
cd "C:\Users\User\Documents\n\local-drop"
python local_share.py
```

Test with curl (or browser):
```bash
curl "http://localhost:8080/api/download-bulk?files=test1.txt&files=test2.txt" -o test-download.zip
```

Expected: ZIP file downloads successfully with both files inside.

- [ ] **Step 6: Commit backend changes**

```bash
git add local_share.py
git commit -m "feat: add ZIP bulk download endpoint

- New /api/download-bulk endpoint
- Accepts multiple file query params
- Creates in-memory ZIP with timestamp filename
- Validates files and enforces 500MB limit
- Returns application/zip with proper headers

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: HTML Structure - Base Layout & Canvas

**Files:**
- Modify: `local_share.py:106-1499` (replace `PAGE` variable entirely)

**Interfaces:**
- Consumes: Existing QRious library (already embedded)
- Produces: HTML structure with semantic elements, canvas#bg-canvas, theme data attribute

- [ ] **Step 1: Write basic structure test**

Create temporary test file:

```python
# test_html_structure.py
def test_html_structure():
    from local_share import PAGE
    
    # Check essential elements exist
    assert '<canvas id="bg-canvas"' in PAGE
    assert 'data-theme="dark"' in PAGE
    assert 'id="theme-toggle"' in PAGE
    assert 'id="drop-zone"' in PAGE
    assert 'id="file-list"' in PAGE
    assert 'class="glass-card"' in PAGE
    
    print("✓ HTML structure contains all required elements")

if __name__ == '__main__':
    test_html_structure()
```

- [ ] **Step 2: Replace PAGE variable with new HTML structure**

Find the `PAGE` variable assignment (around line 106) and replace entire content with:

```python
PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="Local Drop - Share files on your local network">
<title>Local Drop</title>
<style>
/* CSS will be added in next task */
</style>
</head>
<body data-theme="dark">

<!-- Animated background canvas -->
<canvas id="bg-canvas" aria-hidden="true"></canvas>

<!-- Header -->
<header class="glass-card header">
  <h1 class="logo">Local Drop</h1>
  <button id="theme-toggle" class="theme-toggle" aria-label="Toggle theme">
    <span id="theme-icon">🌙</span>
  </button>
</header>

<!-- Stats row -->
<section class="stats-row">
  <div class="glass-card stat-card">
    <div class="stat-icon" aria-hidden="true">📁</div>
    <div class="stat-value" id="stat-files">0</div>
    <div class="stat-label">Files</div>
  </div>
  
  <div class="glass-card stat-card">
    <div class="stat-icon" aria-hidden="true">💾</div>
    <div class="stat-value" id="stat-size">0 B</div>
    <div class="stat-label">Total Size</div>
  </div>
  
  <div class="glass-card stat-card">
    <div class="stat-icon" aria-hidden="true">⏱</div>
    <div class="stat-value" id="stat-recent">—</div>
    <div class="stat-label">Recent</div>
  </div>
</section>

<!-- Main grid -->
<main class="main-grid">
  
  <!-- Drop zone -->
  <section class="glass-card drop-zone" id="drop-zone" role="button" tabindex="0" aria-label="Upload files">
    <input type="file" id="file-input" multiple hidden aria-label="File input">
    <div class="drop-content">
      <div class="drop-icon" aria-hidden="true">⬆️📁</div>
      <p class="drop-text">Drag files here</p>
      <p class="drop-subtext">or click to upload</p>
    </div>
  </section>
  
  <!-- File list -->
  <section class="glass-card file-section">
    <div class="file-header">
      <div class="search-container">
        <input type="search" id="search-input" class="search-input" placeholder="🔍 Search files..." aria-label="Search files">
        <button id="clear-search" class="clear-search" aria-label="Clear search">✕</button>
      </div>
      
      <div class="view-toggle-container">
        <button id="view-toggle" class="view-toggle" aria-label="Change view layout" aria-expanded="false">
          <span id="view-icon">▦</span>
          <span id="view-label">List</span>
          <span class="dropdown-arrow">▼</span>
        </button>
        <div id="view-menu" class="view-menu glass-card" role="menu" hidden>
          <button class="view-option" data-view="list" role="menuitem">List</button>
          <button class="view-option" data-view="detail" role="menuitem">Detail</button>
          <button class="view-option" data-view="cards" role="menuitem">Cards</button>
          <button class="view-option" data-view="compact" role="menuitem">Compact</button>
        </div>
      </div>
    </div>
    
    <div class="bulk-actions">
      <label class="select-all-container">
        <input type="checkbox" id="select-all">
        <span class="select-all-label">Select All</span>
      </label>
      
      <div class="bulk-buttons">
        <button id="bulk-download" class="btn btn-primary" disabled aria-label="Download selected files">
          ⬇ Download
        </button>
        <button id="bulk-delete" class="btn btn-danger" disabled aria-label="Delete selected files">
          🗑 Delete
        </button>
      </div>
    </div>
    
    <ul id="file-list" class="file-list" role="list" aria-live="polite" data-view="list">
      <!-- Files populated by JavaScript -->
    </ul>
  </section>
  
</main>

<!-- Upload queue (hidden by default) -->
<aside id="upload-queue" class="glass-card upload-queue" hidden aria-live="polite" aria-label="Upload progress">
  <h3 class="queue-title">Uploading...</h3>
  <div id="queue-items" class="queue-items">
    <!-- Upload items populated by JavaScript -->
  </div>
</aside>

<!-- QR Code section -->
<footer class="glass-card qr-section">
  <p class="qr-label">Scan to connect</p>
  <div id="qr-container" class="qr-container"></div>
</footer>

<!-- Toast notifications container -->
<div id="toast-container" class="toast-container" aria-live="polite"></div>

<!-- Context menu -->
<div id="context-menu" class="glass-card context-menu" hidden role="menu">
  <!-- Menu items populated by JavaScript -->
</div>

<!-- Preview overlay -->
<div id="preview-overlay" class="preview-overlay" hidden role="dialog" aria-modal="true">
  <button class="preview-close" aria-label="Close preview">✕</button>
  <img id="preview-image" class="preview-image" alt="Preview">
</div>

<script>
/* JavaScript will be added in later tasks */
</script>

</body>
</html>"""
```

- [ ] **Step 3: Run structure test**

```bash
python test_html_structure.py
```

Expected: All assertions pass, "✓ HTML structure contains all required elements"

- [ ] **Step 4: Verify server still runs**

```bash
python local_share.py
```

Open browser to `http://localhost:8080` - should see unstyled HTML structure.

- [ ] **Step 5: Commit HTML structure**

```bash
git add local_share.py
git commit -m "feat: add glassmorphism HTML structure

- Canvas background element
- Header with theme toggle
- Stats row with 3 cards
- Main grid: drop zone + file list
- File list with view toggle and bulk actions
- Upload queue, QR section, toast container
- Context menu and preview overlay
- Semantic HTML with ARIA labels

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: CSS Foundation - Variables & Reset

**Files:**
- Modify: `local_share.py:PAGE` (add CSS in `<style>` section)

**Interfaces:**
- Consumes: HTML structure from Task 2
- Produces: CSS custom properties for theming, base reset styles, theme switching via `[data-theme]`

- [ ] **Step 1: Add CSS variables for theming**

Replace `/* CSS will be added in next task */` with:

```css
/* ===== CSS Reset & Base ===== */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

:root {
  /* Font */
  --font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif;
  
  /* Spacing */
  --spacing-xs: 4px;
  --spacing-sm: 8px;
  --spacing-md: 16px;
  --spacing-lg: 24px;
  --spacing-xl: 32px;
  
  /* Border radius */
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  
  /* Transitions */
  --transition-theme: all 0.4s cubic-bezier(0.4, 0.0, 0.2, 1);
  --transition-fast: all 0.2s ease;
  --transition-quick: all 0.15s ease;
  
  /* Z-index layers */
  --z-background: 0;
  --z-content: 1;
  --z-dropdown: 100;
  --z-overlay: 500;
  --z-queue: 1000;
  --z-toast: 2000;
}

/* ===== Theme: Dark Mode (Default) ===== */
[data-theme="dark"] {
  --bg-gradient-start: #0a0a0a;
  --bg-gradient-end: #1a1a1a;
  --glass-overlay: rgba(255, 255, 255, 0.05);
  --glass-overlay-thick: rgba(255, 255, 255, 0.1);
  --glass-overlay-thin: rgba(255, 255, 255, 0.03);
  --glass-border: rgba(255, 255, 255, 0.1);
  --glass-blur: blur(20px);
  --glass-blur-strong: blur(30px);
  
  --dot-color: rgba(255, 255, 255, 0.15);
  --dot-glow: rgba(255, 255, 255, 0.4);
  
  --text-primary: #ffffff;
  --text-secondary: rgba(255, 255, 255, 0.6);
  --text-tertiary: rgba(255, 255, 255, 0.4);
  
  --accent: #6366f1;
  --accent-hover: #818cf8;
  --accent-rgb: 99, 102, 241;
  
  --success: #10b981;
  --danger: #ef4444;
  
  --shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.1);
  --shadow-hover: 0 12px 40px 0 rgba(0, 0, 0, 0.15);
}

/* ===== Theme: Light Mode ===== */
[data-theme="light"] {
  --bg-gradient-start: #ffffff;
  --bg-gradient-end: #f5f5f5;
  --glass-overlay: rgba(0, 0, 0, 0.03);
  --glass-overlay-thick: rgba(0, 0, 0, 0.08);
  --glass-overlay-thin: rgba(0, 0, 0, 0.02);
  --glass-border: rgba(0, 0, 0, 0.08);
  --glass-blur: blur(20px);
  --glass-blur-strong: blur(30px);
  
  --dot-color: rgba(0, 0, 0, 0.12);
  --dot-glow: rgba(0, 0, 0, 0.3);
  
  --text-primary: #0a0a0a;
  --text-secondary: rgba(0, 0, 0, 0.6);
  --text-tertiary: rgba(0, 0, 0, 0.4);
  
  --accent: #6366f1;
  --accent-hover: #4f46e5;
  --accent-rgb: 99, 102, 241;
  
  --success: #059669;
  --danger: #dc2626;
  
  --shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.05);
  --shadow-hover: 0 12px 40px 0 rgba(0, 0, 0, 0.08);
}

/* ===== Base Styles ===== */
html {
  font-size: 16px;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

body {
  font-family: var(--font-family);
  background: linear-gradient(135deg, var(--bg-gradient-start) 0%, var(--bg-gradient-end) 100%);
  color: var(--text-primary);
  min-height: 100vh;
  padding: var(--spacing-lg);
  position: relative;
  overflow-x: hidden;
  transition: var(--transition-theme);
}

/* Apply transitions to all themeable properties */
body,
.glass-card,
.btn,
input,
button,
.file-item,
.stat-card,
.context-menu,
.view-menu {
  transition: var(--transition-theme);
}

/* Reduced motion support */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 2: Test theme variables**

Create test:

```python
# test_css_variables.py
def test_css_variables():
    from local_share import PAGE
    
    # Check dark mode variables
    assert '--bg-gradient-start: #0a0a0a' in PAGE
    assert '[data-theme="dark"]' in PAGE
    
    # Check light mode variables
    assert '--bg-gradient-start: #ffffff' in PAGE
    assert '[data-theme="light"]' in PAGE
    
    # Check transition
    assert '0.4s cubic-bezier' in PAGE
    
    print("✓ CSS variables defined for both themes")

if __name__ == '__main__':
    test_css_variables()
```

- [ ] **Step 3: Run test**

```bash
python test_css_variables.py
```

Expected: "✓ CSS variables defined for both themes"

- [ ] **Step 4: Visual test in browser**

```bash
python local_share.py
```

Open browser, check:
- Dark background visible
- No console errors
- Text is white on dark background

- [ ] **Step 5: Commit CSS foundation**

```bash
git add local_share.py
git commit -m "feat: add CSS variables and theme system

- CSS custom properties for both themes
- Dark mode: black background, white text
- Light mode: white background, black text
- Seamless 0.4s theme transitions
- CSS reset and base styles
- Reduced motion support

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: CSS Components - Glass Cards & Layout Grid

**Files:**
- Modify: `local_share.py:PAGE` (add to CSS section)

**Interfaces:**
- Consumes: CSS variables from Task 3, HTML structure from Task 2
- Produces: `.glass-card` styles, responsive grid layout, header/stats/main-grid positioning

- [ ] **Step 1: Add glassmorphism card styles**

Add after base styles in `<style>`:

```css
/* ===== Glass Card Component ===== */
.glass-card {
  background: var(--glass-overlay);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
}

.glass-card-thick {
  background: var(--glass-overlay-thick);
}

.glass-card-thin {
  background: var(--glass-overlay-thin);
}

/* ===== Background Canvas ===== */
#bg-canvas {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  z-index: var(--z-background);
  pointer-events: none;
}

/* ===== Layout Container ===== */
body {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
  max-width: 1400px;
  margin: 0 auto;
}

/* ===== Header ===== */
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--spacing-md) var(--spacing-lg);
  position: relative;
  z-index: var(--z-content);
}

.logo {
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.theme-toggle {
  background: transparent;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  padding: var(--spacing-sm);
  border-radius: var(--radius-sm);
  transition: var(--transition-fast);
  color: var(--text-primary);
}

.theme-toggle:hover {
  background: var(--glass-overlay-thin);
  transform: scale(1.1);
}

.theme-toggle:focus {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* ===== Stats Row ===== */
.stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--spacing-md);
  position: relative;
  z-index: var(--z-content);
}

.stat-card {
  padding: var(--spacing-lg);
  text-align: center;
  transition: var(--transition-fast);
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-hover);
}

.stat-icon {
  font-size: 2rem;
  margin-bottom: var(--spacing-sm);
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--spacing-xs);
}

.stat-label {
  font-size: 0.875rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* ===== Main Grid ===== */
.main-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--spacing-lg);
  position: relative;
  z-index: var(--z-content);
}

/* Desktop: Two columns (40% / 60%) */
@media (min-width: 1024px) {
  .main-grid {
    grid-template-columns: 2fr 3fr;
  }
}

/* Tablet: Stack vertically */
@media (min-width: 768px) and (max-width: 1023px) {
  .main-grid {
    grid-template-columns: 1fr;
  }
}

/* Mobile: Stack vertically */
@media (max-width: 767px) {
  body {
    padding: var(--spacing-md);
    gap: var(--spacing-md);
  }
  
  .header {
    padding: var(--spacing-md);
  }
  
  .logo {
    font-size: 1.25rem;
  }
  
  .stats-row {
    grid-template-columns: 1fr;
    gap: var(--spacing-sm);
  }
  
  .stat-card {
    padding: var(--spacing-md);
  }
}
```

- [ ] **Step 2: Visual test in browser**

```bash
python local_share.py
```

Open browser and verify:
- Glass effect visible (frosted blur on cards)
- Header shows logo and theme button
- Stats row shows 3 cards in a row (desktop)
- Cards have hover effect (slight lift)
- Responsive on mobile (cards stack vertically)

- [ ] **Step 3: Test responsive breakpoints**

Resize browser window:
- Desktop (>1024px): Main grid shows 2 columns
- Tablet (768-1024px): Everything stacks
- Mobile (<768px): Reduced padding, single column

- [ ] **Step 4: Commit glass cards and layout**

```bash
git add local_share.py
git commit -m "feat: add glassmorphism cards and responsive grid

- Glass card component with backdrop blur
- Header with logo and theme toggle
- Stats row with 3 cards
- Responsive main grid (2-column desktop, stack mobile)
- Hover effects and transitions
- Responsive breakpoints for mobile/tablet/desktop

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: CSS Components - Drop Zone & File List

**Files:**
- Modify: `local_share.py:PAGE` (add to CSS section)

**Interfaces:**
- Consumes: Glass card styles from Task 4, HTML structure from Task 2
- Produces: `.drop-zone` styles, `.file-section` styles, `.file-list` layout modes, `.context-menu` positioning

- [ ] **Step 1: Add drop zone styles**

Add to CSS:

```css
/* ===== Drop Zone ===== */
.drop-zone {
  padding: var(--spacing-xl);
  border: 2px dashed var(--glass-border);
  border-radius: var(--radius-lg);
  text-align: center;
  cursor: pointer;
  transition: var(--transition-fast);
  min-height: 300px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.drop-zone:hover {
  border-color: var(--accent);
  background: var(--glass-overlay-thin);
  transform: scale(1.01);
}

.drop-zone:focus {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.drop-zone.dragover {
  border-color: var(--accent);
  border-style: solid;
  background: rgba(var(--accent-rgb), 0.1);
  transform: scale(1.02);
  box-shadow: 0 0 20px rgba(var(--accent-rgb), 0.3);
}

.drop-content {
  pointer-events: none;
}

.drop-icon {
  font-size: 3rem;
  margin-bottom: var(--spacing-md);
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.8; transform: scale(1.05); }
}

.drop-text {
  font-size: 1.25rem;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: var(--spacing-xs);
}

.drop-subtext {
  font-size: 0.875rem;
  color: var(--text-secondary);
}

/* ===== File Section ===== */
.file-section {
  padding: var(--spacing-lg);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  min-height: 400px;
}

.file-header {
  display: flex;
  gap: var(--spacing-md);
  flex-wrap: wrap;
}

.search-container {
  flex: 1;
  min-width: 200px;
  position: relative;
}

.search-input {
  width: 100%;
  padding: var(--spacing-sm) var(--spacing-md);
  padding-right: 40px;
  background: var(--glass-overlay-thin);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  font-size: 0.875rem;
  transition: var(--transition-fast);
}

.search-input:focus {
  outline: none;
  border-color: var(--accent);
  background: var(--glass-overlay);
}

.search-input::placeholder {
  color: var(--text-tertiary);
}

.clear-search {
  position: absolute;
  right: var(--spacing-sm);
  top: 50%;
  transform: translateY(-50%);
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: var(--spacing-xs);
  border-radius: var(--radius-sm);
  display: none;
}

.clear-search:hover {
  color: var(--text-primary);
  background: var(--glass-overlay-thin);
}

.view-toggle-container {
  position: relative;
}

.view-toggle {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  padding: var(--spacing-sm) var(--spacing-md);
  background: var(--glass-overlay-thin);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  cursor: pointer;
  transition: var(--transition-fast);
  font-size: 0.875rem;
}

.view-toggle:hover {
  background: var(--glass-overlay);
  border-color: var(--accent);
}

.view-menu {
  position: absolute;
  top: calc(100% + var(--spacing-xs));
  right: 0;
  min-width: 150px;
  padding: var(--spacing-xs);
  z-index: var(--z-dropdown);
}

.view-option {
  display: block;
  width: 100%;
  padding: var(--spacing-sm) var(--spacing-md);
  background: transparent;
  border: none;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: var(--transition-quick);
  font-size: 0.875rem;
}

.view-option:hover {
  background: var(--glass-overlay);
}

.view-option.active {
  background: rgba(var(--accent-rgb), 0.2);
  color: var(--accent);
}

/* ===== Bulk Actions ===== */
.bulk-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--spacing-md);
  flex-wrap: wrap;
}

.select-all-container {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  cursor: pointer;
}

.select-all-label {
  color: var(--text-secondary);
  font-size: 0.875rem;
  user-select: none;
}

input[type="checkbox"] {
  width: 18px;
  height: 18px;
  cursor: pointer;
  accent-color: var(--accent);
}

.bulk-buttons {
  display: flex;
  gap: var(--spacing-sm);
}

.btn {
  padding: var(--spacing-sm) var(--spacing-md);
  border-radius: var(--radius-md);
  border: none;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: var(--transition-fast);
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-xs);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--accent);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-hover);
  transform: scale(1.05);
}

.btn-danger {
  background: var(--danger);
  color: white;
}

.btn-danger:hover:not(:disabled) {
  filter: brightness(1.1);
  transform: scale(1.05);
}

/* ===== File List ===== */
.file-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  overflow-y: auto;
  max-height: 600px;
  padding-right: var(--spacing-xs);
}

/* Scrollbar styling */
.file-list::-webkit-scrollbar {
  width: 6px;
}

.file-list::-webkit-scrollbar-track {
  background: var(--glass-overlay-thin);
  border-radius: 3px;
}

.file-list::-webkit-scrollbar-thumb {
  background: var(--glass-overlay-thick);
  border-radius: 3px;
}

.file-list::-webkit-scrollbar-thumb:hover {
  background: var(--glass-border);
}

/* Empty state */
.file-list-empty {
  text-align: center;
  padding: var(--spacing-xl);
  color: var(--text-secondary);
  font-size: 0.875rem;
}

/* ===== File List: List View (Default) ===== */
.file-list[data-view="list"] .file-item {
  display: grid;
  grid-template-columns: auto auto 1fr auto;
  gap: var(--spacing-md);
  align-items: center;
  padding: var(--spacing-md);
  background: var(--glass-overlay-thin);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  transition: var(--transition-fast);
}

.file-list[data-view="list"] .file-item:hover {
  background: var(--glass-overlay);
  transform: translateX(4px);
}

.file-list[data-view="list"] .file-item.selected {
  background: rgba(var(--accent-rgb), 0.1);
  border-color: var(--accent);
}

.file-list[data-view="list"] .file-icon {
  font-size: 1.5rem;
}

.file-list[data-view="list"] .file-info {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  min-width: 0;
}

.file-list[data-view="list"] .file-name {
  color: var(--text-primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-list[data-view="list"] .file-meta {
  color: var(--text-secondary);
  font-size: 0.75rem;
  display: flex;
  gap: var(--spacing-xs);
}

/* ===== File List: Detail View ===== */
.file-list[data-view="detail"] .file-item {
  display: grid;
  grid-template-columns: auto auto 1fr auto;
  gap: var(--spacing-lg);
  align-items: center;
  padding: var(--spacing-lg);
  background: var(--glass-overlay-thin);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  transition: var(--transition-fast);
}

.file-list[data-view="detail"] .file-item:hover {
  background: var(--glass-overlay);
  transform: translateX(4px);
}

.file-list[data-view="detail"] .file-item.selected {
  background: rgba(var(--accent-rgb), 0.1);
  border-color: var(--accent);
}

.file-list[data-view="detail"] .file-icon {
  font-size: 2rem;
}

.file-list[data-view="detail"] .file-info {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.file-list[data-view="detail"] .file-name {
  color: var(--text-primary);
  font-weight: 500;
  font-size: 1rem;
}

.file-list[data-view="detail"] .file-meta {
  color: var(--text-secondary);
  font-size: 0.875rem;
}

.file-list[data-view="detail"] .file-type {
  color: var(--text-tertiary);
  font-size: 0.75rem;
}

/* ===== File List: Cards View ===== */
.file-list[data-view="cards"] {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: var(--spacing-md);
}

.file-list[data-view="cards"] .file-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--spacing-md);
  background: var(--glass-overlay-thin);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  transition: var(--transition-fast);
  text-align: center;
  position: relative;
}

.file-list[data-view="cards"] .file-item:hover {
  background: var(--glass-overlay);
  transform: translateY(-2px);
  box-shadow: var(--shadow-hover);
}

.file-list[data-view="cards"] .file-item.selected {
  background: rgba(var(--accent-rgb), 0.1);
  border-color: var(--accent);
}

.file-list[data-view="cards"] .file-checkbox {
  position: absolute;
  top: var(--spacing-sm);
  left: var(--spacing-sm);
}

.file-list[data-view="cards"] .file-menu-btn {
  position: absolute;
  top: var(--spacing-sm);
  right: var(--spacing-sm);
}

.file-list[data-view="cards"] .file-icon {
  font-size: 3rem;
  margin: var(--spacing-md) 0;
}

.file-list[data-view="cards"] .file-name {
  color: var(--text-primary);
  font-size: 0.875rem;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  width: 100%;
}

.file-list[data-view="cards"] .file-size {
  color: var(--text-secondary);
  font-size: 0.75rem;
  margin-top: var(--spacing-xs);
}

/* ===== File List: Compact View ===== */
.file-list[data-view="compact"] .file-item {
  display: grid;
  grid-template-columns: auto auto 1fr auto auto auto;
  gap: var(--spacing-sm);
  align-items: center;
  padding: var(--spacing-sm) var(--spacing-md);
  background: var(--glass-overlay-thin);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  transition: var(--transition-fast);
}

.file-list[data-view="compact"] .file-item:hover {
  background: var(--glass-overlay);
}

.file-list[data-view="compact"] .file-item.selected {
  background: rgba(var(--accent-rgb), 0.1);
  border-color: var(--accent);
}

.file-list[data-view="compact"] .file-icon {
  font-size: 1.25rem;
}

.file-list[data-view="compact"] .file-name {
  color: var(--text-primary);
  font-size: 0.875rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-list[data-view="compact"] .file-size,
.file-list[data-view="compact"] .file-time {
  color: var(--text-secondary);
  font-size: 0.75rem;
}

/* ===== File Actions Menu Button ===== */
.file-menu-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: var(--spacing-xs);
  border-radius: var(--radius-sm);
  font-size: 1.25rem;
  line-height: 1;
  transition: var(--transition-quick);
}

.file-menu-btn:hover {
  background: var(--glass-overlay);
  color: var(--text-primary);
}

/* ===== Context Menu ===== */
.context-menu {
  position: fixed;
  min-width: 180px;
  padding: var(--spacing-xs);
  z-index: var(--z-dropdown);
  backdrop-filter: var(--glass-blur-strong);
  -webkit-backdrop-filter: var(--glass-blur-strong);
}

.context-menu-item {
  display: block;
  width: 100%;
  padding: var(--spacing-sm) var(--spacing-md);
  background: transparent;
  border: none;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: var(--transition-quick);
  font-size: 0.875rem;
}

.context-menu-item:hover {
  background: var(--glass-overlay);
}

.context-menu-item.danger {
  color: var(--danger);
}

.context-menu-item.danger:hover {
  background: rgba(239, 68, 68, 0.1);
}
```

- [ ] **Step 2: Visual test file list layouts**

```bash
python local_share.py
```

Open browser dev tools console and test view switching:
```javascript
document.getElementById('file-list').setAttribute('data-view', 'list');
document.getElementById('file-list').setAttribute('data-view', 'detail');
document.getElementById('file-list').setAttribute('data-view', 'cards');
document.getElementById('file-list').setAttribute('data-view', 'compact');
```

Verify layout changes with each view mode.

- [ ] **Step 3: Test responsive drop zone**

Resize browser:
- Desktop: Drop zone in left column
- Mobile: Drop zone full width, stacks above file list

- [ ] **Step 4: Commit drop zone and file list styles**

```bash
git add local_share.py
git commit -m "feat: add drop zone and file list component styles

- Drop zone with dashed border and hover effects
- Drag-over state with glow
- File section header with search and view toggle
- Bulk actions bar with select all and buttons
- Four file list view modes: list, detail, cards, compact
- Context menu positioning
- Responsive grid for cards view
- Custom scrollbar styling

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: CSS Components - Upload Queue, Toast, Preview

**Files:**
- Modify: `local_share.py:PAGE` (add to CSS section)

**Interfaces:**
- Consumes: Glass card styles from Task 4
- Produces: `.upload-queue` floating panel, `.toast-container` notifications, `.preview-overlay` modal, `.qr-section` footer

- [ ] **Step 1: Add remaining component styles**

Add to CSS:

```css
/* ===== Upload Queue ===== */
.upload-queue {
  position: fixed;
  bottom: var(--spacing-lg);
  right: var(--spacing-lg);
  width: 400px;
  max-width: calc(100vw - var(--spacing-lg) * 2);
  padding: var(--spacing-md);
  z-index: var(--z-queue);
  backdrop-filter: var(--glass-blur-strong);
  -webkit-backdrop-filter: var(--glass-blur-strong);
  max-height: 50vh;
  overflow-y: auto;
}

.queue-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--spacing-md);
}

.queue-items {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.queue-item {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.queue-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.queue-name {
  color: var(--text-primary);
  font-size: 0.875rem;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.queue-size {
  color: var(--text-secondary);
  font-size: 0.75rem;
}

.queue-progress {
  width: 100%;
  height: 4px;
  background: var(--glass-overlay);
  border-radius: 2px;
  overflow: hidden;
}

.queue-progress-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--accent) 0%, var(--accent-hover) 100%);
  border-radius: 2px;
  transition: width 0.3s ease;
  position: relative;
  overflow: hidden;
}

.queue-progress-bar::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  right: 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.3) 50%,
    transparent 100%
  );
  animation: shimmer 1.5s infinite;
}

@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

.queue-speed {
  color: var(--text-secondary);
  font-size: 0.75rem;
}

@media (max-width: 767px) {
  .upload-queue {
    bottom: var(--spacing-md);
    right: var(--spacing-md);
    left: var(--spacing-md);
    width: auto;
  }
}

/* ===== Toast Notifications ===== */
.toast-container {
  position: fixed;
  top: var(--spacing-lg);
  left: 50%;
  transform: translateX(-50%);
  z-index: var(--z-toast);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  pointer-events: none;
}

.toast {
  padding: var(--spacing-md) var(--spacing-lg);
  background: var(--glass-overlay-thick);
  backdrop-filter: var(--glass-blur-strong);
  -webkit-backdrop-filter: var(--glass-blur-strong);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  font-size: 0.875rem;
  box-shadow: var(--shadow-hover);
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  animation: toast-in 0.3s ease;
  pointer-events: auto;
}

.toast.success {
  border-left: 3px solid var(--success);
}

.toast.error {
  border-left: 3px solid var(--danger);
}

.toast.info {
  border-left: 3px solid var(--accent);
}

@keyframes toast-in {
  from {
    opacity: 0;
    transform: translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.toast.fade-out {
  animation: toast-out 0.3s ease forwards;
}

@keyframes toast-out {
  from {
    opacity: 1;
    transform: translateY(0);
  }
  to {
    opacity: 0;
    transform: translateY(-20px);
  }
}

/* ===== Preview Overlay ===== */
.preview-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.9);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  z-index: var(--z-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--spacing-lg);
  animation: fade-in 0.3s ease;
}

@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.preview-close {
  position: absolute;
  top: var(--spacing-lg);
  right: var(--spacing-lg);
  background: var(--glass-overlay-thick);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: 50%;
  width: 40px;
  height: 40px;
  color: white;
  font-size: 1.5rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: var(--transition-fast);
}

.preview-close:hover {
  background: var(--glass-overlay);
  transform: scale(1.1);
}

.preview-image {
  max-width: 90vw;
  max-height: 90vh;
  object-fit: contain;
  border-radius: var(--radius-md);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
}

/* ===== QR Section ===== */
.qr-section {
  padding: var(--spacing-lg);
  text-align: center;
  margin-top: auto;
}

.qr-label {
  color: var(--text-secondary);
  font-size: 0.875rem;
  margin-bottom: var(--spacing-md);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.qr-container {
  display: inline-block;
  padding: var(--spacing-md);
  background: white;
  border-radius: var(--radius-md);
}

.qr-container canvas {
  display: block;
  max-width: 200px;
  height: auto;
  aspect-ratio: 1;
}

@media (max-width: 767px) {
  .qr-container canvas {
    max-width: 150px;
  }
}

/* ===== Utility Classes ===== */
.hidden {
  display: none !important;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}

/* ===== Focus Styles ===== */
button:focus-visible,
input:focus-visible,
[tabindex]:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* ===== Selection Styles ===== */
::selection {
  background: rgba(var(--accent-rgb), 0.3);
  color: var(--text-primary);
}
```

- [ ] **Step 2: Visual test components**

```bash
python local_share.py
```

Test in browser console:
```javascript
// Show upload queue
document.getElementById('upload-queue').removeAttribute('hidden');

// Show toast
const toast = document.createElement('div');
toast.className = 'toast success';
toast.textContent = '✓ Test toast';
document.getElementById('toast-container').appendChild(toast);

// Show preview overlay
document.getElementById('preview-overlay').removeAttribute('hidden');
```

Verify:
- Upload queue appears bottom-right
- Toast appears top-center
- Preview overlay covers full screen
- QR section at bottom with white background

- [ ] **Step 3: Test mobile responsiveness**

Resize to mobile width:
- Upload queue spans full width (with padding)
- QR code shrinks to 150px
- All components remain accessible

- [ ] **Step 4: Commit remaining components**

```bash
git add local_share.py
git commit -m "feat: add upload queue, toast, and preview overlays

- Upload queue floating panel with progress bars
- Shimmer animation on progress bars
- Toast notification system with fade animations
- Full-screen preview overlay with blur backdrop
- QR code section with white background
- Mobile-responsive adjustments
- Focus and selection styles

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: JavaScript - Canvas Background Animation

**Files:**
- Modify: `local_share.py:PAGE` (add JavaScript in `<script>` section)

**Interfaces:**
- Consumes: Canvas element from Task 2, CSS variables from Task 3
- Produces: `initBackground()` function, isometric dot grid animation, theme-aware colors

- [ ] **Step 1: Write test for canvas animation**

Create test file:

```javascript
// test_canvas.js (for browser console)
function testCanvasAnimation() {
  const canvas = document.getElementById('bg-canvas');
  if (!canvas) return console.error('Canvas not found');
  
  const ctx = canvas.getContext('2d');
  if (!ctx) return console.error('Canvas context not found');
  
  console.log('✓ Canvas element exists');
  console.log('✓ Canvas dimensions:', canvas.width, 'x', canvas.height);
  console.log('✓ Canvas context ready');
  
  // Check if animation is running
  setTimeout(() => {
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const hasContent = imageData.data.some(val => val > 0);
    console.log(hasContent ? '✓ Canvas has content (animation running)' : '✗ Canvas empty');
  }, 100);
}
```

- [ ] **Step 2: Add canvas background animation**

Replace `/* JavaScript will be added in later tasks */` with:

```javascript
'use strict';

// ===== Canvas Background Animation =====
(function() {
  const canvas = document.getElementById('bg-canvas');
  const ctx = canvas.getContext('2d');
  
  let dots = [];
  let animationId = null;
  let rotation = 0;
  
  // Isometric projection (60° angles)
  const ISO_ANGLE = Math.PI / 3; // 60 degrees
  const COS_ISO = Math.cos(ISO_ANGLE);
  const SIN_ISO = Math.sin(ISO_ANGLE);
  
  function toIsometric(x, y) {
    return {
      x: (x - y) * COS_ISO,
      y: (x + y) * SIN_ISO * 0.5
    };
  }
  
  function resizeCanvas() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    initDots();
  }
  
  function initDots() {
    dots = [];
    
    // Responsive grid spacing
    const spacing = window.innerWidth < 768 ? 60 : 
                    window.innerWidth < 1024 ? 50 : 40;
    
    // Calculate grid bounds
    const cols = Math.ceil(canvas.width / spacing) + 2;
    const rows = Math.ceil(canvas.height / spacing) + 2;
    
    // Create isometric grid of dots
    for (let row = -1; row < rows; row++) {
      for (let col = -1; col < cols; col++) {
        const x = col * spacing;
        const y = row * spacing;
        
        dots.push({
          x,
          y,
          baseOpacity: 0.15 + Math.random() * 0.25,
          flickerSpeed: 0.5 + Math.random() * 1.5,
          flickerOffset: Math.random() * Math.PI * 2,
          radius: 2
        });
      }
    }
  }
  
  function getThemeColors() {
    const theme = document.body.getAttribute('data-theme');
    if (theme === 'light') {
      return {
        base: 'rgba(0, 0, 0, ',
        glow: 0.3
      };
    }
    return {
      base: 'rgba(255, 255, 255, ',
      glow: 0.4
    };
  }
  
  function animate() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    const time = Date.now() / 1000;
    rotation += 0.0001; // Slow drift
    
    const colors = getThemeColors();
    
    // Draw dots
    dots.forEach(dot => {
      // Calculate isometric position with rotation
      const iso = toIsometric(
        dot.x + Math.cos(rotation) * 10,
        dot.y + Math.sin(rotation) * 10
      );
      
      const screenX = canvas.width / 2 + iso.x;
      const screenY = canvas.height / 2 + iso.y;
      
      // Skip dots outside viewport
      if (screenX < -10 || screenX > canvas.width + 10 ||
          screenY < -10 || screenY > canvas.height + 10) {
        return;
      }
      
      // Calculate flickering opacity
      const flicker = Math.sin(time * dot.flickerSpeed + dot.flickerOffset);
      const opacity = dot.baseOpacity + (flicker * 0.1);
      
      // Draw dot
      ctx.fillStyle = colors.base + opacity + ')';
      ctx.beginPath();
      ctx.arc(screenX, screenY, dot.radius, 0, Math.PI * 2);
      ctx.fill();
      
      // Add subtle glow
      const glowOpacity = opacity * colors.glow;
      ctx.fillStyle = colors.base + glowOpacity + ')';
      ctx.beginPath();
      ctx.arc(screenX, screenY, dot.radius + 1, 0, Math.PI * 2);
      ctx.fill();
    });
    
    animationId = requestAnimationFrame(animate);
  }
  
  function startAnimation() {
    if (!animationId) {
      animate();
    }
  }
  
  function stopAnimation() {
    if (animationId) {
      cancelAnimationFrame(animationId);
      animationId = null;
    }
  }
  
  // Initialize
  resizeCanvas();
  startAnimation();
  
  // Handle resize
  let resizeTimeout;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(resizeCanvas, 250);
  });
  
  // Pause animation when page hidden (performance)
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopAnimation();
    } else {
      startAnimation();
    }
  });
  
  // Re-render on theme change (color update)
  window.addEventListener('themechange', () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  });
})();
```

- [ ] **Step 3: Test canvas animation**

```bash
python local_share.py
```

Open browser and verify:
- Isometric dot grid visible
- Dots glow and flicker
- Slow drift/rotation animation
- Dots are white on dark theme
- Animation runs at 60fps (check performance tab)

Open console and run:
```javascript
testCanvasAnimation();
```

- [ ] **Step 4: Test theme switching (preparation)**

In console:
```javascript
document.body.setAttribute('data-theme', 'light');
window.dispatchEvent(new Event('themechange'));
```

Verify dots change to dark gray on white background.

- [ ] **Step 5: Commit canvas animation**

```bash
git add local_share.py
git commit -m "feat: add animated isometric dot grid background

- Canvas-based background with isometric projection
- Dots arranged at 60° angles
- Slow rotation/drift animation
- Flicker effect with varying opacity
- Theme-aware colors (white/dark gray)
- Responsive grid spacing (mobile/tablet/desktop)
- Pause animation when tab hidden
- 60fps performance

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: JavaScript - Theme Toggle System

**Files:**
- Modify: `local_share.py:PAGE` (add to JavaScript section)

**Interfaces:**
- Consumes: Theme toggle button from Task 2, CSS variables from Task 3, canvas animation from Task 7
- Produces: `applyTheme(theme)` function, `toggleTheme()` handler, localStorage persistence, seamless transitions

- [ ] **Step 1: Add theme toggle functionality**

Add after canvas animation code:

```javascript
// ===== Theme Toggle System =====
(function() {
  const themeToggle = document.getElementById('theme-toggle');
  const themeIcon = document.getElementById('theme-icon');
  
  function applyTheme(theme) {
    document.body.setAttribute('data-theme', theme);
    themeIcon.textContent = theme === 'light' ? '☀' : '🌙';
    localStorage.setItem('theme', theme);
    
    // Notify canvas to update colors
    window.dispatchEvent(new Event('themechange'));
  }
  
  function toggleTheme() {
    const currentTheme = document.body.getAttribute('data-theme') || 'dark';
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    applyTheme(newTheme);
  }
  
  // Initialize theme from localStorage or default to dark
  const savedTheme = localStorage.getItem('theme') || 'dark';
  applyTheme(savedTheme);
  
  // Attach toggle handler
  themeToggle.addEventListener('click', toggleTheme);
  
  // Keyboard shortcut: Ctrl/Cmd + T
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 't') {
      e.preventDefault();
      toggleTheme();
    }
  });
})();
```

- [ ] **Step 2: Write test for theme toggle**

In browser console:

```javascript
function testThemeToggle() {
  const initialTheme = document.body.getAttribute('data-theme');
  console.log('✓ Initial theme:', initialTheme);
  
  // Toggle theme
  document.getElementById('theme-toggle').click();
  const newTheme = document.body.getAttribute('data-theme');
  console.log('✓ New theme after toggle:', newTheme);
  
  // Check localStorage
  const savedTheme = localStorage.getItem('theme');
  console.log('✓ Theme saved to localStorage:', savedTheme);
  
  // Check icon changed
  const icon = document.getElementById('theme-icon').textContent;
  console.log('✓ Theme icon:', icon);
  
  // Verify themes are different
  console.log(initialTheme !== newTheme ? '✓ Toggle works' : '✗ Toggle failed');
}
```

- [ ] **Step 3: Test theme toggle**

```bash
python local_share.py
```

Open browser:
1. Click theme toggle button
2. Verify smooth transition (0.4s)
3. Verify background changes (dark ↔ light)
4. Verify dot colors change (white ↔ dark gray)
5. Verify icon changes (🌙 ↔ ☀)
6. Refresh page - theme should persist

Run test in console:
```javascript
testThemeToggle();
```

- [ ] **Step 4: Test keyboard shortcut**

Press `Ctrl+T` (or `Cmd+T` on Mac) - theme should toggle.

- [ ] **Step 5: Commit theme toggle**

```bash
git add local_share.py
git commit -m "feat: add theme toggle system with seamless transitions

- Theme toggle button handler
- localStorage persistence
- Smooth 0.4s cubic-bezier transitions
- Icon morphing (sun ↔ moon)
- Keyboard shortcut (Ctrl/Cmd+T)
- Theme change event for canvas update
- Initializes from saved preference

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: JavaScript - File Management Core

**Files:**
- Modify: `local_share.py:PAGE` (add to JavaScript section)

**Interfaces:**
- Consumes: `/api/files` endpoint (existing), HTML structure from Task 2
- Produces: `loadFiles()`, `renderFiles(files)`, `updateStats()`, `state` object for app state

- [ ] **Step 1: Add file management state and core functions**

Add after theme toggle code:

```javascript
// ===== Application State =====
const state = {
  allFiles: [],
  selectedFiles: new Set(),
  searchQuery: '',
  currentView: localStorage.getItem('fileView') || 'list',
  autoRefreshInterval: null
};

// ===== Utility Functions =====
function formatSize(bytes) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = bytes;
  let unitIndex = 0;
  
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex++;
  }
  
  return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function formatTime(dateString) {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  
  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  
  return date.toLocaleDateString();
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  
  const icon = type === 'success' ? '✓' : 
               type === 'error' ? '✗' : 
               type === 'info' ? 'ⓘ' : '';
  
  toast.textContent = `${icon} ${message}`;
  container.appendChild(toast);
  
  setTimeout(() => {
    toast.classList.add('fade-out');
    setTimeout(() => toast.remove(), 300);
  }, 2000);
}

// ===== File Management =====
async function loadFiles(preserveSelection = false) {
  try {
    const response = await fetch('/api/files');
    if (!response.ok) throw new Error('Failed to load files');
    
    state.allFiles = await response.json();
    
    // Preserve selection or clear
    if (!preserveSelection) {
      state.selectedFiles.clear();
    } else {
      // Remove selections for files that no longer exist
      const fileNames = new Set(state.allFiles.map(f => f.name));
      state.selectedFiles.forEach(name => {
        if (!fileNames.has(name)) {
          state.selectedFiles.delete(name);
        }
      });
    }
    
    updateStats();
    filterAndRenderFiles();
    updateBulkActions();
  } catch (error) {
    console.error('Load files error:', error);
    showToast('Failed to load files', 'error');
  }
}

function updateStats() {
  const fileCount = state.allFiles.length;
  const totalSize = state.allFiles.reduce((sum, f) => sum + f.size, 0);
  
  document.getElementById('stat-files').textContent = fileCount;
  document.getElementById('stat-size').textContent = formatSize(totalSize);
  
  if (fileCount > 0) {
    const recent = state.allFiles[0]; // Assuming sorted by most recent
    document.getElementById('stat-recent').textContent = formatTime(recent.modified);
  } else {
    document.getElementById('stat-recent').textContent = '—';
  }
}

function filterAndRenderFiles() {
  const query = state.searchQuery.toLowerCase();
  const filtered = query ? 
    state.allFiles.filter(f => f.name.toLowerCase().includes(query)) :
    state.allFiles;
  
  renderFiles(filtered);
}

function renderFiles(files) {
  const fileList = document.getElementById('file-list');
  fileList.innerHTML = '';
  
  if (files.length === 0) {
    const empty = document.createElement('li');
    empty.className = 'file-list-empty';
    empty.textContent = state.searchQuery ? 
      'No files match your search' : 
      'No files have been shared yet';
    fileList.appendChild(empty);
    return;
  }
  
  files.forEach(file => {
    const item = createFileItem(file);
    fileList.appendChild(item);
  });
  
  updateSelectAllCheckbox();
}

function createFileItem(file) {
  const li = document.createElement('li');
  li.className = 'file-item';
  if (state.selectedFiles.has(file.name)) {
    li.classList.add('selected');
  }
  li.dataset.name = file.name;
  
  // Checkbox
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.className = 'file-checkbox';
  checkbox.checked = state.selectedFiles.has(file.name);
  checkbox.addEventListener('change', () => toggleFileSelection(file.name));
  
  // Icon
  const icon = document.createElement('span');
  icon.className = 'file-icon';
  icon.textContent = file.icon || '📄';
  icon.setAttribute('aria-hidden', 'true');
  
  // Info container
  const info = document.createElement('div');
  info.className = 'file-info';
  
  const name = document.createElement('div');
  name.className = 'file-name';
  name.textContent = file.name;
  
  const meta = document.createElement('div');
  meta.className = 'file-meta';
  
  // View-specific metadata
  if (state.currentView === 'detail') {
    const metaLine2 = document.createElement('div');
    metaLine2.textContent = `${formatSize(file.size)} • Modified ${formatTime(file.modified)}`;
    meta.appendChild(metaLine2);
    
    const metaLine3 = document.createElement('div');
    metaLine3.className = 'file-type';
    metaLine3.textContent = getFileType(file.name);
    meta.appendChild(metaLine3);
  } else if (state.currentView === 'compact') {
    // Compact: separate size and time elements
    const size = document.createElement('span');
    size.className = 'file-size';
    size.textContent = formatSize(file.size);
    
    const time = document.createElement('span');
    time.className = 'file-time';
    time.textContent = formatTime(file.modified);
    
    meta.appendChild(size);
    meta.appendChild(time);
  } else {
    // List/Cards view
    meta.textContent = `${formatSize(file.size)} • ${formatTime(file.modified)}`;
  }
  
  info.appendChild(name);
  info.appendChild(meta);
  
  // Menu button
  const menuBtn = document.createElement('button');
  menuBtn.className = 'file-menu-btn';
  menuBtn.textContent = '⋮';
  menuBtn.setAttribute('aria-label', 'File actions');
  menuBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    showContextMenu(e, file);
  });
  
  // Assemble based on view
  if (state.currentView === 'cards') {
    li.appendChild(checkbox);
    li.appendChild(menuBtn);
    li.appendChild(icon);
    li.appendChild(name);
    
    const size = document.createElement('div');
    size.className = 'file-size';
    size.textContent = formatSize(file.size);
    li.appendChild(size);
  } else {
    li.appendChild(checkbox);
    li.appendChild(icon);
    li.appendChild(info);
    li.appendChild(menuBtn);
  }
  
  // Right-click context menu
  li.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    showContextMenu(e, file);
  });
  
  return li;
}

function getFileType(filename) {
  const ext = filename.split('.').pop().toLowerCase();
  const types = {
    pdf: 'PDF Document',
    doc: 'Word Document',
    docx: 'Word Document',
    xls: 'Excel Spreadsheet',
    xlsx: 'Excel Spreadsheet',
    png: 'PNG Image',
    jpg: 'JPEG Image',
    jpeg: 'JPEG Image',
    gif: 'GIF Image',
    mp4: 'MP4 Video',
    mp3: 'MP3 Audio',
    zip: 'ZIP Archive',
    txt: 'Text File',
  };
  return types[ext] || 'File';
}

function toggleFileSelection(filename) {
  if (state.selectedFiles.has(filename)) {
    state.selectedFiles.delete(filename);
  } else {
    state.selectedFiles.add(filename);
  }
  
  // Update UI
  const item = document.querySelector(`[data-name="${CSS.escape(filename)}"]`);
  if (item) {
    item.classList.toggle('selected', state.selectedFiles.has(filename));
    const checkbox = item.querySelector('.file-checkbox');
    if (checkbox) checkbox.checked = state.selectedFiles.has(filename);
  }
  
  updateSelectAllCheckbox();
  updateBulkActions();
}

function updateSelectAllCheckbox() {
  const selectAllCheckbox = document.getElementById('select-all');
  const visibleFiles = document.querySelectorAll('.file-item:not(.file-list-empty)').length;
  
  if (visibleFiles === 0) {
    selectAllCheckbox.checked = false;
    selectAllCheckbox.indeterminate = false;
  } else if (state.selectedFiles.size === 0) {
    selectAllCheckbox.checked = false;
    selectAllCheckbox.indeterminate = false;
  } else if (state.selectedFiles.size === visibleFiles) {
    selectAllCheckbox.checked = true;
    selectAllCheckbox.indeterminate = false;
  } else {
    selectAllCheckbox.checked = false;
    selectAllCheckbox.indeterminate = true;
  }
}

function updateBulkActions() {
  const hasSelection = state.selectedFiles.size > 0;
  document.getElementById('bulk-download').disabled = !hasSelection;
  document.getElementById('bulk-delete').disabled = !hasSelection;
}
```

- [ ] **Step 2: Test file loading**

```bash
python local_share.py
```

Open browser console:
```javascript
// Test file loading
await loadFiles();
console.log('Files loaded:', state.allFiles.length);

// Test stats update
console.log('File count:', document.getElementById('stat-files').textContent);
console.log('Total size:', document.getElementById('stat-size').textContent);

// Test selection
toggleFileSelection(state.allFiles[0].name);
console.log('Selected files:', state.selectedFiles.size);
```

- [ ] **Step 3: Visual verification**

Upload a test file, verify:
- File appears in list
- Stats update correctly
- Checkbox selection works
- File item has proper styling based on view mode

- [ ] **Step 4: Commit file management core**

```bash
git add local_share.py
git commit -m "feat: add file management core functionality

- Application state management
- Load files from API endpoint
- Update stats (count, size, recent)
- Render files in current view mode
- File selection toggle
- Format utilities (size, time)
- Toast notification system
- Select all checkbox with indeterminate state
- Bulk action button state management

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: JavaScript - Search, View Toggle, Context Menu & Preview

**Files:**
- Modify: `local_share.py:PAGE` (add to JavaScript section)

**Interfaces:**
- Consumes: State from Task 9, HTML elements from Task 2
- Produces: Search filtering, view layout switching, context menu with actions, image preview overlay

- [ ] **Step 1: Add search functionality**

Add after file management code:

```javascript
// ===== Search & View Controls =====
(function() {
  const searchInput = document.getElementById('search-input');
  const clearSearchBtn = document.getElementById('clear-search');
  const viewToggleBtn = document.getElementById('view-toggle');
  const viewMenu = document.getElementById('view-menu');
  const viewOptions = document.querySelectorAll('.view-option');
  const fileList = document.getElementById('file-list');
  
  // Search
  searchInput.addEventListener('input', (e) => {
    state.searchQuery = e.target.value;
    clearSearchBtn.style.display = state.searchQuery ? 'block' : 'none';
    filterAndRenderFiles();
  });
  
  clearSearchBtn.addEventListener('click', () => {
    state.searchQuery = '';
    searchInput.value = '';
    clearSearchBtn.style.display = 'none';
    filterAndRenderFiles();
    showToast('Search cleared');
  });
  
  // View toggle
  viewToggleBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    viewMenu.hidden = !viewMenu.hidden;
  });
  
  viewOptions.forEach(option => {
    option.addEventListener('click', (e) => {
      e.preventDefault();
      const view = option.dataset.view;
      state.currentView = view;
      localStorage.setItem('fileView', view);
      
      // Update UI
      viewOptions.forEach(o => o.classList.remove('active'));
      option.classList.add('active');
      document.getElementById('view-label').textContent = 
        view.charAt(0).toUpperCase() + view.slice(1);
      
      // Hide menu
      viewMenu.hidden = true;
      
      // Re-render with new view
      filterAndRenderFiles();
    });
  });
  
  // Close menus when clicking outside
  document.addEventListener('click', (e) => {
    if (!viewToggleBtn.contains(e.target)) {
      viewMenu.hidden = true;
    }
    if (!contextMenu.contains(e.target)) {
      contextMenu.hidden = true;
    }
  });
  
  // Escape key closes menus
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      viewMenu.hidden = true;
      contextMenu.hidden = true;
      previewOverlay.hidden = true;
    }
  });
})();
```

- [ ] **Step 2: Add context menu functionality**

Add after search/view controls:

```javascript
// ===== Context Menu & Preview =====
(function() {
  const contextMenu = document.getElementById('context-menu');
  const previewOverlay = document.getElementById('preview-overlay');
  const previewClose = document.getElementById('preview-close');
  const previewImage = document.getElementById('preview-image');
  
  let contextFile = null; // Currently selected file for context menu
  
  function showContextMenu(event, file) {
    event.preventDefault();
    contextFile = file;
    
    // Position menu at cursor
    contextMenu.style.left = `${event.pageX}px`;
    contextMenu.style.top = `${event.pageY}px`;
    contextMenu.hidden = false;
    
    // Focus for keyboard accessibility
    contextMenu.focus();
  }
  
  function hideContextMenu() {
    contextMenu.hidden = true;
    contextFile = null;
  }
  
  // Context menu items
  contextMenu.innerHTML = `
    <button class="context-menu-item" data-action="download">⬇ Download</button>
    <button class="context-menu-item" data-action="copy">📋 Copy Link</button>
    <button class="context-menu-item" data-action="preview">👁 Preview</button>
    <button class="context-menu-item danger" data-action="delete">🗑 Delete</button>
  `;
  
  contextMenu.querySelectorAll('.context-menu-item').forEach(item => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      const action = e.currentTarget.dataset.action;
      
      hideContextMenu();
      
      if (!contextFile) return;
      
      switch (action) {
        case 'download':
          downloadFile(contextFile.name);
          break;
        case 'copy':
          copyLink(contextFile.name);
          break;
        case 'preview':
          if (contextFile.image) {
            showPreview('/preview/' + encodeURIComponent(contextFile.name));
          } else {
            showToast('Preview not available for this file type', 'info');
          }
          break;
        case 'delete':
          if (confirm(`Delete ${contextFile.name}?`)) {
            deleteFile(contextFile.name);
          }
          break;
      }
    });
  });
  
  // Preview overlay
  previewClose.addEventListener('click', () => {
    previewOverlay.hidden = true;
  });
  
  previewOverlay.addEventListener('click', (e) => {
    if (e.target === previewOverlay) {
      previewOverlay.hidden = true;
    }
  });
})();
```

- [ ] **Step 3: Add file action helper functions**

Add after context menu:

```javascript
// ===== File Action Helpers =====
async function downloadFile(filename) {
  const a = document.createElement('a');
  a.href = '/download/' + encodeURIComponent(filename);
  a.download = filename;
  a.click();
  showToast(`Downloading ${filename}...`);
}

async function copyLink(filename) {
  const url = location.origin + '/download/' + encodeURIComponent(filename);
  const textarea = document.createElement('textarea');
  textarea.value = url;
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  document.body.appendChild(textarea);
  textarea.select();
  
  try {
    document.execCommand('copy');
    showToast('Link copied to clipboard');
  } catch (err) {
    showToast('Failed to copy link', 'error');
  }
  
  document.body.removeChild(textarea);
}

async function deleteFile(filename) {
  try {
    const response = await fetch('/api/files/' + encodeURIComponent(filename), {
      method: 'DELETE'
    });
    
    if (!response.ok) {
      throw new Error('Failed to delete file');
    }
    
    loadFiles(true); // Preserve other selections
    showToast('File deleted');
  } catch (error) {
    console.error('Delete error:', error);
    showToast('Failed to delete file', 'error');
  }
}

function showPreview(url) {
  const previewOverlay = document.getElementById('preview-overlay');
  const previewImage = document.getElementById('preview-image');
  
  previewImage.src = url;
  previewOverlay.hidden = false;
  
  // Focus for accessibility
  previewImage.focus();
}
```

- [ ] **Step 4: Test search functionality**

```bash
python local_share.py
```

Upload test files with different names, then:
1. Type in search box - list should filter
2. Click clear search - list should show all
3. Verify clear button appears/disappears correctly

- [ ] **Step 5: Test view toggle**

Click view toggle button and select each view:
- List (default)
- Detail 
- Cards
- Compact

Verify layout changes correctly and preference persists after refresh.

- [ ] **Step 6: Test context menu**

Right-click on a file:
- Verify menu appears at cursor
- Click Download - file should download
- Click Copy Link - toast should confirm
- Click Preview - image preview should show (if image)
- Click Delete - confirmation then deletion

Also test 3-dot button menu works same as right-click.

- [ ] **Step 7: Test preview overlay**

Click preview button or context menu preview:
- Verify overlay covers screen
- Verify image displays correctly
- Click outside or close button - overlay hides
- Press Escape - overlay hides

- [ ] **Step 8: Commit search, view, and menu functionality**

```bash
git add local_share.py
git commit -m "feat: add search, view toggle, context menu, and preview

- Search with live filtering and clear button
- View toggle dropdown with List/Detail/Cards/Compact modes
- Context menu on right-click and 3-dot button
- File actions: download, copy link, preview, delete
- Image preview overlay with backdrop
- Keyboard Escape closes menus/preview
- View preference persists in localStorage

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 11: JavaScript - Upload System

**Files:**
- Modify: `local_share.py:PAGE` (add to JavaScript section)

**Interfaces:**
- Consumes: File input/drop zone from Task 2, upload queue from Task 6
- Produces: Drag & drop upload, progress tracking, upload queue display, multi-file support

- [ ] **Step 1: Add upload queue management**

Add after file action helpers:

```javascript
// ===== Upload System =====
(function() {
  const fileInput = document.getElementById('file-input');
  const dropZone = document.getElementById('drop-zone');
  const uploadQueue = document.getElementById('upload-queue');
  const queueItems = document.getElementById('queue-items');
  
  let uploadCount = 0;
  
  // File input change
  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      handleFiles(Array.from(e.target.files));
      fileInput.value = ''; // Reset for same file selection
    }
  });
  
  // Drag & drop
  ['dragenter', 'dragover'].forEach(event => {
    dropZone.addEventListener(event, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add('dragover');
    });
  });
  
  ['dragleave', 'drop'].forEach(event => {
    dropZone.addEventListener(event, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove('dragover');
    });
  });
  
  dropZone.addEventListener('drop', (e) => {
    handleFiles(Array.from(e.dataTransfer.files));
  });
  
  function handleFiles(files) {
    // Validate file count and size
    const validFiles = Array.from(files).filter(file => {
      if (file.size === 0) {
        showToast('Empty files are not allowed', 'error');
        return false;
      }
      
      if (file.size > MAX_UPLOAD_BYTES) {
        showToast(`File too large: ${formatSize(file.size)}`, 'error');
        return false;
      }
      
      return true;
    });
    
    if (validFiles.length === 0) return;
    
    // Show upload queue
    uploadQueue.hidden = false;
    
    // Process each file
    validFiles.forEach(file => {
      uploadCount++;
      const uploadId = `upload-${uploadCount}`;
      uploadFile(file, uploadId);
    });
  }
  
  function uploadFile(file, uploadId) {
    // Create queue item UI
    const queueItem = document.createElement('div');
    queueItem.className = 'queue-item';
    queueItem.id = uploadId;
    
    const header = document.createElement('div');
    header.className = 'queue-item-header';
    
    const name = document.createElement('div');
    name.className = 'queue-name';
    name.textContent = file.name;
    
    const size = document.createElement('div');
    size.className = 'queue-size';
    size.textContent = formatSize(file.size);
    
    header.append(name, size);
    
    const progressContainer = document.createElement('div');
    progressContainer.className = 'queue-progress';
    progressContainer.setAttribute('role', 'progressbar');
    progressContainer.setAttribute('aria-valuemin', '0');
    progressContainer.setAttribute('aria-valuemax', '100');
    progressContainer.setAttribute('aria-valuenow', '0');
    
    const progressBar = document.createElement('div');
    progressBar.className = 'queue-progress-bar';
    progressBar.style.width = '0%';
    
    progressContainer.appendChild(progressBar);
    
    const speed = document.createElement('div');
    speed.className = 'queue-speed';
    speed.setAttribute('aria-live', 'polite');
    
    queueItem.append(header, progressContainer, speed);
    queueItems.appendChild(queueItem);
    
    // Upload via XMLHttpRequest for progress tracking
    const formData = new FormData();
    formData.append('files', file);
    
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/upload');
    
    const startTime = Date.now();
    let loaded = 0;
    
    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) {
        const percent = Math.round((e.loaded / e.total) * 100);
        progressBar.style.width = percent + '%';
        progressContainer.setAttribute('aria-valuenow', percent);
        
        // Calculate speed
        const now = Date.now();
        const elapsed = (now - startTime) / 1000; // seconds
        if (elapsed > 0) {
          const bytesPerSecond = e.loaded / elapsed;
          speed.textContent = `${formatSize(bytesPerSecond)}/s`;
        }
      }
    });
    
    xhr.onload = () => {
      if (xhr.status === 200 || xhr.status === 201) {
        speed.textContent = 'Complete';
        progressContainer.setAttribute('aria-valuenow', '100');
        
        // Remove after delay
        setTimeout(() => {
          queueItem.remove();
          if (queueItems.children.length === 0) {
            uploadQueue.hidden = true;
            loadFiles(); // Refresh file list
            showToast('Upload complete');
          }
        }, 1500);
      } else {
        speed.textContent = 'Failed';
        speed.style.color = 'var(--danger)';
        
        setTimeout(() => queueItem.remove(), 3000);
      }
    };
    
    xhr.onerror = () => {
      speed.textContent = 'Failed';
      speed.style.color = 'var(--danger)';
      
      setTimeout(() => queueItem.remove(), 3000);
    };
    
    xhr.send(formData);
  }
})();
```

- [ ] **Step 2: Add keyboard accessibility to drop zone**

Add after upload system initialization:

```javascript
// Make drop zone keyboard accessible
dropZone.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    fileInput.click();
  }
});
```

- [ ] **Step 3: Test upload system**

```bash
python local_share.py
```

Test upload flow:
1. Click drop zone or drag files onto it
2. Select test files (small images/text files work best)
3. Verify upload queue appears bottom-right
4. Watch progress bars fill and speed display
5. Verify upload completes and queue hides
6. Verify file appears in file list
7. Verify stats update

Test drag & drop:
1. Drag files from desktop onto drop zone
2. Verify same upload flow works

Test keyboard:
1. Tab to drop zone
2. Press Enter or Space
3. Verify file picker opens

- [ ] **Step 4: Test multiple file upload**

Select multiple files at once:
- Verify each gets its own queue item
- Verify all upload concurrently
- Verify all complete and refresh list

- [ ] **Step 5: Test upload validation**

Try to upload:
1. Empty file (should show error)
2. File larger than 512MB (should show error)
3. Valid file (should succeed)

- [ ] **Step 6: Commit upload system**

```bash
git add local_share.py
git commit -m "feat: add upload system with drag & drop and progress tracking

- Drag & drop support with visual feedback
- Click-to-upload via file input
- Upload queue with individual progress bars
- Real-time upload speed calculation
- Multi-file upload support
- File validation (size limits, empty files)
- Keyboard accessibility (Enter/Space to trigger)
- Automatic cleanup and file list refresh
- Visual drag-over state with glow effect

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 12: JavaScript - ZIP Bulk Download

**Files:**
- Modify: `local_share.py:PAGE` (add to JavaScript section)

**Interfaces:**
- Consumes: State from Task 9, bulk download button from Task 2, backend endpoint from Task 1
- Produces: Bulk download functionality that creates ZIP of selected files

- [ ] **Step 1: Add bulk download functionality**

Add after upload system:

```javascript
// ===== Bulk Download (ZIP) =====
(function() {
  const bulkDownloadBtn = document.getElementById('bulk-download');
  
  bulkDownloadBtn.addEventListener('click', async () => {
    if (state.selectedFiles.size === 0) return;
    
    const fileNames = Array.from(state.selectedFiles);
    
    // Show preparing toast
    showToast(`Preparing ${fileNames.length} file(s) for download...`, 'info');
    
    try {
      // Build query string
      const params = new URLSearchParams();
      fileNames.forEach(name => params.append('files', name));
      
      // Create temporary link for download
      const downloadUrl = `/api/download-bulk?${params.toString()}`;
      
      const a = document.createElement('a');
      a.href = downloadUrl;
      a.download = `selected-files-${new Date().toISOString().slice(0,19).replace(/[:T]/g,'-')}.zip`;
      
      // Trigger download
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      
      // Update toast
      showToast(`Downloading ${fileNames.length} file(s) as ZIP...`, 'info');
      
    } catch (error) {
      console.error('Bulk download error:', error);
      showToast('Failed to prepare ZIP download', 'error');
    }
  });
})();
```

- [ ] **Step 2: Test bulk download**

```bash
python local_share.py
```

Upload a few test files, then:
1. Select multiple files using checkboxes
2. Click bulk download button
3. Verify ZIP file downloads
4. Verify ZIP contains all selected files
5. Verify filename format: `selected-files-YYYY-MM-DD-HH-MM-SS.zip`
6. Verify toast messages show correctly

Test edge cases:
1. No files selected - button should be disabled
2. Single file selected - should still work
3. Large selection - verify performance

- [ ] **Step 3: Test keyboard shortcut for bulk download**

From spec, bulk download should be available when files are selected. Since we already enable the button when selection exists, keyboard users can tab to it and press Enter.

- [ ] **Step 4: Commit bulk download**

```bash
git add local_share.py
git commit -m "feat: add ZIP bulk download functionality

- Bulk download button handler
- Creates ZIP of selected files on server
- Downloads as single ZIP file with timestamp filename
- Shows preparatory and download toast messages
- Properly handles empty selection (button disabled)
- Uses new /api/download-bulk endpoint
- Filename format: selected-files-YYYY-MM-DD-HH-MM-SS.zip

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 13: JavaScript - Auto-refresh System

**Files:**
- Modify: `local_share.py:PAGE` (add to JavaScript section)

**Interfaces:**
- Consumes: Auto-refresh checkbox from Task 2, loadFiles() from Task 9
- Produces: Auto-refresh with selection preservation, start/stop controls

- [ ] **Step 1: Add auto-refresh functionality**

Add after bulk download:

```javascript
// ===== Auto-refresh System =====
(function() {
  const autoRefreshCheckbox = document.getElementById('auto-refresh');
  const refreshBtn = document.getElementById('refresh-btn');
  
  let autoRefreshInterval = null;
  
  function startAutoRefresh() {
    if (!autoRefreshInterval) {
      autoRefreshInterval = setInterval(() => {
        loadFiles(true); // Preserve selection
      }, 5000); // 5 seconds
      
      showToast('Auto-refresh enabled');
    }
  }
  
  function stopAutoRefresh() {
    if (autoRefreshInterval) {
      clearInterval(autoRefreshInterval);
      autoRefreshInterval = null;
      showToast('Auto-refresh disabled');
    }
  }
  
  // Checkbox handler
  autoRefreshCheckbox.addEventListener('change', () => {
    if (autoRefreshCheckbox.checked) {
      startAutoRefresh();
    } else {
      stopAutoRefresh();
    }
  });
  
  // Manual refresh button
  refreshBtn.addEventListener('click', () => {
    loadFiles();
    showToast('Files refreshed');
  });
  
  // Keyboard shortcut: Ctrl+R or F5
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey && e.key === 'r') || e.key === 'F5') {
      e.preventDefault();
      loadFiles();
      showToast('Files refreshed');
    }
  });
})();
```

- [ ] **Step 2: Test auto-refresh**

```bash
python local_share.py
```

Test flow:
1. Check auto-refresh checkbox
2. Verify toast shows "Auto-refresh enabled"
3. Wait 5+ seconds - file list should refresh automatically
4. Verify selection is preserved during refresh
5. Uncheck box - verify toast shows "Auto-refresh disabled"
6. Verify refreshing stops

Test manual refresh:
1. Click refresh button - should refresh immediately
2. Press Ctrl+R or F5 - should refresh immediately
3. Verify toast shows "Files refreshed"

Test selection preservation:
1. Select some files
2. Wait for auto-refresh
3. Verify same files remain selected
4. Add/delete files via other means - verify selection adapts correctly

- [ ] **Step 3: Commit auto-refresh system**

```bash
git add local_share.py
git commit -m "feat: add auto-refresh system with selection preservation

- Auto-refresh toggle with 5-second interval
- loadFiles(true) preserves current selections
- Manual refresh button (Ctrl+R, F5 shortcuts)
- Toast notifications for state changes
- Selection preserved during refresh (removes deleted files)
- Proper interval cleanup to prevent memory leaks

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 14: JavaScript - QR Code Integration

**Files:**
- Modify: `local_share.py:PAGE` (add to JavaScript section)

**Interfaces:**
- Consumes: QRious library (already embedded), QR container from Task 2
- Produces: QR code generation with current URL

- [ ] **Step 1: Add QR code initialization**

Add at the end of JavaScript, before closing script tag:

```javascript
// ===== QR Code =====
(function() {
  const qrContainer = document.getElementById('qr-container');
  
  // Create QRious instance
  const qr = new QRious({
    element: document.createElement('canvas'),
    value: location.href,
    size: 200,
    backgroundAlpha: 0,
    foreground: '#000',
    level: 'M'
  });
  
  qrContainer.appendChild(qr.canvas);
  
  // Update QR code if URL changes (though unlikely in this app)
  window.addEventListener('resize', () => {
    // QR code size is fixed, but we could make it responsive if needed
  });
})();
```

- [ ] **Step 2: Test QR code**

```bash
python local_share.py
```

Verify:
1. QR code appears in footer
2. QR code is square (not stretched)
3. QR code scans to current URL
4. QR code has proper styling (white background from CSS)
5. QR code respects theme (foreground should be dark on both themes)

- [ ] **Step 3: Test QR code responsiveness**

Resize browser:
- Verify QR code maintains square aspect ratio
- Verify it doesn't stretch horizontally on wide screens
- Verify it scales appropriately in footer

- [ ] **Step 4: Commit QR code**

```bash
git add local_share.py
git commit -m "feat: add QR code integration

- QRious library initialization
- QR code encodes current page URL
- Fixed size 200x200 pixels
- White background for scanning reliability
- Black foreground for contrast
- Error correction level M
- Preserved in footer section

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 15: JavaScript - Keyboard Shortcuts & Accessibility

**Files:**
- Modify: `local_share.py:PAGE` (add to JavaScript section)

**Interfaces:**
- Consumes: All UI elements and state
- Produces: Comprehensive keyboard navigation, focus management, ARIA attributes, screen reader support

- [ ] **Step 1: Add comprehensive keyboard shortcuts**

Add after QR code (still within script tag):

```javascript
// ===== Keyboard Shortcuts & Accessibility =====
(function() {
  // Focus trap for modals
  function focusTrap(container) {
    const focusableElements = container.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const first = focusableElements[0];
    const last = focusableElements[focusableElements.length - 1];
    
    return { first, last };
  }
  
  document.addEventListener('keydown', (e) => {
    // Prevent shortcuts when typing in inputs
    if (e.target.tagName === 'INPUT' || 
        e.target.tagName === 'TEXTAREA' ||
        e.target.isContentEditable) {
      return;
    }
    
    // Theme toggle: Ctrl/Cmd + T
    if ((e.ctrlKey || e.metaKey) && e.key === 't') {
      e.preventDefault();
      document.getElementById('theme-toggle').click();
    }
    
    // Search focus: Ctrl/Cmd + F
    if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
      e.preventDefault();
      document.getElementById('search-input').focus();
    }
    
    // Select all: Ctrl/Cmd + A
    if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
      e.preventDefault();
      document.getElementById('select-all').click();
    }
    
    // Refresh: Ctrl/Cmd + R or F5
    if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
      e.preventDefault();
      document.getElementById('refresh-btn').click();
    }
    if (e.key === 'F5') {
      e.preventDefault();
      document.getElementById('refresh-btn').click();
    }
    
    // Delete selected: Delete key (when files selected)
    if (e.key === 'Delete' && 
        state.selectedFiles.size > 0 && 
        !document.activeElement.matches('input,textarea')) {
      e.preventDefault();
      document.getElementById('bulk-delete').click();
    }
    
    // Open view toggle: V key
    if (e.key === 'v' || e.key === 'V') {
      e.preventDefault();
      document.getElementById('view-toggle').click();
    }
    
    // Toggle auto-refresh: A key (when not typing)
    if (e.key === 'a' && !e.ctrlKey && !e.metaKey) {
      // Handled by select all above when ctrl/meta is pressed
    }
  });
  
  // Enhanced ARIA attributes and live regions
  function enhanceAccessibility() {
    // File list live region for selection changes
    const fileList = document.getElementById('file-list');
    if (fileList) {
      fileList.setAttribute('aria-live', 'polite');
      fileList.setAttribute('aria-atomic', 'false');
    }
    
    // Upload queue live region
    const uploadQueue = document.getElementById('upload-queue');
    if (uploadQueue) {
      uploadQueue.setAttribute('aria-live', 'polite');
    }
    
    // Stats live region
    document.getElementById('stat-files').setAttribute('aria-live', 'polite');
    document.getElementById('stat-size').setAttribute('aria-live', 'polite');
    document.getElementById('stat-recent').setAttribute('aria-live', 'polite');
    
    // Add labels to buttons
    document.getElementById('theme-toggle').setAttribute('aria-label', 'Toggle dark/light theme');
    document.getElementById('refresh-btn').setAttribute('aria-label', 'Refresh file list');
    document.getElementById('auto-refresh').setAttribute('aria-label', 'Enable auto-refresh');
    document.getElementById('bulk-download').setAttribute('aria-label', 'Download selected files as ZIP');
    document.getElementById('bulk-delete').setAttribute('aria-label', 'Delete selected files');
    document.getElementById('view-toggle').setAttribute('aria-label', 'Change file view layout');
    document.getElementById('clear-search').setAttribute('aria-label', 'Clear search');
    
    // File items
    const fileItems = document.querySelectorAll('.file-item');
    fileItems.forEach(item => {
      item.setAttribute('role', 'listitem');
      const checkbox = item.querySelector('.file-checkbox');
      if (checkbox) {
        checkbox.setAttribute('aria-label', `Select ${item.dataset.name}`);
      }
    });
  }
  
  // Run accessibility enhancement on load and after DOM changes
  enhanceAccessibility();
  
  // Re-enhance after file list updates
  const originalFilterAndRenderFiles = window.filterAndRenderFiles;
  window.filterAndRenderFiles = function() {
    originalFilterAndRenderFiles();
    setTimeout(enhanceAccessibility, 100);
  };
  
  // Focus styles for keyboard users
  const style = document.createElement('style');
  style.textContent = `
    :focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }
    
    /* Skip link for screen readers */
    .skip-link {
      position: absolute;
      top: -40px;
      left: 0;
      background: var(--accent);
      color: white;
      padding: 8px 16px;
      border-radius: var(--radius-sm);
      z-index: 10000;
      font-size: 0.875rem;
    }
    
    .skip-link:focus {
      top: 0;
    }
  `;
  document.head.appendChild(style);
  
  // Add skip link
  const skipLink = document.createElement('a');
  skipLink.href = '#main-content';
  skipLink.className = 'skip-link';
  skipLink.textContent = 'Skip to main content';
  skipLink.addEventListener('click', (e) => {
    e.preventortDefault();
    document.getElementById('main-content')?.focus();
  });
  document.body.insertBefore(skipLink, document.body.firstChild);
  
  // Add main content identifier
  const mainContent = document.querySelector('main');
  if (mainContent) {
    mainContent.id = 'main-content';
  }
})();
```

- [ ] **Step 2: Test keyboard shortcuts**

```bash
python local_share.py
```

Test each shortcut:
1. **Ctrl+T** - Theme toggle
2. **Ctrl+F** - Focus search input
3. **Ctrl+A** - Select all files
4. **Ctrl+R / F5** - Refresh file list
5. **Delete** - Bulk delete (when files selected)
6. **V** - Toggle view menu
7. **Tab** - Navigate through all interactive elements
8. **Enter/Space** - Activate focused buttons
9. **Escape** - Close menus/preview/overlays

Test screen reader compatibility:
- Verify all buttons have aria-label
- Verify file list has proper role
- Verify live regions announce changes
- Verify skip link works

- [ ] **Step 3: Test focus management**

1. Tab through interface - verify logical order
2. Open context menu - verify focus trapped in menu
3. Close menu - verify focus returns to trigger
4. Open preview - verify focus on image
5. Close preview - verify focus returns to trigger
6. Open view menu - verify focus trapped in menu

- [ ] **Step 4: Commit accessibility and keyboard shortcuts**

```bash
git add local_share.py
git commit -m "feat: add keyboard shortcuts and accessibility enhancements

- Comprehensive keyboard shortcuts (Ctrl+T, Ctrl+F, Ctrl+A, Ctrl+R/F5, Delete, V)
- Focus trapping for modals and menus
- Enhanced ARIA attributes and labels
- Live regions for status updates
- Skip link for screen readers
- Improved focus styles for keyboard users
- Accessibility enhancements after DOM updates
- Logical tab order throughout interface

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 16: Integration Testing & Polish

**Files:**
- Modify: `local_share.py:PAGE` (final touches to all sections)

**Interfaces:**
- Consumes: All previous tasks
- Produces: Fully integrated, tested, and polished application

- [ ] **Step 1: Add final polish and bug fixes**

Add final JavaScript at the very end:

```javascript
// ===== Initialization & Final Setup =====
(function() {
  // Initialize view from localStorage
  const savedView = localStorage.getItem('fileView');
  if (savedView) {
    state.currentView = savedView;
    const viewOption = document.querySelector(`.view-option[data-view="${savedView}"]`);
    if (viewOption) {
      viewOption.classList.add('active');
      document.getElementById('view-label').textContent = 
        savedView.charAt(0).toUpperCase() + savedView.slice(1);
    }
  }
  
  // Prevent body scroll when modals are open
  function preventBodyScroll() {
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = originalOverflow; };
  }
  
  // Apply to preview overlay
  const previewOverlay = document.getElementById('preview-overlay');
  if (previewOverlay) {
    const restoreScroll = preventBodyScroll();
    previewOverlay.addEventListener('show', () => restoreScroll());
    previewOverlay.addEventListener('hide', () => restoreScroll());
  }
  
  // Final initialization
  document.documentElement.style.setProperty('--initial-load', 'true');
  
  // Hide address bar on mobile after load
  setTimeout(() => {
    if (window.visualViewport) {
      window.scrollTo(0, 1);
    }
  }, 100);
})();
```

- [ ] **Step 2: Run comprehensive integration test**

```bash
python local_share.py
```

Perform full user flow test:

1. **Theme Testing**
   - Start in dark mode (default)
   - Toggle to light mode - verify smooth transition
   - Toggle back to dark mode - verify smooth transition
   - Refresh page - verify theme persists

2. **Background Animation**
   - Verify isometric dot grid in both themes
   - Verify dots glow and flicker
   - Verify slow drift/rotation
   - Verify responsive spacing on resize

3. **File Operations**
   - Upload single file - verify stats update
   - Upload multiple files - verify queue shows all
   - Select files - verify checkboxes work
   - Select all - verify all selected
   - Search files - verify filtering works
   - Clear search - verify all shown
   - View modes - verify List/Detail/Cards/Compact all work
   - Context menu - verify all actions work
   - Preview - verify image preview works
   - Delete single - verify removed from list
   - Bulk delete - verify multiple removed
   - Bulk download ZIP - verify downloaded and contains correct files

4. **Upload System**
   - Drag & drop upload - verify works
   - Click upload - verify works
   - Keyboard upload (Enter/Space on drop zone) - verify works
   - Progress bars - verify show percentage and speed
   - Queue completion - verify auto-hide and list refresh

5. **Auto-refresh**
   - Enable auto-refresh - verify periodic refresh
   - Verify selection preserved during refresh
   - Disable auto-refresh - verify stops
   - Manual refresh button - verify works
   - Keyboard shortcuts (Ctrl+R, F5) - verify work

6. **Responsiveness**
   - Test desktop (>1024px) - verify 2-column layout
   - Test tablet (768-1024px) - verify stacked layout
   - Test mobile (<768px) - verify single column with proper padding
   - Test view modes on all breakpoints
   - Test upload queue positioning on all breakpoints
   - Test QR code aspect ratio on all breakpoints

7. **Accessibility**
   - Navigate with Tab only - verify all reachable
   - Test keyboard shortcuts
   - Verify screen reader labels
   - Verify focus indicators visible
   - Test skip link
   - Verify toast announcements

8. **Performance**
   - Verify no console errors
   - Verify smooth animations (60fps)
   - Verify quick response to interactions (<100ms)
   - Verify memory doesn't leak over time

- [ ] **Step 3: Test edge cases**

1. **Empty state**
   - Start with no files - verify empty state message
   - Upload files - verify message disappears
   - Delete all files - verify message returns

2. **Error handling**
   - Try to delete non-existent file - verify error handled
   - Try to download ZIP with no selection - verify button disabled
   - Try to upload oversized file - verify error toast
   - Try to upload empty file - verify error toast

3. **Browser compatibility**
   - Test localStorage persistence
   - Verify fallback for older browsers (if any)
   - Verify graceful degradation

- [ ] **Step 4: Final performance check**

Use browser dev tools:
1. Performance tab - record interaction
2. Check for jank or dropped frames
3. Verify CSS animations use transform/opacity
4. Verify canvas animation uses requestAnimationFrame
5. Verify no layout thrashing

- [ ] **Step 5: Commit final polish**

```bash
git add local_share.py
git commit -m "feat: integration testing and final polish

- Comprehensive user flow testing
- Theme transition verification
- Background animation validation
- File operation testing (upload, download, delete, select)
- Upload system testing (drag & drop, click, keyboard)
- Auto-refresh with selection preservation
- Responsive layout testing (mobile/tablet/desktop)
- Accessibility verification (keyboard, screen reader, ARIA)
- Performance optimization and bug fixing
- Edge case handling (empty states, errors)
- Final polish and readiness for production

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Plan Complete

All 16 tasks have been defined. The plan covers:

✅ Backend ZIP bulk download endpoint  
✅ HTML structure with semantic elements  
✅ CSS variables and theme system  
✅ Glassmorphism card components  
✅ Responsive layout grid  
✅ Drop zone and file list components  
✅ Upload queue, toast, and preview overlays  
✅ Animated isometric dot grid background  
✅ Theme toggle with seamless transitions  
✅ File management core (loading, stats, selection)  
✅ Search, view toggle, context menu, and preview  
✅ Upload system with drag & drop and progress  
✅ ZIP bulk download functionality  
✅ Auto-refresh with selection preservation  
✅ QR code integration  
✅ Keyboard shortcuts and accessibility  
✅ Integration testing and final polish  

**Plan complete and saved to `docs/superpowers/plans/2026-09-24-glassmorphism-redesign.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**