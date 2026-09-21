"""Local web UI for the OSS Contribution Copilot — personal daily use.

Thin FastAPI layer over the pipeline. localhost only. Human-approval gate
preserved: nothing posts without an explicit Post click AND a confirm dialog.

    uv run uvicorn oss_copilot.web.app:app --port 8100 --app-dir src
    # open http://localhost:8100
"""

from __future__ import annotations

import sys
sys.path.insert(0, "src")

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from oss_copilot.watcher.pipeline import build_digest
from oss_copilot.watcher.mcp_client import mcp_session, call_tool
from oss_copilot.watcher import state
from oss_copilot.claim.draft import draft_comment

app = FastAPI(title="OSS Copilot")


class RefreshReq(BaseModel):
    days: int = 14
    limit: int | None = 30


class RecentReq(BaseModel):
    days: int = 7


class DraftReq(BaseModel):
    repo: str
    number: int
    name_fix: bool = False


class PostReq(BaseModel):
    repo: str
    number: int
    body: str


@app.post("/api/refresh")
async def refresh(req: RefreshReq):
    items, stats = await build_digest(days=req.days, limit=req.limit, dry_run=False)
    return {"items": items, "stats": stats}


@app.post("/api/recent")
async def recent(req: RecentReq):
    """Read-only: show issues already surfaced in the last N days. No pipeline
    run, no cost, no flag changes. Needs the issue title/url, which aren't in
    state — fetch them live per issue so cards render fully."""
    conn = state.get_conn()
    state.init_schema(conn)
    rows = state.recent_surfaced(conn, days=req.days)
    conn.close()
    if not rows:
        return {"items": []}
    items = []
    async with mcp_session() as s:
        for r in rows:
            iss = await call_tool(s, "get_actionable_issue",
                                  {"repo": r["repo"], "number": r["number"]})
            if isinstance(iss, dict) and iss.get("error"):
                continue
            items.append({"repo": r["repo"], "number": r["number"],
                          "title": iss["title"], "url": iss["url"],
                          "reason": r["reason"], "signals": []})
    return {"items": items}


@app.post("/api/draft")
async def draft(req: DraftReq):
    async with mcp_session() as s:
        issue = await call_tool(s, "get_actionable_issue",
                                {"repo": req.repo, "number": req.number})
        if isinstance(issue, dict) and issue.get("error"):
            return {"error": issue["error"]}
        claim = await call_tool(s, "get_claim_status",
                                {"repo": req.repo, "number": req.number})
    if claim.get("claimed"):
        return {"error": f"appears already claimed (signals: {claim.get('signals')})"}
    return draft_comment(issue["title"], issue["body"], name_fix=req.name_fix)


@app.post("/api/post")
async def post(req: PostReq):
    if not req.body.strip():
        return {"error": "empty body refused"}
    async with mcp_session() as s:
        res = await call_tool(s, "post_issue_comment",
                              {"repo": req.repo, "number": req.number, "body": req.body})
    return res


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


HTML = """<!doctype html><html><head><meta charset=utf-8>
<title>OSS Copilot</title>
<style>
 body{font:14px/1.5 ui-monospace,Menlo,monospace;max-width:820px;margin:2rem auto;
   padding:0 1rem;background:#0f1115;color:#d7dbe0}
 h1{font-size:18px} button{font:inherit;cursor:pointer;border:1px solid #33383f;
   background:#1a1d23;color:#d7dbe0;padding:.35rem .7rem;border-radius:6px}
 button:hover{background:#22262d} .card{border:1px solid #262b32;border-radius:8px;
   padding:.8rem 1rem;margin:.8rem 0;background:#14171c}
 .tag{color:#7fd1b9;font-size:12px} a{color:#7aa2f7} .muted{color:#8b929c;font-size:12px}
 textarea{width:100%;box-sizing:border-box;font:inherit;background:#0f1115;color:#d7dbe0;
   border:1px solid #33383f;border-radius:6px;padding:.5rem;min-height:5rem}
 .row{display:flex;gap:.5rem;align-items:center;margin-top:.5rem;flex-wrap:wrap}
 .ok{color:#7fd1b9} .err{color:#f7768e}
</style></head><body>
<h1>OSS Contribution Copilot</h1>
<div class="row">
  <button onclick="refresh()">↻ Refresh (find new)</button>
  <button onclick="recent()">🕘 Recent (last 7d)</button>
  <label class="muted"><input type=checkbox id=fix> name a fix (verify first)</label>
  <span id=stats class=muted></span>
</div>
<div id=list></div>
<script>
const $=s=>document.querySelector(s);
function el(t,c,h){const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e;}
async function api(p,b){
  const r=await fetch(p,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(b||{})});
  return r.json();
}
async function refresh(){
  $('#stats').textContent='running…'; $('#list').innerHTML='';
  try{
    const d=await api('/api/refresh',{});
    $('#stats').textContent=`scanned ${d.stats.scanned} · surfaced ${d.stats.surfaced} · filtered ${d.stats.filtered}`;
    if(!d.items||!d.items.length){$('#list').append(el('p','muted','Nothing new. Try Recent to see the last 7 days.'));return;}
    d.items.forEach(renderItem);
  }catch(e){ $('#stats').textContent='error'; $('#list').append(el('p','err',String(e))); }
}
async function recent(){
  $('#stats').textContent='loading recent…'; $('#list').innerHTML='';
  try{
    const d=await api('/api/recent',{days:7});
    $('#stats').textContent=`recent: ${d.items.length} surfaced in the last 7 days`;
    if(!d.items||!d.items.length){$('#list').append(el('p','muted','Nothing surfaced recently.'));return;}
    d.items.forEach(renderItem);
  }catch(e){ $('#stats').textContent='error'; $('#list').append(el('p','err',String(e))); }
}
function renderItem(it){
  const c=el('div','card');
  const sig=(it.signals&&it.signals.length)?` <span class=tag>[${it.signals.join(', ')}]</span>`:'';
  c.append(el('div',null,`<b>${it.repo}#${it.number}</b>${sig}`));
  c.append(el('div',null,it.title));
  c.append(el('div','muted',`→ <a href="${it.url}" target=_blank>${it.url}</a>`));
  if(it.reason) c.append(el('div','muted',`readiness: ${it.reason}`));
  const row=el('div','row');
  const b=el('button',null,'Draft claim');
  b.onclick=()=>doDraft(it,c,b);
  row.append(b); c.append(row);
  $('#list').append(c);
}
async function doDraft(it,card,btn){
  btn.textContent='drafting…'; btn.disabled=true;
  const d=await api('/api/draft',{repo:it.repo,number:it.number,name_fix:$('#fix').checked});
  btn.remove();
  if(d.error){card.append(el('div','err',d.error));return;}
  const ta=el('textarea'); ta.value=d.comment; card.append(ta);
  const row=el('div','row');
  const post=el('button',null,'Post');
  post.onclick=async()=>{
    if(!confirm(`Post this comment to ${it.url} for real?`))return;
    post.textContent='posting…'; post.disabled=true;
    const r=await api('/api/post',{repo:it.repo,number:it.number,body:ta.value});
    card.append(el('div', r.posted?'ok':'err',
      r.posted?`✓ posted: <a href="${r.url}" target=_blank>${r.url}</a>`:`✗ ${r.error}`));
    if(r.posted){ta.disabled=true;} else {post.disabled=false;post.textContent='Post';}
  };
  row.append(post); card.append(row);
}
</script></body></html>"""