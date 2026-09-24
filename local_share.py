"""A dependency-free LAN file sharing server."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import html
import json
import logging
import mimetypes
import secrets
import socket
import sys
import time
import zipfile
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse


HOST = "0.0.0.0"
PORT = 8080
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_ZIP_BYTES = 500 * 1024 * 1024
SHARED_DIRECTORY = Path(__file__).with_name("shared_files")

PASSWORD = ""
FILE_EXPIRY_HOURS = 0
SESSION_SECRET = secrets.token_hex(32)
SESSION_DURATION = 3600 * 24

# Chunk size for streaming large files (64KB - optimal for network throughput)
CHUNK_SIZE = 64 * 1024

# Session cleanup interval (seconds) - clean expired sessions periodically
SESSION_CLEANUP_INTERVAL = 300

# Optional rate limiting: max upload requests per minute per IP (0 = disabled)
UPLOAD_RATE_LIMIT = 0


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Local Drop - LAN file sharing server")
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=PORT,
        help=f"Port to run the server on (default: {PORT})"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=HOST,
        help=f"Host address to bind to (default: {HOST})"
    )
    return parser.parse_args()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("local-drop")

sessions: dict[str, float] = {}
_last_session_cleanup = time.time()

# Rate limiting: IP -> list of timestamps
upload_requests: dict[str, list[float]] = {}

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"})


def file_icon(name: str) -> str:
    ext = Path(name).suffix.lower()
    icons = {
        ".pdf": "file-text", ".doc": "file-text", ".docx": "file-text",
        ".xls": "file-spreadsheet", ".xlsx": "file-spreadsheet", ".csv": "file-spreadsheet",
        ".mp3": "music", ".wav": "music", ".flac": "music",
        ".ogg": "music", ".m4a": "music",
        ".mp4": "film", ".mkv": "film", ".avi": "film",
        ".mov": "film", ".webm": "film",
        ".png": "image", ".jpg": "image", ".jpeg": "image",
        ".gif": "image", ".webp": "image", ".bmp": "image",
        ".svg": "image", ".ico": "image",
        ".zip": "archive", ".rar": "archive", ".7z": "archive",
        ".tar": "archive", ".gz": "archive",
        ".py": "file-code", ".js": "file-code", ".ts": "file-code",
        ".html": "globe", ".css": "globe",
        ".txt": "file-text", ".md": "file-text", ".log": "file-text",
        ".json": "file-json", ".xml": "file-json", ".yaml": "file-json",
        ".exe": "app-window", ".msi": "app-window", ".dmg": "app-window",
        ".apk": "smartphone", ".ipa": "smartphone",
    }
    return icons.get(ext, "file")


def is_image(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_EXTENSIONS


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#0a0a0a">
<meta name="description" content="Local Drop - Share files on your local network.">
<title>Local Drop · Instant File Transfer</title>
<style>
/* ===== CSS Reset & Base ===== */
*, *::before, *::after {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

/* ===== Icon System (lucide svg sprite) ===== */
.lucide-icon {
  width: 1em;
  height: 1em;
  display: inline-block;
  flex-shrink: 0;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
  vertical-align: -0.125em;
}

.icon-sprite {
  position: absolute;
  width: 0;
  height: 0;
  overflow: hidden;
}

:root {
  --font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif;

  --spacing-xs: 4px;
  --spacing-sm: 8px;
  --spacing-md: 16px;
  --spacing-lg: 24px;
  --spacing-xl: 32px;

  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;

  --transition-theme: all 0.45s cubic-bezier(0.4, 0.0, 0.2, 1);
  --transition-fast: all 0.2s ease;
  --transition-quick: all 0.15s ease;

  --z-background: 0;
  --z-content: 1;
  --z-dropdown: 100;
  --z-overlay: 500;
  --z-queue: 1000;
  --z-toast: 2000;
}

/* ===== Theme: Dark Mode (Default) ===== */
[data-theme="dark"] {
  color-scheme: dark;
  --bg-gradient-start: #0a0a0a;
  --bg-gradient-end: #1a1a1a;
  --glass-overlay: rgba(255, 255, 255, 0.03);
  --glass-overlay-thick: rgba(255, 255, 255, 0.08);
  --glass-overlay-thin: rgba(255, 255, 255, 0.015);
  --glass-border: rgba(255, 255, 255, 0.08);
  --glass-blur: blur(20px) saturate(150%);
  --glass-blur-strong: blur(30px) saturate(160%);
  --glass-inset: inset 0 1px 0 0 rgba(255, 255, 255, 0.1);
  --glass-sheen: linear-gradient(180deg, rgba(255, 255, 255, 0.05) 0%, rgba(255, 255, 255, 0) 45%);

  --aurora-1: rgba(99, 102, 241, 0.4);
  --aurora-2: rgba(168, 85, 247, 0.34);
  --aurora-3: rgba(56, 189, 248, 0.3);

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
  color-scheme: light;
  --bg-gradient-start: #e8e8e8;
  --bg-gradient-end: #d5d5d5;
  --glass-overlay: rgba(0, 0, 0, 0.03);
  --glass-overlay-thick: rgba(0, 0, 0, 0.06);
  --glass-overlay-thin: rgba(0, 0, 0, 0.015);
  --glass-border: rgba(0, 0, 0, 0.1);
  --glass-blur: blur(20px) saturate(150%);
  --glass-blur-strong: blur(30px) saturate(160%);
  --glass-inset: inset 0 1px 0 0 rgba(255, 255, 255, 0.6);
  --glass-sheen: linear-gradient(180deg, rgba(255, 255, 255, 0.5) 0%, rgba(255, 255, 255, 0.06) 45%);

  --aurora-1: rgba(99, 102, 241, 0.22);
  --aurora-2: rgba(168, 85, 247, 0.18);
  --aurora-3: rgba(14, 165, 233, 0.16);

  --dot-color: rgba(0, 0, 0, 0.14);
  --dot-glow: rgba(0, 0, 0, 0.3);

  --text-primary: #1a1a1a;
  --text-secondary: rgba(0, 0, 0, 0.7);
  --text-tertiary: rgba(0, 0, 0, 0.5);

  --accent: #6366f1;
  --accent-hover: #4f46e5;
  --accent-rgb: 99, 102, 241;

  --success: #059669;
  --danger: #dc2626;

  --shadow: 0 6px 20px 0 rgba(0, 0, 0, 0.12);
  --shadow-hover: 0 10px 32px 0 rgba(0, 0, 0, 0.18);
}

/* ===== Base Styles ===== */
/* The hidden attribute must always win over any display set by a class. */
[hidden] {
  display: none !important;
}

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
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
  max-width: 1360px;
  margin: 0 auto;
}

body, .glass-card, .glass-card-thick, .glass-card-thin, .glass-card-hover,
.btn, input, button, .file-item, .stat-card, .context-menu, .view-menu,
.theme-toggle, .search-input, select {
  transition: var(--transition-theme);
}

/* Theme transition crossfade overlay: eases the old background into the new mode. */
body::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: var(--z-background);
  pointer-events: none;
  background: linear-gradient(135deg, var(--theme-fade-start, transparent) 0%, var(--theme-fade-end, transparent) 100%);
  opacity: 0;
  transition: opacity 0.45s cubic-bezier(0.4, 0.0, 0.2, 1);
  will-change: opacity;
}

body.theme-transition::before {
  opacity: 1;
  transition: none;
}

body.theme-transition.theme-fading::before {
  opacity: 0;
  transition: opacity 0.45s cubic-bezier(0.4, 0.0, 0.2, 1);
}

a {
  color: var(--accent);
  text-decoration: none;
}

button {
  font-family: inherit;
}

/* ===== Glass Card Component ===== */
.glass-card {
  background-color: var(--glass-overlay);
  background-image: var(--glass-sheen);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-inset), var(--shadow);
}

.glass-card-thick {
  background-color: var(--glass-overlay-thick);
}

.glass-card-thin {
  background-color: var(--glass-overlay-thin);
}

.glass-card-hover {
  transition: var(--transition-fast);
}

.glass-card-hover:hover {
  background-color: var(--glass-overlay-thick);
  transform: translateY(-2px);
  box-shadow: var(--glass-inset), var(--shadow-hover);
}

/* ===== Aurora Blobs (give the frosted glass something to blur) ===== */
.aurora {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: var(--z-background);
  pointer-events: none;
  overflow: hidden;
}

.aurora-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  will-change: transform;
}

.aurora-blob-1 {
  width: 55vw;
  height: 55vw;
  left: -12vw;
  top: -12vw;
  background: radial-gradient(circle, var(--aurora-1) 0%, transparent 70%);
  animation: aurora-drift-1 26s ease-in-out infinite alternate;
}

.aurora-blob-2 {
  width: 45vw;
  height: 45vw;
  right: -8vw;
  top: 30vh;
  background: radial-gradient(circle, var(--aurora-2) 0%, transparent 70%);
  animation: aurora-drift-2 32s ease-in-out infinite alternate;
}

.aurora-blob-3 {
  width: 50vw;
  height: 50vw;
  left: 30vw;
  bottom: -18vw;
  background: radial-gradient(circle, var(--aurora-3) 0%, transparent 70%);
  animation: aurora-drift-3 38s ease-in-out infinite alternate;
}

@keyframes aurora-drift-1 {
  from { transform: translate(0, 0) scale(1); }
  to { transform: translate(8vw, 6vh) scale(1.15); }
}

@keyframes aurora-drift-2 {
  from { transform: translate(0, 0) scale(1.05); }
  to { transform: translate(-6vw, -8vh) scale(1); }
}

@keyframes aurora-drift-3 {
  from { transform: translate(0, 0) scale(1); }
  to { transform: translate(-7vw, 5vh) scale(1.12); }
}

/* ===== Header ===== */
.glass-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--spacing-md) var(--spacing-lg);
  position: relative;
  z-index: var(--z-content);
  height: 64px;
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.brand-logo {
  font-size: 1.5rem;
  color: var(--accent);
  animation: pulse 2.4s ease-in-out infinite;
}

.logo {
  font-size: 1.5rem;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--text-primary);
  background: linear-gradient(135deg, var(--text-primary) 0%, var(--text-secondary) 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.theme-toggle {
  background: transparent;
  border: none;
  font-size: 1.4rem;
  cursor: pointer;
  padding: var(--spacing-sm);
  border-radius: 50%;
  color: var(--text-primary);
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.theme-toggle:hover {
  background: var(--glass-overlay-thin);
  transform: scale(1.1);
}

.theme-icon {
  display: inline-block;
  transition: transform 0.4s cubic-bezier(0.4, 0.0, 0.2, 1), opacity 0.4s cubic-bezier(0.4, 0.0, 0.2, 1);
}

.theme-toggle.rotating .theme-icon {
  transform: rotate(180deg);
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.8; transform: scale(1.06); }
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

/* ===== Drop Zone ===== */
.drop-zone {
  padding: var(--spacing-xl) var(--spacing-lg);
  border: 2px dashed var(--glass-border);
  border-radius: var(--radius-lg);
  text-align: center;
  cursor: pointer;
  min-height: 420px;
  display: flex;
  align-items: center;
  justify-content: center;
  outline: none;
  background-color: var(--glass-overlay);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
}

.drop-zone:hover {
  border-color: var(--accent);
  background-color: var(--glass-overlay-thin);
  transition: var(--transition-fast);
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
  box-shadow: 0 0 24px rgba(var(--accent-rgb), 0.3);
  transition: var(--transition-fast);
}

.drop-content {
  pointer-events: none;
}

.drop-icon {
  font-size: 3rem;
  margin-bottom: var(--spacing-md);
  animation: pulse 2s ease-in-out infinite;
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
  min-height: 420px;
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
  overflow: hidden;
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
  font-size: 1rem;
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
  font-size: 0.875rem;
  font-weight: 500;
  min-height: 40px;
}

.view-toggle:hover {
  background: var(--glass-overlay);
  border-color: var(--accent);
}

.dropdown-arrow {
  font-size: 0.7rem;
  color: var(--text-secondary);
}

.view-menu {
  position: absolute;
  top: calc(100% + var(--spacing-xs));
  right: 0;
  min-width: 160px;
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
  font-size: 0.875rem;
  min-height: 40px;
}

.view-option:hover {
  background: var(--glass-overlay);
}

.view-option.active {
  background: rgba(var(--accent-rgb), 0.2);
  color: var(--accent);
  font-weight: 600;
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
  min-height: 44px;
}

.select-all-label {
  color: var(--text-secondary);
  font-size: 0.875rem;
  user-select: none;
}

.selection-count {
  color: var(--text-tertiary);
  font-size: 0.75rem;
  margin-left: auto;
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
  align-items: center;
  flex-wrap: wrap;
}

.btn {
  padding: var(--spacing-sm) var(--spacing-md);
  border-radius: var(--radius-md);
  border: none;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-xs);
  min-height: 40px;
}

.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--accent);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-hover);
  transform: scale(1.05);
  filter: brightness(1.1);
}

.btn-danger {
  background: var(--danger);
  color: white;
}

.btn-danger:hover:not(:disabled) {
  filter: brightness(1.1);
  transform: scale(1.05);
}

.btn-secondary {
  background: var(--glass-overlay-thin);
  color: var(--text-primary);
  border: 1px solid var(--glass-border);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--glass-overlay);
  border-color: var(--accent);
}

.auto-refresh {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  color: var(--text-secondary);
  font-size: 0.875rem;
  cursor: pointer;
  user-select: none;
  min-height: 40px;
}

.auto-refresh input {
  accent-color: var(--accent);
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
  margin: 0;
}

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

.file-list-empty {
  text-align: center;
  padding: var(--spacing-xl);
  color: var(--text-secondary);
  font-size: 0.875rem;
}

.file-item {
  background: var(--glass-overlay-thin);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  transition: var(--transition-fast);
}

.file-item:hover {
  background: var(--glass-overlay);
}

.file-item.selected {
  background: rgba(var(--accent-rgb), 0.1);
  border-color: var(--accent);
  box-shadow: 0 0 12px rgba(var(--accent-rgb), 0.15);
}

.file-checkbox {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
}

.file-icon {
  flex-shrink: 0;
  font-size: 1.5rem;
  text-align: center;
}

.file-name {
  color: var(--text-primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.file-meta {
  color: var(--text-secondary);
  font-size: 0.75rem;
  display: flex;
  gap: var(--spacing-xs);
  align-items: center;
  flex-wrap: wrap;
  min-width: 0;
}

.file-menu-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: var(--spacing-xs);
  border-radius: var(--radius-sm);
  font-size: 1.25rem;
  line-height: 1;
  min-width: 40px;
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.file-menu-btn:hover {
  background: var(--glass-overlay);
  color: var(--text-primary);
}

.file-thumb {
  width: 100%;
  height: 110px;
  object-fit: cover;
  border-radius: var(--radius-sm);
  margin-bottom: var(--spacing-sm);
}

/* ===== File List: List View (Default) ===== */
.file-list[data-view="list"] .file-item {
  display: grid;
  grid-template-columns: auto auto 1fr auto;
  gap: var(--spacing-md);
  align-items: center;
  padding: var(--spacing-md);
}

.file-list[data-view="list"] .file-item:hover {
  transform: translateX(4px);
}

.file-list[data-view="list"] .file-info {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  min-width: 0;
}

/* ===== File List: Detail View ===== */
.file-list[data-view="detail"] .file-item {
  display: grid;
  grid-template-columns: auto auto 1fr auto;
  gap: var(--spacing-lg);
  align-items: center;
  padding: var(--spacing-lg);
}

.file-list[data-view="detail"] .file-item:hover {
  transform: translateX(4px);
}

.file-list[data-view="detail"] .file-icon {
  font-size: 2rem;
}

.file-list[data-view="detail"] .file-info {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  min-width: 0;
}

.file-list[data-view="detail"] .file-name {
  font-size: 1rem;
}

.file-list[data-view="detail"] .file-meta {
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
}

.file-list[data-view="cards"] .file-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--spacing-md);
  text-align: center;
  position: relative;
  min-height: 180px;
}

.file-list[data-view="cards"] .file-item:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-hover);
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
  margin: var(--spacing-lg) 0 var(--spacing-sm);
}

.file-list[data-view="cards"] .file-name {
  font-size: 0.875rem;
  width: 100%;
}

.file-list[data-view="cards"] .file-meta {
  font-size: 0.75rem;
  justify-content: center;
}

/* ===== File List: Compact View ===== */
.file-list[data-view="compact"] .file-item {
  display: grid;
  grid-template-columns: auto auto 1fr auto auto auto;
  gap: var(--spacing-sm);
  align-items: center;
  padding: var(--spacing-sm) var(--spacing-md);
  min-height: 48px;
}

.file-list[data-view="compact"] .file-icon {
  font-size: 1.25rem;
}

.file-list[data-view="compact"] .file-meta {
  font-size: 0.75rem;
  white-space: nowrap;
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
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  width: 100%;
  padding: var(--spacing-sm) var(--spacing-md);
  background: transparent;
  border: none;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  border-radius: var(--radius-sm);
  font-size: 0.875rem;
  min-height: 40px;
}

.context-menu-item:hover {
  background: var(--glass-overlay);
}

.context-menu-item.danger {
  color: var(--danger);
}

.context-menu-item.danger:hover {
  background: rgba(239, 68, 68, 0.12);
}

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
  gap: var(--spacing-sm);
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
  height: 6px;
  background: var(--glass-overlay);
  border-radius: 3px;
  overflow: hidden;
}

.queue-progress-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--accent) 0%, var(--accent-hover) 100%);
  border-radius: 3px;
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
  width: 40%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.35), transparent);
  animation: shimmer 1.5s infinite;
}

@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(300%); }
}

.queue-speed {
  color: var(--text-secondary);
  font-size: 0.75rem;
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
  align-items: center;
  gap: var(--spacing-sm);
  pointer-events: none;
  width: min(420px, calc(100vw - var(--spacing-lg) * 2));
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
  font-weight: 500;
  box-shadow: var(--shadow-hover);
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  animation: toast-in 0.3s ease;
  pointer-events: auto;
}

.toast.success { border-left: 3px solid var(--success); }
.toast.error { border-left: 3px solid var(--danger); }
.toast.info { border-left: 3px solid var(--accent); }

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
  background: rgba(0, 0, 0, 0.88);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  z-index: var(--z-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--spacing-lg);
  animation: fade-in 0.3s ease;
  cursor: pointer;
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
  width: 44px;
  height: 44px;
  color: white;
  font-size: 1.4rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: calc(var(--z-overlay) + 1);
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
  cursor: default;
}

/* ===== QR Section ===== */
.qr-section {
  padding: var(--spacing-lg);
  text-align: center;
  margin-top: auto;
  position: relative;
  z-index: var(--z-content);
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

/* ===== Skip Link ===== */
.skip-link {
  position: absolute;
  top: -40px;
  left: var(--spacing-md);
  background: var(--accent);
  color: white;
  padding: var(--spacing-sm) var(--spacing-md);
  border-radius: var(--radius-sm);
  z-index: 10000;
  font-size: 0.875rem;
  font-weight: 600;
}

.skip-link:focus {
  top: var(--spacing-md);
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

/* ===== Responsive ===== */
@media (min-width: 768px) and (max-width: 1023px) {
  .drop-zone {
    min-height: 260px;
  }
}

@media (min-width: 1024px) {
  .main-grid {
    grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
  }
}

@media (max-width: 767px) {
  body {
    padding: var(--spacing-md);
    gap: var(--spacing-md);
  }

  .glass-header {
    padding: var(--spacing-sm) var(--spacing-md);
    height: 56px;
  }

  .logo, .brand-logo {
    font-size: 1.25rem;
  }

  .stats-row {
    grid-template-columns: 1fr;
    gap: var(--spacing-sm);
  }

  .stat-card {
    padding: var(--spacing-md);
    display: flex;
    align-items: center;
    gap: var(--spacing-md);
    text-align: left;
  }

  .stat-icon {
    font-size: 1.5rem;
    margin-bottom: 0;
  }

  .stat-value {
    font-size: 1.25rem;
    margin-bottom: 0;
  }

  .drop-zone {
    min-height: 200px;
    padding: var(--spacing-lg);
  }

  .drop-icon {
    font-size: 2.25rem;
  }

  .file-list[data-view="cards"] {
    grid-template-columns: repeat(2, 1fr);
  }

  .upload-queue {
    bottom: var(--spacing-md);
    right: var(--spacing-md);
    left: var(--spacing-md);
    width: auto;
    max-width: none;
  }

  .qr-container canvas {
    max-width: 150px;
  }

  .toast-container {
    top: var(--spacing-md);
    width: calc(100vw - var(--spacing-lg) * 2);
  }
}
</style>
</head>
<body data-theme="dark">

<!-- Lucide icon sprite -->
<svg xmlns="http://www.w3.org/2000/svg" class="icon-sprite" aria-hidden="true">
  <symbol id="i-moon" viewBox="0 0 24 24"><path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"/></symbol>
  <symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></symbol>
  <symbol id="i-folder" viewBox="0 0 24 24"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></symbol>
  <symbol id="i-save" viewBox="0 0 24 24"><path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/><path d="M7 3v4a1 1 0 0 0 1 1h7"/></symbol>
  <symbol id="i-timer" viewBox="0 0 24 24"><line x1="10" x2="14" y1="2" y2="2"/><line x1="12" x2="15" y1="14" y2="11"/><circle cx="12" cy="14" r="8"/></symbol>
  <symbol id="i-upload" viewBox="0 0 24 24"><path d="M12 3v12"/><path d="m17 8-5-5-5 5"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/></symbol>
  <symbol id="i-download" viewBox="0 0 24 24"><path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/></symbol>
  <symbol id="i-link" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></symbol>
  <symbol id="i-eye" viewBox="0 0 24 24"><path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/></symbol>
  <symbol id="i-trash-2" viewBox="0 0 24 24"><path d="M10 11v6"/><path d="M14 11v6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></symbol>
  <symbol id="i-refresh-cw" viewBox="0 0 24 24"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></symbol>
  <symbol id="i-x" viewBox="0 0 24 24"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></symbol>
  <symbol id="i-chevron-down" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></symbol>
  <symbol id="i-ellipsis-vertical" viewBox="0 0 24 24"><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></symbol>
  <symbol id="i-check" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></symbol>
  <symbol id="i-circle-x" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/></symbol>
  <symbol id="i-triangle-alert" viewBox="0 0 24 24"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></symbol>
  <symbol id="i-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></symbol>
  <symbol id="i-file" viewBox="0 0 24 24"><path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/></symbol>
  <symbol id="i-file-text" viewBox="0 0 24 24"><path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/></symbol>
  <symbol id="i-file-spreadsheet" viewBox="0 0 24 24"><path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="M8 13h2"/><path d="M14 13h2"/><path d="M8 17h2"/><path d="M14 17h2"/></symbol>
  <symbol id="i-music" viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></symbol>
  <symbol id="i-film" viewBox="0 0 24 24"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 3v18"/><path d="M3 7.5h4"/><path d="M3 12h18"/><path d="M3 16.5h4"/><path d="M17 3v18"/><path d="M17 7.5h4"/><path d="M17 16.5h4"/></symbol>
  <symbol id="i-image" viewBox="0 0 24 24"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/></symbol>
  <symbol id="i-archive" viewBox="0 0 24 24"><rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/></symbol>
  <symbol id="i-file-code" viewBox="0 0 24 24"><path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="M10 12.5 8 15l2 2.5"/><path d="m14 12.5 2 2.5-2 2.5"/></symbol>
  <symbol id="i-globe" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/></symbol>
  <symbol id="i-file-json" viewBox="0 0 24 24"><path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="M10 12a1 1 0 0 0-1 1v1a1 1 0 0 1-1 1 1 1 0 0 1 1 1v1a1 1 0 0 0 1 1"/><path d="M14 18a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1 1 1 0 0 1-1-1v-1a1 1 0 0 0-1-1"/></symbol>
  <symbol id="i-app-window" viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M10 4v4"/><path d="M2 8h20"/><path d="M6 4v4"/></symbol>
  <symbol id="i-smartphone" viewBox="0 0 24 24"><rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/></symbol>
</svg>

<a href="#main-content" class="skip-link">Skip to main content</a>

<!-- Animated background canvas -->
<div class="aurora" aria-hidden="true">
  <div class="aurora-blob aurora-blob-1"></div>
  <div class="aurora-blob aurora-blob-2"></div>
  <div class="aurora-blob aurora-blob-3"></div>
</div>

<!-- Header -->
<header class="glass-card glass-header">
  <div class="brand">
    <span class="brand-logo" aria-hidden="true">◎</span>
    <h1 class="logo">Local Drop</h1>
  </div>
  <div class="header-actions">
    <button id="theme-toggle" class="theme-toggle" aria-label="Toggle dark/light mode" title="Toggle theme (Ctrl+T)">
      <span id="theme-icon" class="theme-icon" aria-hidden="true"><svg class="lucide-icon"><use href="#i-moon"></use></svg></span>
    </button>
  </div>
</header>

<!-- Stats row -->
<section class="stats-row" aria-label="Server statistics">
  <div class="glass-card stat-card glass-card-hover">
    <div class="stat-icon" aria-hidden="true"><svg class="lucide-icon"><use href="#i-folder"></use></svg></div>
    <div><div class="stat-value" id="stat-files" aria-live="polite">0</div>
    <div class="stat-label">Files</div></div>
  </div>
  <div class="glass-card stat-card glass-card-hover">
    <div class="stat-icon" aria-hidden="true"><svg class="lucide-icon"><use href="#i-save"></use></svg></div>
    <div><div class="stat-value" id="stat-size" aria-live="polite">0 B</div>
    <div class="stat-label">Total Size</div></div>
  </div>
  <div class="glass-card stat-card glass-card-hover">
    <div class="stat-icon" aria-hidden="true"><svg class="lucide-icon"><use href="#i-timer"></use></svg></div>
    <div><div class="stat-value" id="stat-recent" aria-live="polite">—</div>
    <div class="stat-label">Recent</div></div>
  </div>
</section>

<!-- Main grid -->
<main class="main-grid" id="main-content" tabindex="-1">

  <!-- Drop zone -->
  <section class="glass-card drop-zone" id="drop-zone" role="button" tabindex="0" aria-label="Upload files - drag and drop or click to choose">
    <input type="file" id="file-input" multiple hidden aria-label="Choose files to upload">
    <div class="drop-content">
      <div class="drop-icon" aria-hidden="true"><svg class="lucide-icon"><use href="#i-upload"></use></svg></div>
      <p class="drop-text">Drag files here</p>
      <p class="drop-subtext">or click to upload</p>
    </div>
  </section>

  <!-- File list -->
  <section class="glass-card file-section" aria-label="Shared files">
    <div class="file-header">
      <div class="search-container">
        <input type="search" id="search-input" class="search-input" placeholder="Search files..." aria-label="Search files" autocomplete="off" spellcheck="false">
        <button id="clear-search" class="clear-search" aria-label="Clear search" hidden><svg class="lucide-icon"><use href="#i-x"></use></svg></button>
      </div>

      <div class="view-toggle-container">
        <button id="view-toggle" class="view-toggle" aria-label="Change file view layout" aria-haspopup="menu" aria-expanded="false">
          <span id="view-label">List</span>
          <span class="dropdown-arrow" aria-hidden="true"><svg class="lucide-icon"><use href="#i-chevron-down"></use></svg></span>
        </button>
        <div id="view-menu" class="view-menu glass-card" role="menu" aria-label="View layouts" hidden>
          <button class="view-option active" data-view="list" role="menuitemradio" aria-checked="true">List</button>
          <button class="view-option" data-view="detail" role="menuitemradio" aria-checked="false">Detail</button>
          <button class="view-option" data-view="cards" role="menuitemradio" aria-checked="false">Cards</button>
          <button class="view-option" data-view="compact" role="menuitemradio" aria-checked="false">Compact</button>
        </div>
      </div>
    </div>

    <div class="bulk-actions">
      <label class="select-all-container">
        <input type="checkbox" id="select-all" aria-label="Select all files">
        <span class="select-all-label">Select All</span>
      </label>
      <span class="selection-count" id="selection-count" aria-live="polite"></span>
      <div class="bulk-buttons">
        <button id="bulk-download" class="btn btn-primary" disabled aria-label="Download selected files as ZIP"><svg class="lucide-icon"><use href="#i-download"></use></svg> ZIP</button>
        <button id="bulk-delete" class="btn btn-danger" disabled aria-label="Delete selected files"><svg class="lucide-icon"><use href="#i-trash-2"></use></svg> Delete</button>
        <button id="refresh-btn" class="btn btn-secondary" aria-label="Refresh file list" title="Refresh (Ctrl+R)"><svg class="lucide-icon"><use href="#i-refresh-cw"></use></svg></button>
        <label class="auto-refresh">
          <input type="checkbox" id="auto-refresh" aria-label="Enable auto-refresh">
          <span>Auto</span>
        </label>
      </div>
    </div>

    <ul id="file-list" class="file-list" data-view="list" role="list" aria-label="Shared files"></ul>
  </section>

</main>

<!-- Upload queue (hidden initially) -->
<aside id="upload-queue" class="upload-queue glass-card" hidden aria-live="polite" aria-label="Upload progress">
  <h3 class="queue-title">Uploading…</h3>
  <div id="queue-items" class="queue-items"></div>
</aside>

<!-- QR Code section -->
<footer class="glass-card qr-section">
  <p class="qr-label">Scan to connect from mobile</p>
  <div id="qr-container" class="qr-container"></div>
</footer>

<!-- Toast notifications container -->
<div id="toast-container" class="toast-container" aria-live="polite" aria-atomic="false"></div>

<!-- Context menu -->
<div id="context-menu" class="context-menu glass-card" hidden role="menu" aria-label="File actions"></div>

<!-- Preview overlay -->
<div id="preview-overlay" class="preview-overlay" hidden role="dialog" aria-modal="true" aria-label="Image preview">
  <button id="preview-close" class="preview-close" aria-label="Close preview"><svg class="lucide-icon"><use href="#i-x"></use></svg></button>
  <img id="preview-image" class="preview-image" alt="Image preview">
</div>

<script>
/*! QRious v4.0.2 | (C) 2017 Alasdair Mercer | GPL v3 License
Based on jsqrencode | (C) 2010 tz@execpc.com | GPL v3 License
*/
!function(t,e){"object"==typeof exports&&"undefined"!=typeof module?module.exports=e():"function"==typeof define&&define.amd?define(e):t.QRious=e()}(this,function(){"use strict";function t(t,e){var n;return"function"==typeof Object.create?n=Object.create(t):(s.prototype=t,n=new s,s.prototype=null),e&&i(!0,n,e),n}function e(e,n,s,r){var o=this;return"string"!=typeof e&&(r=s,s=n,n=e,e=null),"function"!=typeof n&&(r=s,s=n,n=function(){return o.apply(this,arguments)}),i(!1,n,o,r),n.prototype=t(o.prototype,s),n.prototype.constructor=n,n.class_=e||o.class_,n.super_=o,n}function i(t,e,i){for(var n,s,a=0,h=(i=o.call(arguments,2)).length;a<h;a++){s=i[a];for(n in s)t&&!r.call(s,n)||(e[n]=s[n])}}function n(){}var s=function(){},r=Object.prototype.hasOwnProperty,o=Array.prototype.slice,a=e;n.class_="Nevis",n.super_=Object,n.extend=a;var h=n,f=h.extend(function(t,e,i){this.qrious=t,this.element=e,this.element.qrious=t,this.enabled=Boolean(i)},{draw:function(t){},getElement:function(){return this.enabled||(this.enabled=!0,this.render()),this.element},getModuleSize:function(t){var e=this.qrious,i=e.padding||0,n=Math.floor((e.size-2*i)/t.width);return Math.max(1,n)},getOffset:function(t){var e=this.qrious,i=e.padding;if(null!=i)return i;var n=this.getModuleSize(t),s=Math.floor((e.size-n*t.width)/2);return Math.max(0,s)},render:function(t){this.enabled&&(this.resize(),this.reset(),this.draw(t))},reset:function(){},resize:function(){}}),c=f.extend({draw:function(t){var e,i,n=this.qrious,s=this.getModuleSize(t),r=this.getOffset(t),o=this.element.getContext("2d");for(o.fillStyle=n.foreground,o.globalAlpha=n.foregroundAlpha,e=0;e<t.width;e++)for(i=0;i<t.width;i++)t.buffer[i*t.width+e]&&o.fillRect(s*e+r,s*i+r,s,s)},reset:function(){var t=this.qrious,e=this.element.getContext("2d"),i=t.size;e.lineWidth=1,e.clearRect(0,0,i,i),e.fillStyle=t.background,e.globalAlpha=t.backgroundAlpha,e.fillRect(0,0,i,i)},resize:function(){var t=this.element;t.width=t.height=this.qrious.size}}),u=h.extend(null,{BLOCK:[0,11,15,19,23,27,31,16,18,20,22,24,26,28,20,22,24,24,26,28,28,22,24,24,26,26,28,28,24,24,26,26,26,28,28,24,26,26,26,28,28]}),l=h.extend(null,{BLOCKS:[1,0,19,7,1,0,16,10,1,0,13,13,1,0,9,17,1,0,34,10,1,0,28,16,1,0,22,22,1,0,16,28,1,0,55,15,1,0,44,26,2,0,17,18,2,0,13,22,1,0,80,20,2,0,32,18,2,0,24,26,4,0,9,16,1,0,108,26,2,0,43,24,2,2,15,18,2,2,11,22,2,0,68,18,4,0,27,16,4,0,19,24,4,0,15,28,2,0,78,20,4,0,31,18,2,4,14,18,4,1,13,26,2,0,97,24,2,2,38,22,4,2,18,22,4,2,14,26,2,0,116,30,3,2,36,22,4,4,16,20,4,4,12,24,2,2,68,18,4,1,43,26,6,2,19,24,6,2,15,28,4,0,81,20,1,4,50,30,4,4,22,28,3,8,12,24,2,2,92,24,6,2,36,22,4,6,20,26,7,4,14,28,4,0,107,26,8,1,37,22,8,4,20,24,12,4,11,22,3,1,115,30,4,5,40,24,11,5,16,20,11,5,12,24,5,1,87,22,5,5,41,24,5,7,24,30,11,7,12,24,5,1,98,24,7,3,45,28,15,2,19,24,3,13,15,30,1,5,107,28,10,1,46,28,1,15,22,28,2,17,14,28,5,1,120,30,9,4,43,26,17,1,22,28,2,19,14,28,3,4,113,28,3,11,44,26,17,4,21,26,9,16,13,26,3,5,107,28,3,13,41,26,15,5,24,30,15,10,15,28,4,4,116,28,17,0,42,26,17,6,22,28,19,6,16,30,2,7,111,28,17,0,46,28,7,16,24,30,34,0,13,24,4,5,121,30,4,14,47,28,11,14,24,30,16,14,15,30,6,4,117,30,6,14,45,28,11,16,24,30,30,2,16,30,8,4,106,26,8,13,47,28,7,22,24,30,22,13,15,30,10,2,114,28,19,4,46,28,28,6,22,28,33,4,16,30,8,4,122,30,22,3,45,28,8,26,23,30,12,28,15,30,3,10,117,30,3,23,45,28,4,31,24,30,11,31,15,30,7,7,116,30,21,7,45,28,1,37,23,30,19,26,15,30,5,10,115,30,19,10,47,28,15,25,24,30,23,25,15,30,13,3,115,30,2,29,46,28,42,1,24,30,23,28,15,30,17,0,115,30,10,23,46,28,10,35,24,30,19,35,15,30,17,1,115,30,14,21,46,28,29,19,24,30,11,46,15,30,13,6,115,30,14,23,46,28,44,7,24,30,59,1,16,30,12,7,121,30,12,26,47,28,39,14,24,30,22,41,15,30,6,14,121,30,6,34,47,28,46,10,24,30,2,64,15,30,17,4,122,30,29,14,46,28,49,10,24,30,24,46,15,30,4,18,122,30,13,32,46,28,48,14,24,30,42,32,15,30,20,4,117,30,40,7,47,28,43,22,24,30,10,67,15,30,19,6,118,30,18,31,47,28,34,34,24,30,20,61,15,30],FINAL_FORMAT:[30660,29427,32170,30877,26159,25368,27713,26998,21522,20773,24188,23371,17913,16590,20375,19104,13663,12392,16177,14854,9396,8579,11994,11245,5769,5054,7399,6608,1890,597,3340,2107],LEVELS:{L:1,M:2,Q:3,H:4}}),_=h.extend(null,{EXPONENT:[1,2,4,8,16,32,64,128,29,58,116,232,205,135,19,38,76,152,45,90,180,117,234,201,143,3,6,12,24,48,96,192,157,39,78,156,37,74,148,53,106,212,181,119,238,193,159,35,70,140,5,10,20,40,80,160,93,186,105,210,185,111,222,161,95,190,97,194,153,47,94,188,101,202,137,15,30,60,120,240,253,231,211,187,107,214,177,127,254,225,223,163,91,182,113,226,217,175,67,134,17,34,68,136,13,26,52,104,208,189,103,206,129,31,62,124,248,237,199,147,59,118,236,197,151,51,102,204,133,23,46,92,184,109,218,169,79,158,33,66,132,21,42,84,168,77,154,41,82,164,85,170,73,146,57,114,228,213,183,115,230,209,191,99,198,145,63,126,252,229,215,179,123,246,241,255,227,219,171,75,150,49,98,196,149,55,110,220,165,87,174,65,130,25,50,100,200,141,7,14,28,56,112,224,221,167,83,166,81,162,89,178,121,242,249,239,195,155,43,86,172,69,138,9,18,36,72,144,61,122,244,245,247,243,251,235,203,139,11,22,44,88,176,125,250,233,207,131,27,54,108,216,173,71,142,0],LOG:[255,0,1,25,2,50,26,198,3,223,51,238,27,104,199,75,4,100,224,14,52,141,239,129,28,193,105,248,200,8,76,113,5,138,101,47,225,36,15,33,53,147,142,218,240,18,130,69,29,181,194,125,106,39,249,185,201,154,9,120,77,228,114,166,6,191,139,98,102,221,48,253,226,152,37,179,16,145,34,136,54,208,148,206,143,150,219,189,241,210,19,92,131,56,70,64,30,66,182,163,195,72,126,110,107,58,40,84,250,133,186,61,202,94,155,159,10,21,121,43,78,212,229,172,115,243,167,87,7,112,192,247,140,128,99,13,103,74,222,237,49,197,254,24,227,165,153,119,38,184,180,124,17,68,146,217,35,32,137,46,55,63,209,91,149,188,207,205,144,135,151,178,220,252,190,97,242,86,211,171,20,42,93,158,132,60,57,83,71,109,65,162,31,45,67,216,183,123,164,118,196,23,73,236,127,12,111,246,108,161,59,82,41,157,85,170,251,96,134,177,187,204,62,90,203,89,95,176,156,169,160,81,11,245,22,235,122,117,44,215,79,174,213,233,230,231,173,232,116,214,244,234,168,80,88,175]}),d=h.extend(null,{BLOCK:[3220,1468,2713,1235,3062,1890,2119,1549,2344,2936,1117,2583,1330,2470,1667,2249,2028,3780,481,4011,142,3098,831,3445,592,2517,1776,2234,1951,2827,1070,2660,1345,3177]}),v=h.extend(function(t){var e,i,n,s,r,o=t.value.length;for(this._badness=[],this._level=l.LEVELS[t.level],this._polynomial=[],this._value=t.value,this._version=0,this._stringBuffer=[];this._version<40&&(this._version++,n=4*(this._level-1)+16*(this._version-1),s=l.BLOCKS[n++],r=l.BLOCKS[n++],e=l.BLOCKS[n++],i=l.BLOCKS[n],n=e*(s+r)+r-3+(this._version<=9),!(o<=n)););this._dataBlock=e,this._eccBlock=i,this._neccBlock1=s,this._neccBlock2=r;var a=this.width=17+4*this._version;this.buffer=v._createArray(a*a),this._ecc=v._createArray(e+(e+i)*(s+r)+r),this._mask=v._createArray((a*(a+1)+1)/2),this._insertFinders(),this._insertAlignments(),this.buffer[8+a*(a-8)]=1,this._insertTimingGap(),this._reverseMask(),this._insertTimingRowAndColumn(),this._insertVersion(),this._syncMask(),this._convertBitStream(o),this._calculatePolynomial(),this._appendEccToData(),this._interleaveBlocks(),this._pack(),this._finish()},{_addAlignment:function(t,e){var i,n=this.buffer,s=this.width;for(n[t+s*e]=1,i=-2;i<2;i++)n[t+i+s*(e-2)]=1,n[t-2+s*(e+i+1)]=1,n[t+2+s*(e+i)]=1,n[t+i+1+s*(e+2)]=1;for(i=0;i<2;i++)this._setMask(t-1,e+i),this._setMask(t+1,e-i),this._setMask(t-i,e-1),this._setMask(t+i,e+1)},_appendData:function(t,e,i,n){var s,r,o,a=this._polynomial,h=this._stringBuffer;for(r=0;r<n;r++)h[i+r]=0;for(r=0;r<e;r++){if(255!==(s=_.LOG[h[t+r]^h[i]]))for(o=1;o<n;o++)h[i+o-1]=h[i+o]^_.EXPONENT[v._modN(s+a[n-o])];else for(o=i;o<i+n;o++)h[o]=h[o+1];h[i+n-1]=255===s?0:_.EXPONENT[v._modN(s+a[0])]}},_appendEccToData:function(){var t,e=0,i=this._dataBlock,n=this._calculateMaxLength(),s=this._eccBlock;for(t=0;t<this._neccBlock1;t++)this._appendData(e,i,n,s),e+=i,n+=s;for(t=0;t<this._neccBlock2;t++)this._appendData(e,i+1,n,s),e+=i+1,n+=s},_applyMask:function(t){var e,i,n,s,r=this.buffer,o=this.width;switch(t){case 0:for(s=0;s<o;s++)for(n=0;n<o;n++)n+s&1||this._isMasked(n,s)||(r[n+s*o]^=1);break;case 1:for(s=0;s<o;s++)for(n=0;n<o;n++)1&s||this._isMasked(n,s)||(r[n+s*o]^=1);break;case 2:for(s=0;s<o;s++)for(e=0,n=0;n<o;n++,e++)3===e&&(e=0),e||this._isMasked(n,s)||(r[n+s*o]^=1);break;case 3:for(i=0,s=0;s<o;s++,i++)for(3===i&&(i=0),e=i,n=0;n<o;n++,e++)3===e&&(e=0),e||this._isMasked(n,s)||(r[n+s*o]^=1);break;case 4:for(s=0;s<o;s++)for(e=0,i=s>>1&1,n=0;n<o;n++,e++)3===e&&(e=0,i=!i),i||this._isMasked(n,s)||(r[n+s*o]^=1);break;case 5:for(i=0,s=0;s<o;s++,i++)for(3===i&&(i=0),e=0,n=0;n<o;n++,e++)3===e&&(e=0),(n&s&1)+!(!e|!i)||this._isMasked(n,s)||(r[n+s*o]^=1);break;case 6:for(i=0,s=0;s<o;s++,i++)for(3===i&&(i=0),e=0,n=0;n<o;n++,e++)3===e&&(e=0),(n&s&1)+(e&&e===i)&1||this._isMasked(n,s)||(r[n+s*o]^=1);break;case 7:for(i=0,s=0;s<o;s++,i++)for(3===i&&(i=0),e=0,n=0;n<o;n++,e++)3===e&&(e=0),(e&&e===i)+(n+s&1)&1||this._isMasked(n,s)||(r[n+s*o]^=1)}},_calculateMaxLength:function(){return this._dataBlock*(this._neccBlock1+this._neccBlock2)+this._neccBlock2},_calculatePolynomial:function(){var t,e,i=this._eccBlock,n=this._polynomial;for(n[0]=1,t=0;t<i;t++){for(n[t+1]=1,e=t;e>0;e--)n[e]=n[e]?n[e-1]^_.EXPONENT[v._modN(_.LOG[n[e]]+t)]:n[e-1];n[0]=_.EXPONENT[v._modN(_.LOG[n[0]]+t)]}for(t=0;t<=i;t++)n[t]=_.LOG[n[t]]},_checkBadness:function(){var t,e,i,n,s,r=0,o=this._badness,a=this.buffer,h=this.width;for(s=0;s<h-1;s++)for(n=0;n<h-1;n++)(a[n+h*s]&&a[n+1+h*s]&&a[n+h*(s+1)]&&a[n+1+h*(s+1)]||!(a[n+h*s]||a[n+1+h*s]||a[n+h*(s+1)]||a[n+1+h*(s+1)]))&&(r+=v.N2);var f=0;for(s=0;s<h;s++){for(i=0,o[0]=0,t=0,n=0;n<h;n++)t===(e=a[n+h*s])?o[i]++:o[++i]=1,f+=(t=e)?1:-1;r+=this._getBadness(i)}f<0&&(f=-f);var c=0,u=f;for(u+=u<<2,u<<=1;u>h*h;)u-=h*h,c++;for(r+=c*v.N4,n=0;n<h;n++){for(i=0,o[0]=0,t=0,s=0;s<h;s++)t===(e=a[n+h*s])?o[i]++:o[++i]=1,t=e;r+=this._getBadness(i)}return r},_convertBitStream:function(t){var e,i,n=this._ecc,s=this._version;for(i=0;i<t;i++)n[i]=this._value.charCodeAt(i);var r=this._stringBuffer=n.slice(),o=this._calculateMaxLength();t>=o-2&&(t=o-2,s>9&&t--);var a=t;if(s>9){for(r[a+2]=0,r[a+3]=0;a--;)e=r[a],r[a+3]|=255&e<<4,r[a+2]=e>>4;r[2]|=255&t<<4,r[1]=t>>4,r[0]=64|t>>12}else{for(r[a+1]=0,r[a+2]=0;a--;)e=r[a],r[a+2]|=255&e<<4,r[a+1]=e>>4;r[1]|=255&t<<4,r[0]=64|t>>4}for(a=t+3-(s<10);a<o;)r[a++]=236,r[a++]=17},_getBadness:function(t){var e,i=0,n=this._badness;for(e=0;e<=t;e++)n[e]>=5&&(i+=v.N1+n[e]-5);for(e=3;e<t-1;e+=2)n[e-2]===n[e+2]&&n[e+2]===n[e-1]&&n[e-1]===n[e+1]&&3*n[e-1]===n[e]&&(0===n[e-3]||e+3>t||3*n[e-3]>=4*n[e]||3*n[e+3]>=4*n[e])&&(i+=v.N3);return i},_finish:function(){this._stringBuffer=this.buffer.slice();var t,e,i=0,n=3e4;for(e=0;e<8&&(this._applyMask(e),(t=this._checkBadness())<n&&(n=t,i=e),7!==i);e++)this.buffer=this._stringBuffer.slice();i!==e&&this._applyMask(i),n=l.FINAL_FORMAT[i+(this._level-1<<3)];var s=this.buffer,r=this.width;for(e=0;e<8;e++,n>>=1)1&n&&(s[r-1-e+8*r]=1,e<6?s[8+r*e]=1:s[8+r*(e+1)]=1);for(e=0;e<7;e++,n>>=1)1&n&&(s[8+r*(r-7+e)]=1,e?s[6-e+8*r]=1:s[7+8*r]=1)},_interleaveBlocks:function(){var t,e,i=this._dataBlock,n=this._ecc,s=this._eccBlock,r=0,o=this._calculateMaxLength(),a=this._neccBlock1,h=this._neccBlock2,f=this._stringBuffer;for(t=0;t<i;t++){for(e=0;e<a;e++)n[r++]=f[t+e*i];for(e=0;e<h;e++)n[r++]=f[a*i+t+e*(i+1)]}for(e=0;e<h;e++)n[r++]=f[a*i+t+e*(i+1)];for(t=0;t<s;t++)for(e=0;e<a+h;e++)n[r++]=f[o+t+e*s];this._stringBuffer=n},_insertAlignments:function(){var t,e,i,n=this._version,s=this.width;if(n>1)for(t=u.BLOCK[n],i=s-7;;){for(e=s-7;e>t-3&&(this._addAlignment(e,i),!(e<t));)e-=t;if(i<=t+9)break;i-=t,this._addAlignment(6,i),this._addAlignment(i,6)}},_insertFinders:function(){var t,e,i,n,s=this.buffer,r=this.width;for(t=0;t<3;t++){for(e=0,n=0,1===t&&(e=r-7),2===t&&(n=r-7),s[n+3+r*(e+3)]=1,i=0;i<6;i++)s[n+i+r*e]=1,s[n+r*(e+i+1)]=1,s[n+6+r*(e+i)]=1,s[n+i+1+r*(e+6)]=1;for(i=1;i<5;i++)this._setMask(n+i,e+1),this._setMask(n+1,e+i+1),this._setMask(n+5,e+i),this._setMask(n+i+1,e+5);for(i=2;i<4;i++)s[n+i+r*(e+2)]=1,s[n+2+r*(e+i+1)]=1,s[n+4+r*(e+i)]=1,s[n+i+1+r*(e+4)]=1}},_insertTimingGap:function(){var t,e,i=this.width;for(e=0;e<7;e++)this._setMask(7,e),this._setMask(i-8,e),this._setMask(7,e+i-7);for(t=0;t<8;t++)this._setMask(t,7),this._setMask(t+i-8,7),this._setMask(t,i-8)},_insertTimingRowAndColumn:function(){var t,e=this.buffer,i=this.width;for(t=0;t<i-14;t++)1&t?(this._setMask(8+t,6),this._setMask(6,8+t)):(e[8+t+6*i]=1,e[6+i*(8+t)]=1)},_insertVersion:function(){var t,e,i,n,s=this.buffer,r=this._version,o=this.width;if(r>6)for(t=d.BLOCK[r-7],e=17,i=0;i<6;i++)for(n=0;n<3;n++,e--)1&(e>11?r>>e-12:t>>e)?(s[5-i+o*(2-n+o-11)]=1,s[2-n+o-11+o*(5-i)]=1):(this._setMask(5-i,2-n+o-11),this._setMask(2-n+o-11,5-i))},_isMasked:function(t,e){var i=v._getMaskBit(t,e);return 1===this._mask[i]},_pack:function(){var t,e,i,n=1,s=1,r=this.width,o=r-1,a=r-1,h=(this._dataBlock+this._eccBlock)*(this._neccBlock1+this._neccBlock2)+this._neccBlock2;for(e=0;e<h;e++)for(t=this._stringBuffer[e],i=0;i<8;i++,t<<=1){128&t&&(this.buffer[o+r*a]=1);do{s?o--:(o++,n?0!==a?a--:(n=!n,6===(o-=2)&&(o--,a=9)):a!==r-1?a++:(n=!n,6===(o-=2)&&(o--,a-=8))),s=!s}while(this._isMasked(o,a))}},_reverseMask:function(){var t,e,i=this.width;for(t=0;t<9;t++)this._setMask(t,8);for(t=0;t<8;t++)this._setMask(t+i-8,8),this._setMask(8,t);for(e=0;e<7;e++)this._setMask(8,e+i-7)},_setMask:function(t,e){var i=v._getMaskBit(t,e);this._mask[i]=1},_syncMask:function(){var t,e,i=this.width;for(e=0;e<i;e++)for(t=0;t<=e;t++)this.buffer[t+i*e]&&this._setMask(t,e)}},{_createArray:function(t){var e,i=[];for(e=0;e<t;e++)i[e]=0;return i},_getMaskBit:function(t,e){var i;return t>e&&(i=t,t=e,e=i),i=e,i+=e*e,i>>=1,i+=t},_modN:function(t){for(;t>=255;)t=((t-=255)>>8)+(255&t);return t},N1:3,N2:3,N3:40,N4:10}),p=v,m=f.extend({draw:function(){this.element.src=this.qrious.toDataURL()},reset:function(){this.element.src=""},resize:function(){var t=this.element;t.width=t.height=this.qrious.size}}),g=h.extend(function(t,e,i,n){this.name=t,this.modifiable=Boolean(e),this.defaultValue=i,this._valueTransformer=n},{transform:function(t){var e=this._valueTransformer;return"function"==typeof e?e(t,this):t}}),k=h.extend(null,{abs:function(t){return null!=t?Math.abs(t):null},hasOwn:function(t,e){return Object.prototype.hasOwnProperty.call(t,e)},noop:function(){},toUpperCase:function(t){return null!=t?t.toUpperCase():null}}),w=h.extend(function(t){this.options={},t.forEach(function(t){this.options[t.name]=t},this)},{exists:function(t){return null!=this.options[t]},get:function(t,e){return w._get(this.options[t],e)},getAll:function(t){var e,i=this.options,n={};for(e in i)k.hasOwn(i,e)&&(n[e]=w._get(i[e],t));return n},init:function(t,e,i){"function"!=typeof i&&(i=k.noop);var n,s;for(n in this.options)k.hasOwn(this.options,n)&&(s=this.options[n],w._set(s,s.defaultValue,e),w._createAccessor(s,e,i));this._setAll(t,e,!0)},set:function(t,e,i){return this._set(t,e,i)},setAll:function(t,e){return this._setAll(t,e)},_set:function(t,e,i,n){var s=this.options[t];if(!s)throw new Error("Invalid option: "+t);if(!s.modifiable&&!n)throw new Error("Option cannot be modified: "+t);return w._set(s,e,i)},_setAll:function(t,e,i){if(!t)return!1;var n,s=!1;for(n in t)k.hasOwn(t,n)&&this._set(n,t[n],e,i)&&(s=!0);return s}},{_createAccessor:function(t,e,i){var n={get:function(){return w._get(t,e)}};t.modifiable&&(n.set=function(n){w._set(t,n,e)&&i(n,t)}),Object.defineProperty(e,t.name,n)},_get:function(t,e){return e["_"+t.name]},_set:function(t,e,i){var n="_"+t.name,s=i[n],r=t.transform(null!=e?e:t.defaultValue);return i[n]=r,r!==s}}),M=w,b=h.extend(function(){this._services={}},{getService:function(t){var e=this._services[t];if(!e)throw new Error("Service is not being managed with name: "+t);return e},setService:function(t,e){if(this._services[t])throw new Error("Service is already managed with name: "+t);e&&(this._services[t]=e)}}),B=new M([new g("background",!0,"white"),new g("backgroundAlpha",!0,1,k.abs),new g("element"),new g("foreground",!0,"black"),new g("foregroundAlpha",!0,1,k.abs),new g("level",!0,"L",k.toUpperCase),new g("mime",!0,"image/png"),new g("padding",!0,null,k.abs),new g("size",!0,100,k.abs),new g("value",!0,"")]),y=new b,O=h.extend(function(t){B.init(t,this,this.update.bind(this));var e=B.get("element",this),i=y.getService("element"),n=e&&i.isCanvas(e)?e:i.createCanvas(),s=e&&i.isImage(e)?e:i.createImage();this._canvasRenderer=new c(this,n,!0),this._imageRenderer=new m(this,s,s===e),this.update()},{get:function(){return B.getAll(this)},set:function(t){B.setAll(t,this)&&this.update()},toDataURL:function(t){return this.canvas.toDataURL(t||this.mime)},update:function(){var t=new p({level:this.level,value:this.value});this._canvasRenderer.render(t),this._imageRenderer.render(t)}},{use:function(t){y.setService(t.getName(),t)}});Object.defineProperties(O.prototype,{canvas:{get:function(){return this._canvasRenderer.getElement()}},image:{get:function(){return this._imageRenderer.getElement()}}});var A=O,L=h.extend({getName:function(){}}).extend({createCanvas:function(){},createImage:function(){},getName:function(){return"element"},isCanvas:function(t){},isImage:function(t){}}).extend({createCanvas:function(){return document.createElement("canvas")},createImage:function(){return document.createElement("img")},isCanvas:function(t){return t instanceof HTMLCanvasElement},isImage:function(t){return t instanceof HTMLImageElement}});return A.use(new L),A});
// ===== Application State =====
const MAX_UPLOAD_BYTES = 512 * 1024 * 1024;

const state = {
  allFiles: [],
  selectedFiles: new Set(),
  searchQuery: '',
  currentView: 'list',
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

function parseModified(str) {
  // Accepts "24 Sep 2026, 14:30"; falls back to "HH:MM" style and raw string.
  const d = new Date(str);
  if (!isNaN(d.getTime())) return d;
  const m = str.match(/(\d{2})\/(\d{2})\/(\d{4}),\s*(\d{2}):(\d{2})/);
  if (m) return new Date(+m[3], +m[2] - 1, +m[1], +m[4], +m[5]);
  return new Date(str.replace(',', ''));
}

function formatTime(str) {
  if (!str) return '—';
  const date = parseModified(str);
  const now = new Date();
  const diffMs = now - date.getTime();
  if (isNaN(diffMs)) return str;
  if (diffMs < 60000) return 'Just now';
  const mins = Math.floor(diffMs / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString();
}

function getFileType(filename) {
  const ext = filename.split('.').pop().toLowerCase();
  const types = {
    pdf: 'PDF Document', doc: 'Word Document', docx: 'Word Document',
    xls: 'Excel Spreadsheet', xlsx: 'Excel Spreadsheet', xlsm: 'Excel Spreadsheet',
    csv: 'CSV File', png: 'PNG Image', jpg: 'JPEG Image', jpeg: 'JPEG Image',
    gif: 'GIF Image', webp: 'WEBP Image', svg: 'SVG Image', bmp: 'Bitmap Image',
    ico: 'Icon', mp4: 'MP4 Video', mkv: 'MKV Video', avi: 'AVI Video',
    mov: 'MOV Video', webm: 'WebM Video', mp3: 'MP3 Audio', wav: 'WAV Audio',
    flac: 'FLAC Audio', ogg: 'OGG Audio', m4a: 'M4A Audio',
    zip: 'ZIP Archive', rar: 'RAR Archive', '7z': '7-Zip Archive', tar: 'Tar Archive', gz: 'GZip Archive',
    txt: 'Text File', md: 'Markdown Document', log: 'Log File',
    json: 'JSON File', xml: 'XML File', yaml: 'YAML File', yml: 'YAML File',
    py: 'Python Script', js: 'JavaScript File', ts: 'TypeScript File',
    html: 'HTML Document', css: 'CSS Stylesheet',
    exe: 'Executable', msi: 'Installer', dmg: 'Disk Image', apk: 'Android App', ipa: 'iOS App'
  };
  return types[ext] || 'File';
}

// ===== Icon Helpers =====
function svgIcon(name) {
  const href = '#i-' + name;
  return '<svg class="lucide-icon" aria-hidden="true" focusable="false"><use href="' + href + '" xlink:href="' + href + '"></use></svg>';
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  const iconName = type === 'success' ? 'check' : type === 'error' ? 'circle-x' : type === 'warning' ? 'triangle-alert' : 'info';
  toast.innerHTML = svgIcon(iconName) + '<span>' + escapeHtml(message) + '</span>';
  toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('fade-out');
    setTimeout(() => toast.remove(), 300);
  }, 2000);
}

// ===== Theme Toggle System =====
let themeTransitionTimer = null;

function applyTheme(theme) {
  document.body.setAttribute('data-theme', theme);
  const icon = document.getElementById('theme-icon');
  if (icon) {
    const use = icon.querySelector('use');
    if (use) {
      const href = theme === 'light' ? '#i-sun' : '#i-moon';
      use.setAttribute('href', href);
      use.setAttribute('xlink:href', href);
    }
  }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', theme === 'light' ? '#e8e8e8' : '#0a0a0a');
  try { localStorage.setItem('theme', theme); } catch (e) {}
  window.dispatchEvent(new Event('themechange'));
}

function toggleTheme() {
  const current = document.body.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';

  // Snapshot the current background so we can ease out of it into the new mode.
  const computed = getComputedStyle(document.body);
  const fromStart = computed.getPropertyValue('--bg-gradient-start').trim() ||
    (current === 'dark' ? '#0a0a0a' : '#e8e8e8');
  const fromEnd = computed.getPropertyValue('--bg-gradient-end').trim() ||
    (current === 'dark' ? '#1a1a1a' : '#d5d5d5');

  if (themeTransitionTimer) {
    clearTimeout(themeTransitionTimer);
    document.body.classList.remove('theme-transition', 'theme-fading');
  }

  document.body.style.setProperty('--theme-fade-start', fromStart);
  document.body.style.setProperty('--theme-fade-end', fromEnd);
  document.body.classList.add('theme-transition');
  void document.body.offsetWidth;

  const toggle = document.getElementById('theme-toggle');
  if (toggle) {
    toggle.classList.remove('rotating');
    void toggle.offsetWidth;
    toggle.classList.add('rotating');
    setTimeout(() => toggle.classList.remove('rotating'), 450);
  }

  applyTheme(next);

  requestAnimationFrame(() => {
    document.body.classList.add('theme-fading');
  });

  themeTransitionTimer = setTimeout(() => {
    document.body.classList.remove('theme-transition', 'theme-fading');
    document.body.style.removeProperty('--theme-fade-start');
    document.body.style.removeProperty('--theme-fade-end');
    themeTransitionTimer = null;
  }, 520);
}

// ===== File Action Helpers =====
function downloadFile(filename) {
  const a = document.createElement('a');
  a.href = '/download/' + encodeURIComponent(filename);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  showToast(`Downloading ${filename}…`);
}

function copyLink(filename) {
  const url = location.origin + '/download/' + encodeURIComponent(filename);
  const textarea = document.createElement('textarea');
  textarea.value = url;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  document.body.appendChild(textarea);
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch (e) {}
  document.body.removeChild(textarea);
  showToast(ok ? 'Link copied to clipboard' : 'Copy failed', ok ? 'success' : 'error');
}

async function deleteFile(filename) {
  try {
    const response = await fetch('/api/files/' + encodeURIComponent(filename), { method: 'DELETE' });
    if (!response.ok) throw new Error('Failed to delete file');
    await loadFiles(true);
    showToast('File deleted', 'success');
  } catch (error) {
    console.error('Delete error:', error);
    showToast('Failed to delete file', 'error');
  }
}

function showPreview(url) {
  const overlay = document.getElementById('preview-overlay');
  const image = document.getElementById('preview-image');
  if (!overlay || !image) return;
  image.src = url;
  overlay.hidden = false;
  document.body.style.overflow = 'hidden';
}

function hidePreview() {
  const overlay = document.getElementById('preview-overlay');
  const image = document.getElementById('preview-image');
  if (overlay) overlay.hidden = true;
  if (image) image.src = '';
  document.body.style.overflow = '';
}

function initPreview() {
  const overlay = document.getElementById('preview-overlay');
  const closeBtn = document.getElementById('preview-close');
  if (!overlay || !closeBtn) return;
  closeBtn.addEventListener('click', hidePreview);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) hidePreview();
  });
}

// ===== Context Menu =====
let contextFile = null;

function showContextMenu(event, file) {
  event.preventDefault();
  contextFile = file;
  const menu = document.getElementById('context-menu');
  if (!menu) return;

  menu.innerHTML = '';
  const actions = [
    { label: 'Download', icon: 'download', action: 'download' },
    { label: 'Copy Link', icon: 'link', action: 'copy' }
  ];
  if (file.image) actions.push({ label: 'Preview', icon: 'eye', action: 'preview' });
  actions.push({ label: 'Delete', icon: 'trash-2', action: 'delete', danger: true });

  actions.forEach(item => {
    const btn = document.createElement('button');
    btn.className = 'context-menu-item' + (item.danger ? ' danger' : '');
    btn.innerHTML = svgIcon(item.icon) + '<span>' + item.label + '</span>';
    btn.dataset.action = item.action;
    btn.setAttribute('role', 'menuitem');
    btn.addEventListener('click', handleContextAction);
    menu.appendChild(btn);
  });

  const x = Math.min(event.pageX, window.innerWidth - 196);
  const y = Math.min(event.pageY, window.innerHeight - 200);
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  menu.hidden = false;
  menu.querySelectorAll('.context-menu-item')[0].focus();
}

function hideContextMenu() {
  const menu = document.getElementById('context-menu');
  if (menu) menu.hidden = true;
  contextFile = null;
}

function handleContextAction(e) {
  const action = e.currentTarget.dataset.action;
  const file = contextFile;
  hideContextMenu();
  if (!file) return;
  switch (action) {
    case 'download': downloadFile(file.name); break;
    case 'copy': copyLink(file.name); break;
    case 'preview':
      showPreview('/preview/' + encodeURIComponent(file.name));
      break;
    case 'delete':
      if (window.confirm(`Delete ${file.name}?`)) deleteFile(file.name);
      break;
  }
}

// ===== File Management =====
async function loadFiles(preserveSelection = false) {
  try {
    const response = await fetch('/api/files');
    if (!response.ok) throw new Error('Failed to load files');
    state.allFiles = await response.json();

    if (!preserveSelection) {
      state.selectedFiles.clear();
    } else {
      const names = new Set(state.allFiles.map(f => f.name));
      state.selectedFiles.forEach(name => {
        if (!names.has(name)) state.selectedFiles.delete(name);
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
  const total = state.allFiles.reduce((sum, f) => sum + f.size, 0);
  document.getElementById('stat-files').textContent = state.allFiles.length;
  document.getElementById('stat-size').textContent = formatSize(total);
  const recent = state.allFiles[0];
  document.getElementById('stat-recent').textContent = recent ? formatTime(recent.modified) : '—';
}

function filterAndRenderFiles() {
  const q = state.searchQuery.toLowerCase();
  const filtered = q ? state.allFiles.filter(f => f.name.toLowerCase().includes(q)) : state.allFiles;
  renderFiles(filtered);
}

function renderFiles(files) {
  const list = document.getElementById('file-list');
  if (!list) return;
  list.innerHTML = '';

  if (files.length === 0) {
    const li = document.createElement('li');
    li.className = 'file-list-empty';
    li.textContent = state.searchQuery ? 'No files match your search' : 'No files have been shared yet';
    list.appendChild(li);
    updateSelectAllCheckbox();
    updateSelectionCount();
    return;
  }

  const fragment = document.createDocumentFragment();
  files.forEach(file => fragment.appendChild(createFileItem(file)));
  list.appendChild(fragment);

  updateSelectAllCheckbox();
  updateSelectionCount();
}

function createFileItem(file) {
  const li = document.createElement('li');
  li.className = 'file-item';
  li.dataset.name = file.name;
  li.setAttribute('role', 'listitem');
  if (state.selectedFiles.has(file.name)) li.classList.add('selected');

  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.className = 'file-checkbox';
  checkbox.checked = state.selectedFiles.has(file.name);
  checkbox.setAttribute('aria-label', 'Select ' + file.name);
  checkbox.addEventListener('change', () => toggleFileSelection(file.name));

  const icon = document.createElement('span');
  icon.className = 'file-icon';
  icon.setAttribute('aria-hidden', 'true');
  icon.innerHTML = svgIcon(file.icon || 'file');

  const info = document.createElement('div');
  info.className = 'file-info';

  const name = document.createElement('div');
  name.className = 'file-name';
  name.textContent = file.name;
  name.title = file.name;

  const meta = document.createElement('div');
  meta.className = 'file-meta';
  const sep = document.createTextNode(' • ');

  if (state.currentView === 'detail') {
    const metaLine2 = document.createElement('div');
    metaLine2.textContent = `${formatSize(file.size)} • Modified ${formatTime(file.modified)}`;
    const metaLine3 = document.createElement('div');
    metaLine3.className = 'file-type';
    metaLine3.textContent = getFileType(file.name);
    info.appendChild(name);
    info.appendChild(metaLine2);
    info.appendChild(metaLine3);
  } else {
    meta.appendChild(document.createTextNode(formatSize(file.size)));
    meta.appendChild(sep);
    meta.appendChild(document.createTextNode(formatTime(file.modified)));
    info.appendChild(name);
    info.appendChild(meta);
  }

  const menuBtn = document.createElement('button');
  menuBtn.className = 'file-menu-btn';
  menuBtn.innerHTML = svgIcon('ellipsis-vertical');
  menuBtn.setAttribute('aria-label', 'File actions for ' + file.name);
  menuBtn.setAttribute('aria-haspopup', 'menu');
  menuBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    showContextMenu(e, file);
  });

  if (state.currentView === 'cards') {
    li.appendChild(checkbox);
    li.appendChild(menuBtn);
    if (file.image) {
      const thumb = document.createElement('img');
      thumb.className = 'file-thumb';
      thumb.loading = 'lazy';
      thumb.alt = '';
      thumb.src = '/preview/' + encodeURIComponent(file.name);
      thumb.addEventListener('error', () => thumb.remove());
      li.appendChild(thumb);
    } else {
      li.appendChild(icon);
    }
    li.appendChild(name);
    const cardMeta = document.createElement('div');
    cardMeta.className = 'file-meta';
    cardMeta.textContent = formatSize(file.size);
    li.appendChild(cardMeta);
  } else if (state.currentView === 'compact') {
    const sizeEl = document.createElement('span');
    sizeEl.textContent = formatSize(file.size);
    const timeEl = document.createElement('span');
    timeEl.textContent = formatTime(file.modified);
    meta.appendChild(sizeEl);
    meta.appendChild(timeEl);
    li.appendChild(checkbox);
    li.appendChild(icon);
    li.appendChild(info);
    li.appendChild(meta);
    li.appendChild(menuBtn);
  } else {
    li.appendChild(checkbox);
    li.appendChild(info);
    li.appendChild(menuBtn);
    li.insertBefore(icon, info);
  }

  li.addEventListener('contextmenu', (e) => showContextMenu(e, file));
  return li;
}

function toggleFileSelection(filename) {
  if (state.selectedFiles.has(filename)) {
    state.selectedFiles.delete(filename);
  } else {
    state.selectedFiles.add(filename);
  }
  const item = document.querySelector(`[data-name="${CSS.escape ? CSS.escape(filename) : filename}"]`);
  if (item) {
    item.classList.toggle('selected', state.selectedFiles.has(filename));
    const cb = item.querySelector('.file-checkbox');
    if (cb) cb.checked = state.selectedFiles.has(filename);
  }
  updateSelectAllCheckbox();
  updateBulkActions();
  updateSelectionCount();
}

function updateSelectAllCheckbox() {
  const checkbox = document.getElementById('select-all');
  if (!checkbox) return;
  const visibleCount = document.querySelectorAll('.file-item').length;
  const selectedVisible = [...document.querySelectorAll('.file-item')].filter(i =>
    state.selectedFiles.has(i.dataset.name)
  ).length;

  if (visibleCount === 0) {
    checkbox.checked = false;
    checkbox.indeterminate = false;
  } else if (selectedVisible === visibleCount) {
    checkbox.checked = true;
    checkbox.indeterminate = false;
  } else if (selectedVisible === 0) {
    checkbox.checked = false;
    checkbox.indeterminate = false;
  } else {
    checkbox.checked = false;
    checkbox.indeterminate = true;
  }
}

function updateBulkActions() {
  const has = state.selectedFiles.size > 0;
  document.getElementById('bulk-download').disabled = !has;
  document.getElementById('bulk-delete').disabled = !has;
}

function updateSelectionCount() {
  const el = document.getElementById('selection-count');
  if (el) {
    el.textContent = state.selectedFiles.size > 0
      ? state.selectedFiles.size + ' selected'
      : '';
  }
}

// ===== Search & View Controls =====
function initSearchAndView() {
  const searchInput = document.getElementById('search-input');
  const clearSearchBtn = document.getElementById('clear-search');
  const viewToggleBtn = document.getElementById('view-toggle');
  const viewMenu = document.getElementById('view-menu');
  const viewLabel = document.getElementById('view-label');
  const viewOptions = document.querySelectorAll('.view-option');

  let searchTimer = null;
  searchInput.addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    const value = e.target.value;
    clearSearchBtn.hidden = value.length === 0;
    searchTimer = setTimeout(() => {
      state.searchQuery = value.trim();
      filterAndRenderFiles();
    }, 300);
  });

  clearSearchBtn.addEventListener('click', () => {
    state.searchQuery = '';
    searchInput.value = '';
    clearSearchBtn.hidden = true;
    filterAndRenderFiles();
    searchInput.focus();
  });

  function setView(view) {
    state.currentView = view;
    try { localStorage.setItem('fileView', view); } catch (e) {}
    const list = document.getElementById('file-list');
    if (list) list.setAttribute('data-view', view);
    viewLabel.textContent = view.charAt(0).toUpperCase() + view.slice(1);
    viewOptions.forEach(o => {
      const active = o.dataset.view === view;
      o.classList.toggle('active', active);
      o.setAttribute('aria-checked', active ? 'true' : 'false');
    });
    viewMenu.hidden = true;
    viewToggleBtn.setAttribute('aria-expanded', 'false');
    filterAndRenderFiles();
  }

  viewToggleBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    viewMenu.hidden = !viewMenu.hidden;
    viewToggleBtn.setAttribute('aria-expanded', String(!viewMenu.hidden));
  });

  viewOptions.forEach(option => {
    option.addEventListener('click', () => setView(option.dataset.view));
  });

  document.addEventListener('click', (e) => {
    if (!viewToggleBtn.contains(e.target)) {
      viewMenu.hidden = true;
      viewToggleBtn.setAttribute('aria-expanded', 'false');
    }
  });

  // Restore saved view
  let saved;
  try { saved = localStorage.getItem('fileView'); } catch (e) {}
  if (saved && ['list', 'detail', 'cards', 'compact'].includes(saved)) {
    setView(saved);
  }
}

// ===== Upload System =====
function initUpload() {
  const fileInput = document.getElementById('file-input');
  const dropZone = document.getElementById('drop-zone');
  const uploadQueue = document.getElementById('upload-queue');
  const queueItems = document.getElementById('queue-items');
  let uploadCount = 0;

  dropZone.addEventListener('click', () => fileInput.click());

  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      handleFiles(Array.from(e.target.files));
      fileInput.value = '';
    }
  });

  ['dragenter', 'dragover'].forEach(evt => {
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add('dragover');
    });
  });

  ['dragleave', 'drop'].forEach(evt => {
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove('dragover');
    });
  });

  dropZone.addEventListener('drop', (e) => {
    handleFiles(Array.from(e.dataTransfer.files));
  });

  dropZone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      fileInput.click();
    }
  });

  // Prevent the browser from navigating away if files dropped outside the zone
  ['dragover', 'drop'].forEach(evt => {
    window.addEventListener(evt, (e) => {
      if (e.target !== dropZone) e.preventDefault();
    });
  });

  function handleFiles(files) {
    const valid = files.filter(file => {
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
    if (valid.length === 0) return;
    uploadQueue.hidden = false;
    showToast(`Uploading ${valid.length} file(s)…`, 'info');
    valid.forEach(file => {
      uploadCount++;
      uploadFile(file, 'upload-' + uploadCount);
    });
  }

  function uploadFile(file, id) {
    const item = document.createElement('div');
    item.className = 'queue-item';

    const header = document.createElement('div');
    header.className = 'queue-item-header';
    const name = document.createElement('div');
    name.className = 'queue-name';
    name.textContent = file.name;
    name.title = file.name;
    const size = document.createElement('div');
    size.className = 'queue-size';
    size.textContent = formatSize(file.size);
    header.appendChild(name);
    header.appendChild(size);

    const progressContainer = document.createElement('div');
    progressContainer.className = 'queue-progress';
    progressContainer.setAttribute('role', 'progressbar');
    progressContainer.setAttribute('aria-label', 'Upload progress for ' + file.name);
    progressContainer.setAttribute('aria-valuemin', '0');
    progressContainer.setAttribute('aria-valuemax', '100');
    progressContainer.setAttribute('aria-valuenow', '0');

    const bar = document.createElement('div');
    bar.className = 'queue-progress-bar';
    bar.style.width = '0%';
    progressContainer.appendChild(bar);

    const speed = document.createElement('div');
    speed.className = 'queue-speed';
    speed.setAttribute('aria-live', 'polite');

    item.appendChild(header);
    item.appendChild(progressContainer);
    item.appendChild(speed);
    queueItems.appendChild(item);

    const formData = new FormData();
    formData.append('files', file);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/upload');
    const startTime = Date.now();

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) {
        const percent = Math.round((e.loaded / e.total) * 100);
        bar.style.width = percent + '%';
        progressContainer.setAttribute('aria-valuenow', String(percent));
        const elapsed = (Date.now() - startTime) / 1000;
        if (elapsed > 0) {
          speed.textContent = formatSize(e.loaded / elapsed) + '/s • ' + percent + '%';
        }
      }
    });

    function finish(status) {
      if (status === 'complete') {
        speed.textContent = 'Complete';
        bar.style.width = '100%';
        progressContainer.setAttribute('aria-valuenow', '100');
        setTimeout(() => {
          item.remove();
          if (queueItems.children.length === 0) {
            uploadQueue.hidden = true;
            loadFiles();
            showToast('Upload complete', 'success');
          }
        }, 1500);
      } else {
        speed.textContent = 'Failed';
        speed.style.color = 'var(--danger)';
        setTimeout(() => item.remove(), 3000);
      }
    }

    xhr.onload = () => {
      if (xhr.status === 200) finish('complete');
      else finish('failed');
    };
    xhr.onerror = () => finish('failed');
    xhr.ontimeout = () => finish('failed');
    xhr.timeout = 0;
    xhr.send(formData);
  }
}

// ===== Bulk Actions =====
function initBulkActions() {
  const selectAll = document.getElementById('select-all');
  const bulkDownload = document.getElementById('bulk-download');
  const bulkDelete = document.getElementById('bulk-delete');

  selectAll.addEventListener('change', () => {
    const items = document.querySelectorAll('.file-item[data-name]');
    if (selectAll.checked) {
      items.forEach(item => state.selectedFiles.add(item.dataset.name));
    } else {
      items.forEach(item => state.selectedFiles.delete(item.dataset.name));
    }
    items.forEach(item => {
      item.classList.toggle('selected', state.selectedFiles.has(item.dataset.name));
      const cb = item.querySelector('.file-checkbox');
      if (cb) cb.checked = state.selectedFiles.has(item.dataset.name);
    });
    updateBulkActions();
    updateSelectionCount();
    showToast(selectAll.checked ? 'All visible files selected' : 'Selection cleared', 'info');
  });

  bulkDelete.addEventListener('click', async () => {
    const count = state.selectedFiles.size;
    if (count === 0) return;
    const names = Array.from(state.selectedFiles);
    if (!window.confirm(`Delete ${count} file(s)?`)) return;
    let failed = 0;
    for (const name of names) {
      try {
        const resp = await fetch('/api/files/' + encodeURIComponent(name), { method: 'DELETE' });
        if (!resp.ok) failed++;
      } catch (e) { failed++; }
    }
    state.selectedFiles.clear();
    await loadFiles();
    if (failed === 0) showToast('Files deleted', 'success');
    else showToast(`${failed} file(s) could not be deleted`, 'error');
  });

  bulkDownload.addEventListener('click', bulkDownloadZIP);
}

function bulkDownloadZIP() {
  const files = Array.from(state.selectedFiles);
  if (files.length === 0) return;

  showToast(`Preparing ${files.length} file(s) for download…`, 'info');

  const params = new URLSearchParams();
  files.forEach(name => params.append('files', name));

  const now = new Date();
  const stamp = now.getFullYear() + '-' +
    String(now.getMonth() + 1).padStart(2, '0') + '-' +
    String(now.getDate()).padStart(2, '0') + '-' +
    String(now.getHours()).padStart(2, '0') +
    String(now.getMinutes()).padStart(2, '0') +
    String(now.getSeconds()).padStart(2, '0');

  const a = document.createElement('a');
  a.href = '/api/download-bulk?' + params.toString();
  a.download = 'selected-files-' + stamp + '.zip';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);

  setTimeout(() => showToast(`Downloading ${files.length} file(s) as ZIP…`, 'info'), 400);
}

// ===== Auto-refresh =====
function initAutoRefresh() {
  const autoRefresh = document.getElementById('auto-refresh');
  const refreshBtn = document.getElementById('refresh-btn');

  refreshBtn.addEventListener('click', () => {
    loadFiles();
    showToast('Files refreshed', 'success');
  });

  autoRefresh.addEventListener('change', () => {
    if (autoRefresh.checked) {
      if (!state.autoRefreshInterval) {
        state.autoRefreshInterval = setInterval(() => loadFiles(true), 5000);
      }
      showToast('Auto-refresh enabled', 'info');
    } else {
      if (state.autoRefreshInterval) {
        clearInterval(state.autoRefreshInterval);
        state.autoRefreshInterval = null;
      }
      showToast('Auto-refresh disabled', 'info');
    }
  });
}

// ===== Keyboard Shortcuts & Accessibility =====
function initKeyboard() {
  document.addEventListener('keydown', (e) => {
    const tag = (e.target.tagName || '').toLowerCase();
    const typing = tag === 'input' || tag === 'textarea' || e.target.isContentEditable;

    if (e.key === 'Escape') {
      hideContextMenu();
      const viewMenu = document.getElementById('view-menu');
      if (viewMenu) viewMenu.hidden = true;
      const preview = document.getElementById('preview-overlay');
      if (preview && !preview.hidden) hidePreview();
      return;
    }

    if (typing) return;

    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
      e.preventDefault();
      const search = document.getElementById('search-input');
      if (search) search.focus();
      return;
    }

    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
      e.preventDefault();
      const selectAll = document.getElementById('select-all');
      selectAll.checked = !selectAll.checked;
      selectAll.dispatchEvent(new Event('change'));
      return;
    }

    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 't') {
      e.preventDefault();
      toggleTheme();
      return;
    }

    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'r' || e.key === 'F5') {
      e.preventDefault();
      loadFiles();
      return;
    }

    if (e.key === 'Delete') {
      const bulkDelete = document.getElementById('bulk-delete');
      if (bulkDelete && !bulkDelete.disabled) bulkDelete.click();
      return;
    }

    if (e.key.toLowerCase() === 'v' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      const viewToggle = document.getElementById('view-toggle');
      if (viewToggle) viewToggle.click();
    }
  });
}

// ===== QR Code =====
function initQR() {
  const container = document.getElementById('qr-container');
  if (!container || typeof QRious === 'undefined') return;
  let qr;
  try {
    qr = new QRious({
      element: document.createElement('canvas'),
      value: location.href,
      size: 200,
      backgroundAlpha: 1,
      foreground: '#000000',
      level: 'M'
    });
    container.appendChild(qr.canvas);
  } catch (e) {
    console.error('QR generation failed:', e);
  }
}

// ===== Initialization =====
function init() {
  // Theme (default: dark)
  let savedTheme;
  try { savedTheme = localStorage.getItem('theme'); } catch (e) {}
  applyTheme(savedTheme || 'dark');

  const themeToggle = document.getElementById('theme-toggle');
  themeToggle.addEventListener('click', toggleTheme);

  initSearchAndView();
  initUpload();
  initBulkActions();
  initAutoRefresh();
  initKeyboard();
  initPreview();
  initQR();

  // Close context menu when tapping/clicking anywhere outside it (mobile + desktop)
  document.addEventListener('click', (e) => {
    const menu = document.getElementById('context-menu');
    if (!menu || menu.hidden) return;
    if (!menu.contains(e.target)) hideContextMenu();
  });

  loadFiles();
}

document.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>
"""


