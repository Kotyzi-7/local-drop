"""A dependency-free LAN file sharing server."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import os
import secrets
import socket
import time
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse


HOST = "0.0.0.0"
PORT = 8080
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
SHARED_DIRECTORY = Path(__file__).with_name("shared_files")

PASSWORD = ""
FILE_EXPIRY_HOURS = 0
SESSION_SECRET = secrets.token_hex(32)
SESSION_DURATION = 3600 * 24

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("local-drop")

sessions: dict[str, float] = {}

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"})


def file_icon(name: str) -> str:
    ext = Path(name).suffix.lower()
    icons = {
        ".pdf": "\U0001f4c4", ".doc": "\U0001f4c3", ".docx": "\U0001f4c3",
        ".xls": "\U0001f4ca", ".xlsx": "\U0001f4ca", ".csv": "\U0001f4ca",
        ".mp3": "\U0001f3b5", ".wav": "\U0001f3b5", ".flac": "\U0001f3b5",
        ".ogg": "\U0001f3b5", ".m4a": "\U0001f3b5",
        ".mp4": "\U0001f3ac", ".mkv": "\U0001f3ac", ".avi": "\U0001f3ac",
        ".mov": "\U0001f3ac", ".webm": "\U0001f3ac",
        ".png": "\U0001f5bc", ".jpg": "\U0001f5bc", ".jpeg": "\U0001f5bc",
        ".gif": "\U0001f5bc", ".webp": "\U0001f5bc", ".bmp": "\U0001f5bc",
        ".svg": "\U0001f5bc", ".ico": "\U0001f5bc",
        ".zip": "\U0001f4e6", ".rar": "\U0001f4e6", ".7z": "\U0001f4e6",
        ".tar": "\U0001f4e6", ".gz": "\U0001f4e6",
        ".py": "\U0001f40d", ".js": "\U0001f40d", ".ts": "\U0001f40d",
        ".html": "\U0001f310", ".css": "\U0001f310",
        ".txt": "\U0001f4dd", ".md": "\U0001f4dd", ".log": "\U0001f4dd",
        ".json": "\U0001f4cb", ".xml": "\U0001f4cb", ".yaml": "\U0001f4cb",
        ".exe": "\U0001f5a5", ".msi": "\U0001f5a5", ".dmg": "\U0001f5a5",
        ".apk": "\U0001f4f1", ".ipa": "\U0001f4f1",
    }
    return icons.get(ext, "\U0001f4c1")


def is_image(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_EXTENSIONS


PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Local Drop</title>
  <style>
    :root { color-scheme:dark; --ink:#e9edf5; --muted:#9ba5b7; --line:#2b3446; --panel:#171d29; --accent:#7c9cff; --green:#4ade80; --red:#ff6b6b; }
    *{box-sizing:border-box} body{margin:0;min-height:100vh;font:16px/1.45 system-ui,sans-serif;color:var(--ink);background:radial-gradient(circle at 18% 0%,#283862 0,transparent 34rem),#0d111a}
    main{width:min(880px,calc(100% - 32px));margin:0 auto;padding:68px 0} h1{font-size:clamp(2.4rem,8vw,4.5rem);letter-spacing:-.07em;margin:0} p.sub{color:var(--muted);margin:12px 0 30px}
    .card{background:rgba(23,29,41,.88);border:1px solid var(--line);border-radius:22px;padding:24px;box-shadow:0 22px 60px #0005}
    #drop-zone{display:grid;place-items:center;min-height:180px;border:2px dashed #53647f;border-radius:16px;text-align:center;cursor:pointer;transition:.2s} #drop-zone:hover,#drop-zone.drag{border-color:var(--accent);background:#7c9cff12} input{display:none}
    button,.download{border:0;border-radius:10px;padding:10px 14px;background:var(--accent);color:#101526;font:inherit;font-weight:700;cursor:pointer;text-decoration:none} button.secondary{background:#273146;color:var(--ink)} button.danger{background:transparent;color:#ff9b9b;padding:6px}
    .toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:34px 0 12px} .status{color:var(--muted);min-height:24px} ul{list-style:none;margin:0;padding:0}
    li{display:flex;align-items:center;gap:14px;padding:14px 4px;border-top:1px solid var(--line)} .file{min-width:0;flex:1} .name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap} .meta{color:var(--muted);font-size:.84rem} .actions{display:flex;align-items:center;gap:8px}
    progress{width:100%;height:8px;accent-color:var(--accent)} .empty{padding:26px 4px;color:var(--muted);text-align:center}
    .speed{color:var(--green);font-size:.84rem;margin-top:4px} .file-icon{font-size:1.5rem;flex-shrink:0}
    .preview-overlay{position:fixed;inset:0;background:#000c;display:grid;place-items:center;z-index:100;cursor:pointer} .preview-overlay img{max-width:90vw;max-height:90vh;border-radius:12px;box-shadow:0 8px 40px #0008}
    .qr-section{margin-top:16px;padding:16px;background:var(--panel);border-radius:12px;text-align:center} .qr-section canvas{margin:12px auto;border-radius:8px;background:#fff;padding:8px}
    .copy-toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--green);color:#000;padding:10px 20px;border-radius:8px;font-weight:700;z-index:200;animation:fadeInOut 2s forwards} @keyframes fadeInOut{0%{opacity:0;transform:translateX(-50%) translateY(10px)} 10%{opacity:1;transform:translateX(-50%) translateY(0)} 80%{opacity:1} 100%{opacity:0}}
    @media(max-width:560px){main{padding:36px 0} .card{padding:16px} li{align-items:flex-start} .actions{flex-direction:column}}
  </style>
</head>
<body><main>
  <h1>Local Drop</h1>
  <p class="sub">Send files directly between devices on this local network.</p>
  <section class="card">
    <label id="drop-zone" for="files"><strong>Drop files here</strong><span>or tap to choose files</span><input id="files" type="file" multiple></label>
    <div id="status" class="status"></div><div id="speed" class="speed"></div><progress id="progress" value="0" max="100" hidden></progress>
    <div class="toolbar"><strong>Available files</strong><button id="refresh" class="secondary">Refresh</button></div>
    <ul id="file-list"></ul>
  </section>
  <div class="qr-section" id="qr-section">
    <strong>Scan to connect from mobile</strong>
    <div id="qr-container"></div>
  </div>
</main><script>
const input=document.querySelector('#files'),drop=document.querySelector('#drop-zone'),status=document.querySelector('#status'),speedEl=document.querySelector('#speed'),progress=document.querySelector('#progress'),list=document.querySelector('#file-list');
function formatSize(b){const u=['B','KB','MB','GB'];let i=0;while(b>=1024&&i<u.length-1){b/=1024;i++}return `${b.toFixed(i?1:0)} ${u[i]}`}
function formatSpeed(bytesPerSec){return formatSize(bytesPerSec)+'/s'}
function showToast(msg){const t=document.createElement('div');t.className='copy-toast';t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),2100)}
function showPreview(url){const o=document.createElement('div');o.className='preview-overlay';o.onclick=()=>o.remove();const img=document.createElement('img');img.src=url;o.appendChild(img);document.body.appendChild(o)}
function copyLink(name){const url=location.origin+'/download/'+encodeURIComponent(name);const ta=document.createElement('textarea');ta.value=url;ta.style.cssText='position:fixed;left:-9999px;top:-9999px';document.body.appendChild(ta);ta.select();ta.setSelectionRange(0,ta.value.length);try{document.execCommand('copy');showToast('Link copied!')}catch{showToast('Copy failed')}document.body.removeChild(ta)}
async function loadFiles(){const r=await fetch('/api/files');const files=await r.json();list.replaceChildren();if(!files.length){list.innerHTML='<li class="empty">No files have been shared yet.</li>';return}
files.forEach(f=>{const row=document.createElement('li'),icon=document.createElement('span'),info=document.createElement('div'),name=document.createElement('div'),meta=document.createElement('div'),acts=document.createElement('div'),dl=document.createElement('a'),cp=document.createElement('button'),rm=document.createElement('button');
icon.className='file-icon';icon.textContent=f.icon||'\U0001f4c1';
info.className='file';name.className='name';meta.className='meta';acts.className='actions';dl.className='download';cp.className='secondary';rm.className='danger';
name.textContent=f.name;meta.textContent=`${formatSize(f.size)} \u00b7 ${f.modified}`;
dl.textContent='Download';dl.href='/download/'+encodeURIComponent(f.name);
cp.textContent='Copy Link';cp.onclick=()=>copyLink(f.name);
rm.textContent='Delete';rm.onclick=async()=>{if(confirm(`Delete ${f.name}?`)){await fetch('/api/files/'+encodeURIComponent(f.name),{method:'DELETE'});loadFiles()}};
if(f.image){const pv=document.createElement('button');pv.textContent='Preview';pv.onclick=()=>showPreview('/preview/'+encodeURIComponent(f.name));acts.append(pv)}
info.append(name,meta);acts.append(dl,cp,rm);row.append(icon,info,acts);list.append(row)});}
function upload(files){if(!files.length)return;const data=new FormData();[...files].forEach(f=>data.append('files',f));const req=new XMLHttpRequest();req.open('POST','/upload');progress.hidden=false;speedEl.textContent='';status.textContent=`Uploading ${files.length} file${files.length>1?'s':''}...`;
const startTime=Date.now();let lastLoaded=0;let lastTime=startTime;
req.upload.onprogress=e=>{if(e.lengthComputable){progress.value=e.loaded/e.total*100;const now=Date.now();if(now-lastTime>=500){const speed=e.loaded/(now-startTime)*1000;speedEl.textContent=formatSpeed(speed);lastTime=now;lastLoaded=e.loaded}}};
req.onload=()=>{progress.hidden=true;speedEl.textContent='';status.textContent=req.status===200?'Upload complete.':'Upload failed.';input.value='';loadFiles()};
req.onerror=()=>{progress.hidden=true;speedEl.textContent='';status.textContent='Upload failed.'};req.send(data)}
input.onchange=()=>upload(input.files);['dragenter','dragover'].forEach(t=>drop.addEventListener(t,e=>{e.preventDefault();drop.classList.add('drag')}));['dragleave','drop'].forEach(t=>drop.addEventListener(t,e=>{e.preventDefault();drop.classList.remove('drag')}));drop.addEventListener('drop',e=>upload(e.dataTransfer.files));document.querySelector('#refresh').onclick=loadFiles;loadFiles();
function generateQR(text){
const EC_LEVEL=1;
const VERSIONS=[
{size:21,ecTotal:26,ecBlocks:[{count:1,ecPerBlock:10}],groups:[{count:1,dataPerBlock:16}]},
{size:25,ecTotal:44,ecBlocks:[{count:1,ecPerBlock:16}],groups:[{count:1,dataPerBlock:28}]},
{size:29,ecTotal:70,ecBlocks:[{count:1,ecPerBlock:26}],groups:[{count:1,dataPerBlock:44}]},
{size:33,ecTotal:100,ecBlocks:[{count:2,ecPerBlock:18}],groups:[{count:2,dataPerBlock:32}]},
{size:37,ecTotal:134,ecBlocks:[{count:2,ecPerBlock:24}],groups:[{count:2,dataPerBlock:43}]},
{size:41,ecTotal:172,ecBlocks:[{count:4,ecPerBlock:16}],groups:[{count:4,dataPerBlock:27}]},
{size:45,ecTotal:196,ecBlocks:[{count:4,ecPerBlock:20}],groups:[{count:4,dataPerBlock:31}]},
{size:49,ecTotal:242,ecBlocks:[{count:2,ecPerBlock:26}],groups:[{count:2,dataPerBlock:38},{count:2,ecPerBlock:26}],dataGroups:[{count:2,dataPerBlock:38},{count:2,dataPerBlock:38}]}
];
const ALIGN=[[0],[6,18],[6,22],[6,26],[6,30],[6,34],[6,22,38],[6,24,42],[6,26,46],[6,28,50],[6,30,54],[6,32,58],[6,34,62]];
const GF_EXP=new Uint8Array(512),GF_LOG=new Uint8Array(256);
let v=1;for(let i=0;i<255;i++){GF_EXP[i]=v;GF_LOG[v]=i;v=v*2^(v>=128?285:0)}for(let i=255;i<512;i++)GF_EXP[i]=GF_EXP[i-255];
function gfMul(a,b){return a===0||b===0?0:GF_EXP[GF_LOG[a]+GF_LOG[b]]}
function rsGenPoly(n){let p=[1];for(let i=0;i<n;i++){const np=new Uint8Array(p.length+1);np[0]=p[0];for(let j=1;j<p.length;j++){np[j]=p[j]^gfMul(p[j-1],GF_EXP[i])}np[p.length]=gfMul(p[p.length-1],GF_EXP[i]);p=np}return p}
function rsEncode(data,ecLen){
const poly=rsGenPoly(ecLen);
const result=new Uint8Array(data.length+ecLen);
result.set(data);
for(let i=0;i<data.length;i++){const f=result[i];if(f!==0)for(let j=1;j<poly.length;j++)result[i+j]^=gfMul(poly[j],f)}
return result.slice(data.length)}
const bytes=new TextEncoder().encode(text);
let ver=-1;for(let i=0;i<VERSIONS.length;i++){const total=VERSIONS[i].groups.reduce((s,g)=>s+g.count*g.dataPerBlock,0);if(bytes.length<=total-3){ver=i;break}}
if(ver<0)ver=VERSIONS.length-1;
const V=VERSIONS[ver],size=V.size;
const totalData=V.groups.reduce((s,g)=>s+g.count*g.dataPerBlock,0);
const dataBlocks=[];
let offset=0;
for(const g of V.groups){for(let i=0;i<g.count;i++){dataBlocks.push(bytes.slice(offset,offset+g.dataPerBlock));offset+=g.dataPerBlock}}
while(offset<totalData){dataBlocks.push(new Uint8Array(V.groups[0].dataPerBlock));offset+=V.groups[0].dataPerBlock}
const ecPerBlock=V.ecBlocks[0].ecPerBlock;
const allBlocks=[],ecBlocks=[];
for(const b of dataBlocks){const padded=new Uint8Array(V.groups[0].dataPerBlock);padded.set(b);allBlocks.push(padded);ecBlocks.push(rsEncode(padded,ecPerBlock))}
const modules=Array.from({length:size},()=>new Uint8Array(size));
const reserved=Array.from({length:size},()=>new Uint8Array(size));
function setMod(r,c,mod){if(r>=0&&r<size&&c>=0&&c<size){modules[r][c]=mod?1:0;reserved[r][c]=1}}
function setFinder(r,c){
for(let dr=0;dr<7;dr++)for(let dc=0;dc<7;dc++){
const border=dr===0||dr===6||dc===0||dc===6;
const inner=dr>=2&&dr<=4&&dc>=2&&dc<=4;
setMod(r+dr,c+dc,border||inner)}
for(let i=0;i<7;i++){setMod(r-1,c+i,0);setMod(r+7,c+i,0);setMod(r+i,c-1,0);setMod(r+i,c+7,0)}
setMod(r-1,c-1,0);setMod(r-1,c+7,0);setMod(r+7,c-1,0);setMod(r+7,c+7,0)}
setFinder(0,0);setFinder(0,size-7);setFinder(size-7,0);
for(let i=0;i<size;i++){if(!reserved[6][i])setMod(6,i,i%2===0);if(!reserved[i][6])setMod(i,6,i%2===0)}
if(ver>=1){const positions=ALIGN[ver];for(const r of positions)for(const c of positions){if(reserved[r][c])continue;
for(let dr=-2;dr<=2;dr++)for(let dc=-2;dc<=2;dc++){const b=Math.max(Math.abs(dr),Math.abs(dc))===2;setMod(r+dr,c+dc,!b)}}}
setMod(size-8,8,1);
let bitIndex=0;
const bitData=[];
for(let i=0;i<allBlocks.length;i++){const b=allBlocks[i];for(let j=0;j<b.length;j++)for(let k=7;k>=0;k--)bitData.push((b[j]>>k)&1)}
for(let i=0;i<ecBlocks.length;i++){const b=ecBlocks[i];for(let j=0;j<b.length;j++)for(let k=7;k>=0;k--)bitData.push((b[j]>>k)&1)}
bitIndex=0;
let row=size-1,col=size-1,dir=-1;
while(col>=0){if(col===6)col--;
for(let i=0;i<size;i++){const r=row+i*dir;if(r<0||r>=size)continue;
for(let dc=0;dc<=1;dc++){const c=col-dc;if(c<0||c>=size||reserved[r][c])continue;
modules[r][c]=bitIndex<bitData.length?bitData[bitIndex]:0;bitIndex++}}
dir=-dir;col-=2}
const masks=[
(r,c)=>(r+c)%2===0,(r,c)=>r%2===0,(r,c)=>c%3===0,
(r,c)=>(r+c)%3===0,(r,c)=>(Math.floor(r/2)+Math.floor(c/3))%2===0,
(r,c)=>(r*c)%2+(r*c)%3===0,(r,c)=>((r*c)%2+(r*c)%3)%2===0,(r,c)=>((r+c)%2+(r*c)%3)%2===0
];
function penalty(m){let p=0;
for(let r=0;r<size;r++){let cnt=1;for(let c=1;c<size;c++){if(m[r][c]===m[r][c-1])cnt++;else{if(cnt>=5)p+=cnt-2;cnt=1}}if(cnt>=5)p+=cnt-2}
for(let c=0;c<size;c++){let cnt=1;for(let r=1;r<size;r++){if(m[r][c]===m[r-1][c])cnt++;else{if(cnt>=5)p+=cnt-2;cnt=1}}if(cnt>=5)p+=cnt-2}
for(let r=0;r<size-1;r++)for(let c=0;c<size-1;c++){const v=m[r][c];if(v===m[r][c+1]&&v===m[r+1][c]&&v===m[r+1][c+1])p+=3}
let rl=0;for(let r=0;r<size;r++)for(let c=0;c<size;c++){if(m[r][c]===1){rl++;if(rl===5)p+=3;else if(rl>5)p+=1}else rl=0}
let cl=0;for(let c=0;c<size;c++)for(let r=0;r<size;r++){if(m[r][c]===1){cl++;if(cl===5)p+=3;else if(cl>5)p+=1}else cl=0}
return p}
let bestMask=0,bestPenalty=Infinity;
for(let m=0;m<8;m++){
const masked=modules.map(r=>Uint8Array.from(r));
for(let r=0;r<size;r++)for(let c=0;c<size;c++){if(!reserved[r][c]&&masks[m](r,c))masked[r][c]^=1}
const p=penalty(masked);if(p<bestPenalty){bestPenalty=p;bestMask=m}}
const final=modules.map(r=>Uint8Array.from(r));
for(let r=0;r<size;r++)for(let c=0;c<size;c++){if(!reserved[r][c]&&masks[bestMask](r,c))final[r][c]^=1}
const formatBits=((EC_LEVEL<<3)|bestMask);
let fmt=formatBits<<10;for(let i=0;i<10;i++)fmt=fmt&(1<<9)?fmt^(0x537<<(9-i)):fmt;
const fb=(fmt^(0x5412)).toString(2).padStart(15,'0');
for(let i=0;i<6;i++)setMod(8,i,parseInt(fb[i]));
for(let i=0;i<7;i++)setMod(8,size-1-i,parseInt(fb[14-i]));
for(let i=0;i<7;i++)setMod(size-1-i,8,parseInt(fb[i]));
for(let i=0;i<8;i++)setMod(i,8,parseInt(fb[14-i]));
setMod(size-8,8,1);
const canvas=document.createElement('canvas');
const px=size+8;canvas.width=px*4;canvas.height=px*4;
const ctx=canvas.getContext('2d');
ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);
ctx.fillStyle='#000';
for(let r=0;r<size;r++)for(let c=0;c<size;c++){if(final[r][c])ctx.fillRect((c+4)*4,(r+4)*4,4,4)}
return canvas}
document.querySelector('#qr-container').appendChild(generateQR(location.href));
</script></body></html>"""


def local_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        try:
            connection.connect(("8.8.8.8", 80))
            return connection.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def hash_password(password: str) -> str:
    return hashlib.sha256((SESSION_SECRET + password).encode()).hexdigest()


def check_auth(handler: BaseHTTPRequestHandler) -> bool:
    if not PASSWORD:
        return True
    auth_header = handler.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            _, password = decoded.split(":", 1)
            if hash_password(password) == hash_password(PASSWORD):
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
{"<div class='error'>"+message+"</div>" if message else ""}
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
    if hash_password(password) == hash_password(PASSWORD):
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

        if path == "/":
            self.send_bytes(PAGE.encode(), "text/html; charset=utf-8")
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
            with file_path.open("rb") as f:
                data = f.read()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(data)
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
    ip = local_ip()
    logger.info("Local Drop is available at http://%s:%s", ip, PORT)
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