"""0x web interface: a small local web page on top of the 0x stock and closing engine.

Run it with:   python -m autoclose_ui --open     (or: 0x-ui --open)   then open http://127.0.0.1:8080

It calls the same code as `0x --stock-file ...`, so the figures are identical to the command line.
It only listens on this computer (127.0.0.1), runs read-only tools, and never changes your files:
the owner report is shown as a preview only.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import autoclose as core

_HERE = Path(__file__).resolve().parent
SAMPLES = _HERE / "samples"
MAX_UPLOAD = 25 * 1024 * 1024
ALLOWED = {".pdf", ".csv", ".tsv", ".xlsx", ".json", ".txt"}
UPLOADS = Path(tempfile.mkdtemp(prefix="0x-ui-"))
_LOCK = threading.Lock()  # the engine keeps some process-wide state, so run one review at a time

app = FastAPI(title="0x web interface", version="0.1.0")


def _tools() -> list[dict[str, Any]]:
    out = []
    for name in core.STOCK_TOOL_REGISTRY:
        if name in core.STOCK_WRITE_TOOLS and name != "owner_report":
            continue  # these change files; they stay in the terminal behind --yes
        out.append({"name": name, "description": core.STOCK_TOOL_DESCRIPTIONS[name],
                    "needs_pack": name in core.PACK_TOOLS,
                    "preview_only": name in core.STOCK_WRITE_TOOLS})
    return out


def _cases() -> list[dict[str, Any]]:
    cases = []
    if SAMPLES.is_dir():
        for d in sorted(p for p in SAMPLES.iterdir() if p.is_dir()):
            stock = next(iter(sorted(d.glob("*stock*.pdf")) + sorted(d.glob("*stock*.csv")) + sorted(d.glob("*stock*.xlsx"))), None)
            pack = next(iter(sorted(d.glob("*closing*.pdf"))), None)
            if stock:
                cases.append({"id": d.name, "stock": stock.name, "closing": pack.name if pack else None})
    return cases


@app.get("/api/info")
def info() -> dict[str, Any]:
    return {"tools": _tools(), "cases": _cases()}


@app.post("/api/upload")
async def upload(request: Request, name: str) -> dict[str, str]:
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use: {', '.join(sorted(ALLOWED))}")
    body = await request.body()
    if not body:
        raise HTTPException(400, "Empty file")
    if len(body) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 25 MB")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name)[:80] or f"file{ext}"
    token = uuid.uuid4().hex
    folder = UPLOADS / token
    folder.mkdir()
    (folder / safe).write_bytes(body)
    return {"token": token, "name": safe}


class RunBody(BaseModel):
    case: str | None = None          # a sample case folder name
    stock_token: str | None = None   # or an uploaded file
    closing_token: str | None = None
    tool: str | None = None          # None = the default review
    window: int = 7
    tolerance: float = 2.0
    full: bool = True


def _resolve_upload(token: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise HTTPException(400, "Bad upload reference")
    files = list((UPLOADS / token).glob("*"))
    if not files:
        raise HTTPException(404, "Upload not found, please add the file again")
    return files[0]


def _call(args: argparse.Namespace) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = core.stock_cli(args)
    return code, out.getvalue(), err.getvalue()


@app.post("/api/run")
def run(body: RunBody) -> dict[str, Any]:
    stock = pack = None
    if body.case:
        d = SAMPLES / body.case
        match = next((c for c in _cases() if c["id"] == body.case), None)
        if not match:
            raise HTTPException(404, "Unknown sample case")
        stock = d / match["stock"]
        pack = d / match["closing"] if match["closing"] else None
    if body.stock_token:
        stock = _resolve_upload(body.stock_token)
    if body.closing_token:
        pack = _resolve_upload(body.closing_token)
    if stock is None and pack is None:
        raise HTTPException(400, "Pick a sample case or upload a stock file")
    if body.tool:
        allowed = {t["name"] for t in _tools()}
        if body.tool not in allowed:
            raise HTTPException(400, f"'{body.tool}' is not available in the web interface")

    def make(as_json: bool) -> argparse.Namespace:
        return argparse.Namespace(
            user="web", data=str(UPLOADS / "state"), store=None, date=None,
            stock_file=str(stock) if stock else None, closing_file=str(pack) if pack else None,
            stock_tool=body.tool, window=body.window, tolerance=body.tolerance,
            yes=False, dry_run=True, full=body.full, json=as_json, out=None)

    with _LOCK:
        code, text, err = _call(make(False))
        if code != 0:
            raise HTTPException(422, (err or text).strip() or "The review failed")
        _, raw, _ = _call(make(True))
    try:
        data = json.loads(raw)
    except ValueError:
        data = {}
    issues: list[dict[str, Any]] = []
    summaries: dict[str, str] = {}
    for tool, res in (data.get("results") or {}).items():
        summaries[tool] = res.get("summary", "")
        for i in res.get("issues", []):
            issues.append({**i, "tool": tool})
    return {"report": text, "summaries": summaries, "issues": issues,
            "security": (data.get("security") or {}).get("instruction_like_text_ignored", []),
            "files": {"stock": stock.name if stock else None, "closing": pack.name if pack else None}}


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return PAGE


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>0x · AutoClose</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1b;--mute:#6b6a65;--line:#e2e0d9;--acc:#1f5eff;--accink:#fff;--bad:#c0392b;--warn:#b7791f;--ok:#2f855a;--code:#f0eee8}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--ink:#ecebe6;--mute:#9a988f;--line:#33322e;--acc:#6d95ff;--accink:#101010;--bad:#ff7b6b;--warn:#e6b450;--ok:#5fcf93;--code:#262522}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;align-items:baseline;gap:12px}
header h1{margin:0;font-size:20px;letter-spacing:-.01em}header span{color:var(--mute);font-size:13px}
main{display:grid;grid-template-columns:340px minmax(0,1fr);gap:20px;padding:20px 24px;max-width:1280px;margin:0 auto}
@media(max-width:860px){main{grid-template-columns:1fr;padding:16px}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin:0 0 10px}
label{display:block;font-size:13px;color:var(--mute);margin:12px 0 4px}
select,input[type=number]{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit}
.drop{border:1.5px dashed var(--line);border-radius:10px;padding:12px;text-align:center;color:var(--mute);font-size:13px;cursor:pointer}
.drop.has{border-style:solid;color:var(--ink)}.drop.over{border-color:var(--acc)}
.drop b{display:block;color:var(--ink);font-weight:600}
button{font:inherit;cursor:pointer;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink);padding:7px 12px}
button.primary{background:var(--acc);color:var(--accink);border-color:var(--acc);width:100%;padding:11px;font-weight:600;margin-top:16px}
button:disabled{opacity:.5;cursor:not-allowed}
.row{display:flex;gap:10px}.row>*{flex:1}.chk{display:flex;gap:8px;align-items:center;margin-top:12px;font-size:14px;color:var(--ink)}
.hint{font-size:12px;color:var(--mute);margin-top:4px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.chip{padding:3px 10px;border-radius:99px;font-size:12px;border:1px solid var(--line);color:var(--mute)}
.chip.critical,.chip.high{color:var(--bad);border-color:var(--bad)}.chip.medium{color:var(--warn);border-color:var(--warn)}
.banner{border:1px solid var(--warn);border-radius:10px;padding:10px 14px;margin-bottom:14px;font-size:14px}
.banner b{color:var(--warn)}.banner ul{margin:6px 0 0;padding-left:18px;color:var(--mute)}
.tabs{display:flex;gap:6px;margin-bottom:12px;align-items:center}
.tabs button.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}.tabs .sp{flex:1}
pre{margin:0;background:var(--code);border-radius:10px;padding:14px;overflow:auto;font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre;max-height:70vh}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mute);font-weight:500}.sev{font-weight:600}.sev.critical,.sev.high{color:var(--bad)}.sev.medium{color:var(--warn)}
.empty{color:var(--mute);text-align:center;padding:60px 10px}.err{color:var(--bad);margin-top:12px;font-size:14px}
.spin{display:inline-block;width:14px;height:14px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:s .7s linear infinite;vertical-align:-2px;margin-right:8px}
@keyframes s{to{transform:rotate(360deg)}}
</style></head><body>
<header><h1>0x</h1><span>AutoClose · stock and closing review · runs on this computer only</span></header>
<main>
<section class="card">
  <h2>1 · Choose the case</h2>
  <label for="case">Sample case</label>
  <select id="case"></select>
  <label>Or use your own files</label>
  <div class="drop" id="dStock" tabindex="0"><b>Stock file</b><span>PDF, CSV, Excel, JSON · click or drop</span></div>
  <div class="drop" id="dPack" tabindex="0" style="margin-top:8px"><b>Closing pack (optional)</b><span>PDF · click or drop</span></div>
  <input type="file" id="fStock" hidden><input type="file" id="fPack" hidden>
  <div class="hint" id="clear" hidden><a href="#" id="clearLink" style="color:var(--acc)">Clear my files and use the sample</a></div>
  <h2 style="margin-top:20px">2 · What to run</h2>
  <label for="tool">Report</label>
  <select id="tool"></select>
  <div class="hint" id="toolDesc"></div>
  <div class="row"><div><label for="win">Expiry window (days)</label><input type="number" id="win" value="7" min="1" max="90"></div>
  <div><label for="tol">Count tolerance (%)</label><input type="number" id="tol" value="2" step="0.5" min="0"></div></div>
  <label class="chk"><input type="checkbox" id="full" checked> Show every row (not just the first 12)</label>
  <button class="primary" id="go">Run 0x</button>
  <div class="err" id="err"></div>
</section>
<section class="card" id="out"><div class="empty">Pick a case and press <b>Run 0x</b>.</div></section>
</main>
<script>
const $=id=>document.getElementById(id);
let info={tools:[],cases:[]},up={stock:null,pack:null},last=null,tab='report';
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function api(path,opt){const r=await fetch(path,opt);const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.detail||('Request failed ('+r.status+')'));return j}
function hasPack(){return up.stock?!!up.pack:!!(info.cases.find(c=>c.id===$('case').value)||{}).closing}
function fillTools(){
  const keep=$('tool').value,pack=hasPack();
  $('tool').innerHTML='<option value="">Full review (default)</option>'+info.tools.map(t=>`<option value="${t.name}" ${t.needs_pack&&!pack?'disabled':''}>${t.name}${t.needs_pack?' (closing pack)':''}${t.preview_only?' · preview':''}</option>`).join('');
  if([...$('tool').options].some(o=>o.value===keep&&!o.disabled))$('tool').value=keep;descr()}
function descr(){const t=info.tools.find(t=>t.name===$('tool').value);
  $('toolDesc').textContent=t?t.description+(t.preview_only?' Preview only here; nothing is written.':''):'Runs every stock check and, if a closing pack is present, the closing review.'}
function drop(el,input,key){
  el.onclick=()=>input.click();el.onkeydown=e=>{if(e.key==='Enter')input.click()};
  ['dragover','dragenter'].forEach(ev=>el.addEventListener(ev,e=>{e.preventDefault();el.classList.add('over')}));
  ['dragleave','drop'].forEach(ev=>el.addEventListener(ev,e=>{e.preventDefault();el.classList.remove('over')}));
  el.addEventListener('drop',e=>send(key,el,e.dataTransfer.files[0]));input.onchange=()=>send(key,el,input.files[0])}
async function send(key,el,f){if(!f)return;$('err').textContent='';
  try{const r=await api('/api/upload?name='+encodeURIComponent(f.name),{method:'POST',body:f});
    up[key]=r;el.classList.add('has');el.querySelector('b').textContent=f.name;el.querySelector('span').textContent='uploaded';
    $('clear').hidden=false;if(key==='stock')$('case').disabled=true;fillTools()}catch(e){$('err').textContent=e.message}}
$('clearLink').onclick=e=>{e.preventDefault();up={stock:null,pack:null};$('case').disabled=false;$('clear').hidden=true;
  [['dStock','Stock file','PDF, CSV, Excel, JSON · click or drop'],['dPack','Closing pack (optional)','PDF · click or drop']].forEach(([i,b,s])=>{const d=$(i);d.classList.remove('has');d.querySelector('b').textContent=b;d.querySelector('span').textContent=s});fillTools()};
$('tool').onchange=descr;$('case').onchange=fillTools;
$('go').onclick=async()=>{
  $('err').textContent='';$('go').disabled=true;$('go').innerHTML='<span class="spin"></span>Running';
  try{
    if(!up.stock&&!up.pack&&!$('case').value)throw new Error('Pick a sample case or upload a stock file.');
    last=await api('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      case:up.stock?null:$('case').value||null,stock_token:up.stock?.token||null,closing_token:up.pack?.token||null,
      tool:$('tool').value||null,window:+$('win').value||7,tolerance:+$('tol').value||0,full:$('full').checked})});
    tab='report';draw()}catch(e){$('err').textContent=e.message}
  $('go').disabled=false;$('go').textContent='Run 0x'};
function draw(){
  const c={};last.issues.forEach(i=>c[i.severity]=(c[i.severity]||0)+1);
  const ord=['critical','high','medium','low','info'];const chips=Object.entries(c).sort((a,b)=>ord.indexOf(a[0])-ord.indexOf(b[0])).map(([k,v])=>`<span class="chip ${esc(k)}">${v} ${esc(k)}</span>`).join('')||'<span class="chip">no issues found</span>';
  const sec=last.security.length?`<div class="banner"><b>Security notice.</b> ${last.security.length} piece(s) of text in the documents looked like instructions aimed at an AI agent. They were treated as data and ignored.<ul>${last.security.slice(0,5).map(f=>`<li>${esc(f.where)}: “${esc((f.excerpt||'').slice(0,110))}”</li>`).join('')}</ul></div>`:'';
  const body=tab==='report'?`<pre>${esc(last.report)}</pre>`:tab==='issues'?
    (last.issues.length?`<table><tr><th>Severity</th><th>Item</th><th>Problem</th><th>Action</th></tr>${last.issues.map(i=>`<tr><td class="sev ${esc(i.severity)}">${esc(i.severity)}</td><td>${esc(i.item)}</td><td>${esc(i.message)}</td><td>${esc(i.action)}</td></tr>`).join('')}</table>`:'<div class="empty">No issues.</div>'):
    `<pre>${esc(JSON.stringify(last,null,2))}</pre>`;
  $('out').innerHTML=`<div class="chips">${chips}<span class="chip">${esc([last.files.stock,last.files.closing].filter(Boolean).join(' + '))}</span></div>${sec}
  <div class="tabs">${['report','issues','json'].map(t=>`<button class="${t===tab?'on':''}" data-t="${t}">${t==='report'?'Report':t==='issues'?'Issues ('+last.issues.length+')':'JSON'}</button>`).join('')}
  <span class="sp"></span><button id="cp">Copy</button><button id="dl">Download .txt</button></div>${body}`;
  document.querySelectorAll('[data-t]').forEach(b=>b.onclick=()=>{tab=b.dataset.t;draw()});
  $('cp').onclick=()=>navigator.clipboard.writeText(last.report).then(()=>{$('cp').textContent='Copied';setTimeout(()=>$('cp').textContent='Copy',1200)});
  $('dl').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([last.report],{type:'text/plain'}));a.download='0x-report.txt';a.click()}}
(async()=>{try{info=await api('/api/info');
  $('case').innerHTML=info.cases.map(c=>`<option value="${esc(c.id)}">${esc(c.id)}${c.closing?' · stock + closing pack':' · stock only'}</option>`).join('')||'<option value="">(no samples found)</option>';
  if(info.cases.some(c=>c.id==='piazza1140'))$('case').value='piazza1140';fillTools();drop($('dStock'),$('fStock'),'stock');drop($('dPack'),$('fPack'),'pack')}catch(e){$('err').textContent=e.message}})();
</script></body></html>"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="0x-ui", description="Open the 0x web interface on this computer")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--open", action="store_true", help="Open the page in your browser")
    a = p.parse_args(argv)
    url = f"http://127.0.0.1:{a.port}"
    print(f"0x web interface: {url}   (Ctrl+C to stop)")
    if a.open:
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