def local_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        try:
            connection.connect(("8.8.8.8", 80))
            return connection.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def hash_password(password: str) -> str:
    return hashlib.sha256((SESSION_SECRET + password).encode()).hexdigest()


def verify_password(password: str) -> bool:
    return hmac.compare_digest(hash_password(password), hash_password(PASSWORD))


def check_auth(handler: BaseHTTPRequestHandler) -> bool:
    if not PASSWORD:
        return True
    auth_header = handler.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            _, password = decoded.split(":", 1)
            if verify_password(password):
                return True
        except Exception:
            pass
    session_token = None
    cookie_header = handler.headers.get("Cookie", "")
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("session="):
            session_token = part[8:]
            break
    if session_token and session_token in sessions:
        if time.time() - sessions[session_token] < SESSION_DURATION:
            return True
        del sessions[session_token]
    return False


def send_login_page(handler: BaseHTTPRequestHandler, message: str = ""):
    login_page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Local Drop - Login</title>
<style>
:root{{color-scheme:dark;--ink:#e9edf5;--muted:#9ba5b7;--line:#2b3446;--accent:#7c9cff;--red:#ff6b6b}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;font:16px/1.45 system-ui,sans-serif;color:var(--ink);background:radial-gradient(circle at 18% 0%,#283862 0,transparent 34rem),#0d111a}}
.login{{background:rgba(23,29,41,.88);border:1px solid var(--line);border-radius:22px;padding:40px;width:min(400px,90vw);text-align:center}}
h1{{font-size:2rem;margin:0 0 8px}}p{{color:var(--muted);margin:0 0 24px}}
input{{width:100%;padding:12px 16px;border:1px solid var(--line);border-radius:10px;background:#0d111a;color:var(--ink);font:inherit;margin-bottom:16px;outline:none}}input:focus{{border-color:var(--accent)}}
button{{width:100%;padding:12px;border:0;border-radius:10px;background:var(--accent);color:#101526;font:inherit;font-weight:700;cursor:pointer}}
.error{{color:var(--red);margin-bottom:16px;font-size:.9rem}}
</style></head><body>
<div class="login"><h1>Local Drop</h1><p>Enter password to continue</p>
{"<div class='error'>"+html.escape(message)+"</div>" if message else ""}
<form method="POST" action="/login"><input name="password" type="password" placeholder="Password" autofocus><button type="submit">Login</button></form></div>
</body></html>"""
    body = login_page.encode()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def process_login(handler: BaseHTTPRequestHandler) -> bool:
    length = int(handler.headers.get("Content-Length", 0))
    body = handler.rfile.read(length).decode("utf-8")
    params = {}
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            params[unquote(k)] = unquote(v)
    password = params.get("password", "")
    if verify_password(password):
        token = secrets.token_hex(32)
        sessions[token] = time.time()
        handler.send_response(HTTPStatus.FOUND)
        handler.send_header("Location", "/")
        handler.send_header("Set-Cookie", f"session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_DURATION}")
        handler.end_headers()
        return True
    else:
        send_login_page(handler, "Incorrect password.")
        return False


def cleanup_expired_files():
    if FILE_EXPIRY_HOURS <= 0:
        return
    cutoff = time.time() - (FILE_EXPIRY_HOURS * 3600)
    if not SHARED_DIRECTORY.exists():
        return
    for item in SHARED_DIRECTORY.iterdir():
        if item.is_file() and item.stat().st_mtime < cutoff:
            try:
                item.unlink()
                logger.info("Expired file removed: %s", item.name)
            except OSError as e:
                logger.error("Failed to remove expired file %s: %s", item.name, e)


def cleanup_expired_sessions():
    """Periodically clean up expired sessions to prevent memory leak."""
    global _last_session_cleanup
    now = time.time()
    if now - _last_session_cleanup < SESSION_CLEANUP_INTERVAL:
        return
    _last_session_cleanup = now
    expired = [token for token, ts in sessions.items() if now - ts >= SESSION_DURATION]
    for token in expired:
        del sessions[token]
    if expired:
        logger.debug("Cleaned up %d expired sessions", len(expired))


def check_rate_limit(client_ip: str) -> bool:
    """Check if client IP has exceeded upload rate limit. Returns True if allowed."""
    if UPLOAD_RATE_LIMIT <= 0:
        return True
    now = time.time()
    window_start = now - 60  # 1 minute window
    # Get or create request list for this IP
    if client_ip not in upload_requests:
        upload_requests[client_ip] = []
    # Remove old requests outside the window
    upload_requests[client_ip] = [ts for ts in upload_requests[client_ip] if ts > window_start]
    # Check if limit exceeded
    if len(upload_requests[client_ip]) >= UPLOAD_RATE_LIMIT:
        return False
    # Add current request
    upload_requests[client_ip].append(now)
    return True


def cleanup_rate_limit_data():
    """Periodically clean up old rate limit data to prevent memory leak."""
    now = time.time()
    window_start = now - 60  # 1 minute window
    expired_ips = [ip for ip, timestamps in upload_requests.items() 
                   if not any(ts > window_start for ts in timestamps)]
    for ip in expired_ips:
        del upload_requests[ip]


def safe_path(name: str) -> Path | None:
    candidate = (SHARED_DIRECTORY / Path(name).name).resolve()
    return candidate if candidate.parent == SHARED_DIRECTORY.resolve() else None


def available_name(name: str) -> Path:
    path = safe_path(name) or SHARED_DIRECTORY / "upload"
    stem, suffix = path.stem, path.suffix
    number = 1
    while path.exists():
        path = SHARED_DIRECTORY / f"{stem} ({number}){suffix}"
        number += 1
    return path


class LocalShareHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info("%s - %s", self.client_address[0], format % args)

    def handle_bulk_download(self):
        """Create a ZIP archive of the requested files and stream it to the client."""
        query = urlparse(self.path).query
        file_names = parse_qs(query).get("files", [])

        if not file_names:
            self.send_error(HTTPStatus.BAD_REQUEST, "No files specified.")
            return

        file_paths = []
        total_size = 0
        for name in file_names:
            file_path = safe_path(name)
            if not file_path or not file_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, f"File not found: {name}")
                return
            total_size += file_path.stat().st_size
            file_paths.append((name, file_path))

        if total_size > MAX_ZIP_BYTES:
            self.send_error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "Total size exceeds the 500MB ZIP limit.",
            )
            return

        try:
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for name, file_path in file_paths:
                    zip_file.write(file_path, name)
            zip_data = zip_buffer.getvalue()
        except Exception as e:
            logger.error("ZIP creation failed: %s", e)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to create ZIP archive.")
            return

        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        filename = f"selected-files-{timestamp}.zip"

        logger.info("Bulk download: %d files (%d bytes)", len(file_names), total_size)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
        self.send_header("Content-Length", str(len(zip_data)))
        self.end_headers()
        self.wfile.write(zip_data)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/login" and PASSWORD:
            send_login_page(self)
            return

        if PASSWORD and not check_auth(self):
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/login")
            self.end_headers()
            return

        cleanup_expired_files()
        cleanup_expired_sessions()
        cleanup_rate_limit_data()

        if path == "/":
            self.send_bytes(PAGE.encode(), "text/html; charset=utf-8")
        elif path == "/api/download-bulk":
            self.handle_bulk_download()
        elif path == "/api/files":
            files = []
            for item in SHARED_DIRECTORY.iterdir():
                if item.is_file():
                    files.append({
                        "name": item.name,
                        "size": item.stat().st_size,
                        "modified": datetime.fromtimestamp(item.stat().st_mtime).strftime("%d %b %Y, %H:%M"),
                        "icon": file_icon(item.name),
                        "image": is_image(item.name),
                    })
            self.send_json(sorted(files, key=lambda item: item["modified"], reverse=True))
        elif path.startswith("/preview/"):
            name = unquote(path.removeprefix("/preview/"))
            file_path = safe_path(name)
            if not file_path or not file_path.is_file() or not is_image(name):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            file_size = file_path.stat().st_size
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(file_size))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self._stream_file(file_path)
        elif path.startswith("/download/"):
            self.download(unquote(path.removeprefix("/download/")))
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if PASSWORD and not check_auth(self):
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/login")
            self.end_headers()
            return

        path = urlparse(self.path).path
        if path == "/login" and PASSWORD:
            process_login(self)
            return
        if path != "/upload":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        # Rate limiting for uploads
        client_ip = self.client_address[0]
        if not check_rate_limit(client_ip):
            self.send_error(HTTPStatus.TOO_MANY_REQUESTS, "Upload rate limit exceeded. Please wait before uploading again.")
            return

        length = int(self.headers.get("Content-Length", 0))
        if not 0 < length <= MAX_UPLOAD_BYTES:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Uploads must be under 512 MB.")
            return
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type or "boundary=" not in content_type:
            self.send_error(HTTPStatus.BAD_REQUEST, "Expected a multipart upload.")
            return
        boundary = content_type.split("boundary=", 1)[1].strip().strip('"').encode()
        saved = self.save_multipart_files(self.rfile.read(length), boundary)
        if not saved:
            self.send_error(HTTPStatus.BAD_REQUEST, "No files were uploaded.")
            return
        logger.info("Uploaded: %s", ", ".join(saved))
        self.send_json({"saved": saved})

    def do_DELETE(self):
        if PASSWORD and not check_auth(self):
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/login")
            self.end_headers()
            return

        path = urlparse(self.path).path
        if not path.startswith("/api/files/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        file_path = safe_path(unquote(path.removeprefix("/api/files/")))
        if not file_path or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        logger.info("Deleted: %s", file_path.name)
        file_path.unlink()
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def save_multipart_files(self, body: bytes, boundary: bytes) -> list[str]:
        saved = []
        for part in body.split(b"--" + boundary)[1:-1]:
            headers, separator, content = part.lstrip(b"\r\n").partition(b"\r\n\r\n")
            if not separator or b"filename=" not in headers:
                continue
            filename = headers.split(b"filename=", 1)[1].split(b"\r\n", 1)[0].strip().strip(b'"').decode("utf-8", "replace")
            if not filename:
                continue
            target = available_name(filename)
            target.write_bytes(content[:-2] if content.endswith(b"\r\n") else content)
            saved.append(target.name)
        return saved

    def download(self, name: str):
        file_path = safe_path(name)
        if not file_path or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        file_size = file_path.stat().st_size
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

        # Handle Range header for resumable downloads
        range_header = self.headers.get("Range")
        if range_header:
            self._handle_range_request(file_path, file_size, content_type, range_header)
        else:
            # Full file download with chunked streaming
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(file_path.name)}")
            self.end_headers()
            self._stream_file(file_path)

    def _handle_range_request(self, file_path: Path, file_size: int, content_type: str, range_header: str):
        """Handle HTTP Range header for partial content (resumable downloads)."""
        try:
            # Parse range header: "bytes=start-end" or "bytes=start-" or "bytes=-suffix"
            range_str = range_header.replace("bytes=", "").strip()
            if "-" not in range_str:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return

            start_str, end_str = range_str.split("-", 1)
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1

            # Handle suffix-byte-range-spec: bytes=-500 (last 500 bytes)
            if not start_str and end_str:
                start = file_size - end
                end = file_size - 1

            # Validate range
            if start < 0 or start >= file_size or end >= file_size or start > end:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return

            content_length = end - start + 1
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(content_length))
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(file_path.name)}")
            self.end_headers()
            self._stream_file(file_path, start, end)
        except (ValueError, IndexError):
            self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)

    def _stream_file(self, file_path: Path, start: int = 0, end: int | None = None):
        """Stream file in chunks to avoid loading entire file into memory."""
        with file_path.open("rb") as file:
            file.seek(start)
            remaining = (end - start + 1) if end is not None else None
            while True:
                if remaining is not None and remaining <= 0:
                    break
                chunk_size = min(CHUNK_SIZE, remaining) if remaining is not None else CHUNK_SIZE
                chunk = file.read(chunk_size)
                if not chunk:
                    break
                self.wfile.write(chunk)
                if remaining is not None:
                    remaining -= len(chunk)

    def send_json(self, value):
        self.send_bytes(json.dumps(value).encode(), "application/json")

    def send_bytes(self, body: bytes, content_type: str):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    args = parse_args()
    SHARED_DIRECTORY.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), LocalShareHandler)
    ip = local_ip()
    logger.info("Local Drop is available at http://%s:%s", ip, args.port)
    if PASSWORD:
        logger.info("Password protection is enabled")
    if FILE_EXPIRY_HOURS > 0:
        logger.info("Files expire after %s hours", FILE_EXPIRY_HOURS)
    logger.info("Keep this window open while sharing files. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()