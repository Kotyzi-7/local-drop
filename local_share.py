"""A dependency-free LAN file sharing server."""

from __future__ import annotations

import json
import mimetypes
import socket
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse


HOST = "0.0.0.0"
PORT = 8080
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
SHARED_DIRECTORY = Path(__file__).with_name("shared_files")


PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Local Drop</title>
  <style>
    :root { color-scheme: dark; --ink:#e9edf5; --muted:#9ba5b7; --line:#2b3446; --panel:#171d29; --accent:#7c9cff; }
    * { box-sizing:border-box; } body { margin:0; min-height:100vh; font:16px/1.45 system-ui,sans-serif; color:var(--ink); background:radial-gradient(circle at 18% 0%,#283862 0,transparent 34rem),#0d111a; }
    main { width:min(880px,calc(100% - 32px)); margin:0 auto; padding:68px 0; } h1 { font-size:clamp(2.4rem,8vw,4.5rem); letter-spacing:-.07em; margin:0; } p { color:var(--muted); margin:12px 0 30px; }
    .card { background:rgba(23,29,41,.88); border:1px solid var(--line); border-radius:22px; padding:24px; box-shadow:0 22px 60px #0005; } #drop-zone { display:grid; place-items:center; min-height:180px; border:2px dashed #53647f; border-radius:16px; text-align:center; cursor:pointer; transition:.2s; } #drop-zone:hover,#drop-zone.drag { border-color:var(--accent); background:#7c9cff12; } input { display:none; }
    button,.download { border:0; border-radius:10px; padding:10px 14px; background:var(--accent); color:#101526; font:inherit; font-weight:700; cursor:pointer; text-decoration:none; } button.secondary { background:#273146; color:var(--ink); } button.danger { background:transparent; color:#ff9b9b; padding:6px; }
    .toolbar { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:34px 0 12px; } .status { color:var(--muted); min-height:24px; } ul { list-style:none; margin:0; padding:0; } li { display:flex; align-items:center; gap:14px; padding:14px 4px; border-top:1px solid var(--line); } .file { min-width:0; flex:1; } .name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; } .meta { color:var(--muted); font-size:.84rem; } .actions { display:flex; align-items:center; gap:8px; } progress { width:100%; height:8px; accent-color:var(--accent); } .empty { padding:26px 4px; color:var(--muted); text-align:center; }
    @media (max-width:560px) { main { padding:36px 0; } .card { padding:16px; } li { align-items:flex-start; } .actions { flex-direction:column; } }
  </style>
</head>
<body><main>
  <h1>Local Drop</h1>
  <p>Send files directly between devices on this local network.</p>
  <section class="card">
    <label id="drop-zone" for="files"><strong>Drop files here</strong><span>or tap to choose files</span><input id="files" type="file" multiple></label>
    <div id="status" class="status"></div><progress id="progress" value="0" max="100" hidden></progress>
    <div class="toolbar"><strong>Available files</strong><button id="refresh" class="secondary">Refresh</button></div>
    <ul id="file-list"></ul>
  </section>
</main><script>
const input=document.querySelector('#files'), drop=document.querySelector('#drop-zone'), status=document.querySelector('#status'), progress=document.querySelector('#progress'), list=document.querySelector('#file-list');
const escapeName = name => name;
function formatSize(bytes) { const units=['B','KB','MB','GB']; let i=0; while(bytes>=1024&&i<units.length-1){bytes/=1024;i++} return `${bytes.toFixed(i?1:0)} ${units[i]}`; }
async function loadFiles() { const response=await fetch('/api/files'); const files=await response.json(); list.replaceChildren(); if(!files.length){list.innerHTML='<li class="empty">No files have been shared yet.</li>';return} files.forEach(file=>{const row=document.createElement('li'), info=document.createElement('div'), name=document.createElement('div'), meta=document.createElement('div'), actions=document.createElement('div'), download=document.createElement('a'), remove=document.createElement('button'); info.className='file';name.className='name';meta.className='meta';actions.className='actions';download.className='download';remove.className='danger';name.textContent=file.name;meta.textContent=`${formatSize(file.size)} · ${file.modified}`;download.textContent='Download';download.href='/download/'+encodeURIComponent(file.name);remove.textContent='Delete';remove.onclick=async()=>{if(confirm(`Delete ${file.name}?`)){await fetch('/api/files/'+encodeURIComponent(file.name),{method:'DELETE'});loadFiles()}};info.append(name,meta);actions.append(download,remove);row.append(info,actions);list.append(row);}); }
function upload(files) { if(!files.length)return; const data=new FormData(); [...files].forEach(file=>data.append('files',file)); const request=new XMLHttpRequest(); request.open('POST','/upload'); progress.hidden=false; status.textContent=`Uploading ${files.length} file${files.length>1?'s':''}...`; request.upload.onprogress=e=>{if(e.lengthComputable)progress.value=e.loaded/e.total*100}; request.onload=()=>{progress.hidden=true;status.textContent=request.status===200?'Upload complete.':'Upload failed.';input.value='';loadFiles()}; request.onerror=()=>{progress.hidden=true;status.textContent='Upload failed.'}; request.send(data); }
input.onchange=()=>upload(input.files); ['dragenter','dragover'].forEach(type=>drop.addEventListener(type,e=>{e.preventDefault();drop.classList.add('drag')})); ['dragleave','drop'].forEach(type=>drop.addEventListener(type,e=>{e.preventDefault();drop.classList.remove('drag')})); drop.addEventListener('drop',e=>upload(e.dataTransfer.files)); document.querySelector('#refresh').onclick=loadFiles; loadFiles();
</script></body></html>"""


def local_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        try:
            connection.connect(("8.8.8.8", 80))
            return connection.getsockname()[0]
        except OSError:
            return "127.0.0.1"


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
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self.send_bytes(PAGE.encode(), "text/html; charset=utf-8")
        elif path == "/api/files":
            files = [
                {"name": item.name, "size": item.stat().st_size, "modified": datetime.fromtimestamp(item.stat().st_mtime).strftime("%d %b %Y, %H:%M")}
                for item in SHARED_DIRECTORY.iterdir() if item.is_file()
            ]
            self.send_json(sorted(files, key=lambda item: item["modified"], reverse=True))
        elif path.startswith("/download/"):
            self.download(unquote(path.removeprefix("/download/")))
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if urlparse(self.path).path != "/upload":
            self.send_error(HTTPStatus.NOT_FOUND)
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
        self.send_json({"saved": saved})

    def do_DELETE(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/files/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        file_path = safe_path(unquote(path.removeprefix("/api/files/")))
        if not file_path or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
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
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(file_path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(file_path.name)}")
        self.end_headers()
        with file_path.open("rb") as file:
            self.wfile.write(file.read())

    def send_json(self, value):
        self.send_bytes(json.dumps(value).encode(), "application/json")

    def send_bytes(self, body: bytes, content_type: str):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    SHARED_DIRECTORY.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), LocalShareHandler)
    print(f"Local Drop is available at http://{local_ip()}:{PORT}")
    print("Keep this window open while sharing files. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()
