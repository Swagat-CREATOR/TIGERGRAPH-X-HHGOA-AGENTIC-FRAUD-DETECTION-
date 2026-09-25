"""Build the analyst UI (required component #5): a self-contained investigation
dashboard rendered from the on-disk case answers + their MCP traces — NO API.

Satisfies the PDF's UI requirement — it demonstrates, per case: the trigger, the
investigation/case progression, the evidence, the uncertainty, the recommendations
and the next best actions (initial -> final). Crucially it surfaces the raw
``tool_trace`` so the evidence coming back from TigerGraph *through the MCP layer*
is visible, not just a polished summary. An architecture strip sits on top.

It reads:
  cases/HHG-*.json           the 20 graded answers (Part 1 + Part 2)
  cases/HHG-*.trace.json     the per-case MCP/tool trace (graph evidence returned)
  cases/_runs/summary.json   the P1->P2->P3 headline stats
  $DATASET_DIR/case_pack.csv the trigger row for each case

and writes ``ui.html`` — one file, inline CSS/JS, no external assets. Serve with:
  python -m src.serve_ui        (or any static server) then open http://localhost:8000/ui.html

Usage:
  python -m src.build_ui
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from dotenv import dotenv_values

CASES = Path("cases")
SUMMARY = CASES / "_runs" / "summary.json"
OUT = Path("ui.html")


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _triggers() -> dict:
    """case_id -> trigger row from the dataset case pack (context only)."""
    try:
        ds = Path(dotenv_values(".env").get("DATASET_DIR", ""))
        with open(ds / "case_pack.csv", newline="", encoding="utf-8") as f:
            return {r["case_id"]: r for r in csv.DictReader(f)}
    except (OSError, KeyError):
        return {}


def load_all() -> list[dict]:
    trig = _triggers()
    out = []
    files = sorted(p for p in CASES.glob("HHG-*.json")
                   if not p.name.endswith(".trace.json"))
    for p in files:
        ans = _load(p)
        if not ans:
            continue
        trace = _load(p.with_suffix(".trace.json"))
        out.append({
            "answer": ans,
            "trace": trace.get("tool_trace", []),
            "trigger": trig.get(ans.get("case_id"), {}),
        })
    return out


def build() -> str:
    data = {"cases": load_all(), "summary": _load(SUMMARY)}
    blob = json.dumps(data, ensure_ascii=False)
    html = (_HEAD + "<style>" + _CSS + "</style></head><body>"
            + _BODY + "<script>\nconst DATA = /*__DATA__*/;\n" + _JS
            + "</script></body></html>")
    return html.replace("/*__DATA__*/", blob)


def main() -> None:
    OUT.write_text(build(), encoding="utf-8")
    n = len(load_all())
    print(f"wrote {OUT.resolve()}  ({n} cases)")


_HEAD = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>Fraud Investigation Console — HHGOA</title>"
)

_CSS = r"""
:root{--bg:#0d1117;--panel:#161b22;--panel2:#1c2330;--ink:#e6edf3;--mut:#8b98a9;
--line:#2b3444;--acc:#63b3ed;--hi:#4fd1c5;--ok:#3fb950;--bad:#f85149;--warn:#e3b341;
--chip:#21324a}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif;display:flex;flex-direction:column}
header{padding:12px 20px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#111722,#0d1117)}
header h1{margin:0;font-size:17px}header .sub{color:var(--mut);font-size:12px;margin-top:3px}
.arch{display:flex;gap:8px;flex-wrap:wrap;margin-top:9px;align-items:center;font-size:11.5px;color:var(--mut)}
.arch b{color:var(--acc)}.arch .a{background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:3px 9px}
.arch .ar{color:var(--hi)}
.stat{margin-left:auto;display:flex;gap:14px}.stat div{text-align:right}.stat b{color:var(--hi);font-size:15px}
.main{flex:1;display:flex;min-height:0}
.side{width:270px;border-right:1px solid var(--line);overflow:auto;background:var(--panel)}
.ci{padding:9px 14px;border-bottom:1px solid var(--line);cursor:pointer}
.ci:hover{background:var(--panel2)}.ci.sel{background:var(--panel2);border-left:3px solid var(--acc);padding-left:11px}
.ci .id{font-weight:700}.ci .m{color:var(--mut);font-size:11.5px;margin-top:2px}
.detail{flex:1;overflow:auto;padding:20px 26px 60px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:0 0 14px}
.card h3{margin:0 0 10px;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut)}
.badge{display:inline-block;border-radius:999px;padding:2px 10px;font-size:11.5px;font-weight:700}
.b-fraud{background:rgba(248,81,73,.16);color:var(--bad)}.b-legit{background:rgba(63,185,80,.16);color:var(--ok)}
.b-unc{background:rgba(227,179,65,.16);color:var(--warn)}.b-g{background:rgba(79,209,197,.14);color:var(--hi)}
.chip{display:inline-block;background:var(--chip);border:1px solid var(--line);border-radius:6px;padding:1px 7px;font-size:11.5px;margin:2px 4px 2px 0;color:var(--acc);font-family:ui-monospace,Consolas,monospace}
.kv{display:flex;flex-wrap:wrap;gap:6px 22px;color:var(--mut)}.kv b{color:var(--ink)}
.meter{height:8px;border-radius:5px;background:#22120f;overflow:hidden;margin:6px 0}
.meter>i{display:block;height:100%;background:linear-gradient(90deg,#e3b341,#f85149)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.step{border-left:2px solid var(--line);padding:0 0 12px 14px;position:relative;margin-left:6px}
.step:before{content:'';position:absolute;left:-6px;top:3px;width:10px;height:10px;border-radius:50%;background:var(--acc)}
.step .t{font-weight:700;color:var(--hi);font-family:ui-monospace,Consolas,monospace}
.step .r{background:#0b1017;border:1px solid var(--line);border-radius:6px;padding:8px 10px;margin-top:6px;
font-family:ui-monospace,Consolas,monospace;font-size:11.5px;color:#b9c6d6;white-space:pre-wrap;word-break:break-word;max-height:150px;overflow:auto}
.mcp{color:var(--hi);font-size:10.5px;text-transform:uppercase;letter-spacing:.04em}
.act{border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:8px;background:var(--panel2)}
.act .a{font-weight:700}.act .rt{float:right;font-size:11px}.act .why{color:var(--mut);font-size:12px;margin-top:3px}
.ev{border-bottom:1px dashed var(--line);padding:7px 0}.ev:last-child{border:none}
.src{font-size:10.5px;text-transform:uppercase;color:var(--acc);margin-right:6px}
.chg{background:rgba(99,179,237,.1);border:1px solid var(--line);border-radius:6px;padding:6px 10px;color:var(--acc);font-size:12.5px;margin-bottom:10px}
.muted{color:var(--mut)}.none{color:var(--mut);font-style:italic}
h2.cid{margin:0 0 4px;font-size:22px}
.sys{margin-top:10px;border-top:1px solid var(--line);padding-top:8px}
.sys>summary{cursor:pointer;color:var(--acc);font-size:11.5px;list-style:none;user-select:none}
.sys>summary::-webkit-details-marker{display:none}
.sys>summary:before{content:'▸ ';color:var(--mut)}
.sys[open]>summary:before{content:'▾ '}
.ptable{width:100%;border-collapse:collapse;margin-top:8px;font-size:11.5px}
.ptable th,.ptable td{text-align:left;padding:4px 12px 4px 0;border-bottom:1px solid var(--line);color:var(--mut);white-space:nowrap}
.ptable th{color:var(--acc);font-weight:700;text-transform:uppercase;letter-spacing:.03em;font-size:10.5px}
.ptable td b{color:var(--ink)}
.tiles{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.tile{flex:1;min-width:118px;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:9px 12px}
.tile b{display:block;color:var(--hi);font-size:19px;font-family:ui-monospace,Consolas,monospace}
.tile span{color:var(--mut);font-size:11px}
.tstep{border-left:2px solid var(--line);margin:0 0 8px 6px;padding-left:14px;position:relative}
.tstep:before{content:'';position:absolute;left:-6px;top:6px;width:10px;height:10px;border-radius:50%;background:var(--acc)}
.tstep>summary{cursor:pointer;list-style:none;user-select:none;font-family:ui-monospace,Consolas,monospace;font-size:12px}
.tstep>summary::-webkit-details-marker{display:none}
.tstep .tn{color:var(--hi);font-weight:700}
.tstep .r{background:#0b1017;border:1px solid var(--line);border-radius:6px;padding:8px 10px;margin-top:6px;font-family:ui-monospace,Consolas,monospace;font-size:11.5px;color:#b9c6d6;white-space:pre-wrap;word-break:break-word;max-height:170px;overflow:auto}
.st-ok{color:var(--ok);font-size:10px;text-transform:uppercase;border:1px solid rgba(63,185,80,.4);border-radius:4px;padding:0 5px;margin-left:6px}
.st-err{color:var(--bad);font-size:10px;text-transform:uppercase;border:1px solid rgba(248,81,73,.4);border-radius:4px;padding:0 5px;margin-left:6px}
"""  # __CSS__
_BODY = r"""
<header>
  <h1>🕵️ Fraud Investigation Console <span class='muted' style='font-size:12px'>· HHGOA · TigerGraph</span></h1>
  <div class='sub'>Agentic GraphRAG (P3) · one shared LLM · evidence gathered live from TigerGraph through the MCP layer</div>
  <div class='arch'>
    <span class='a'>Investigator UI</span> →
    <span class='a'>Trigger</span> →
    <span class='a'>Agent <b>plan·act·observe</b> · shared LLM</span> →
    <span class='a ar'>GRIP MCP</span> →
    <span class='a'>TigerGraph <b>FraudInvestigation</b> + Vector KB</span> →
    <span class='a'>Policy · Schema · Validator</span> →
    <span class='a'>Verdict · NBA · SAR · <b>graph write-back</b></span>
    <span class='stat' id='stat'></span>
  </div>
  <details class='sys'><summary>System · models · pipeline comparison (P1 → P2 → P3)</summary>
    <div id='sys'></div>
  </details>
</header>
<div class='main'>
  <div class='side' id='side'></div>
  <div class='detail' id='detail'></div>
</div>
"""  # __BODY__
_JS = r"""
const $=s=>document.querySelector(s);
const esc=s=>(s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const VC={fraud:'b-fraud',legitimate:'b-legit',uncertain:'b-unc'};
const vbadge=v=>`<span class="badge ${VC[v]||'b-unc'}">${esc(v)}</span>`;
const committed=v=>Object.entries(v||{}).filter(([k])=>k!=='uncertain').reduce((s,[,n])=>s+n,0);
const list=(arr,f)=>(arr&&arr.length)?arr.map(f).join(''):'<span class="none">none</span>';
const chips=a=>list(a,x=>`<span class="chip">${esc(x)}</span>`);

function stat(){
  const P=(DATA.summary&&DATA.summary.pipelines)||{}, c=p=>P[p]?committed(P[p].verdicts):0;
  $('#stat').innerHTML=`<div><b>${c('P1')} → ${c('P2')} → ${c('P3')}</b><br>`
    +`<span class="muted">committed verdicts P1→P2→P3</span></div>`
    +`<div><b>${P.P3?P.P3.tool_calls_total:0}</b><br><span class="muted">live graph tool calls</span></div>`;
}
function sidebar(){
  $('#side').innerHTML=DATA.cases.map((c,i)=>{const k=c.answer.case;
    return `<div class="ci" data-i="${i}"><div class="id">${esc(c.answer.case_id)} ${vbadge(k.verdict)}</div>`
      +`<div class="m">${esc(k.pattern)} · p=${k.fraud_probability} · risk ${esc(c.trigger.risk_score||'—')}</div></div>`;
  }).join('');
  document.querySelectorAll('.ci').forEach(d=>d.onclick=()=>select(+d.dataset.i));
}
function select(i){
  document.querySelectorAll('.ci').forEach(d=>d.classList.toggle('sel',+d.dataset.i===i));
  renderDetail(DATA.cases[i]);
  $('#detail').scrollTop=0;
}
function nbaCol(title,items){
  return `<div class="card"><h3>${title}</h3>`+list(items,a=>
    `<div class="act"><span class="a">${esc(a.action)}</span>`
    +`<span class="rt badge b-g">route: ${esc(a.route)}</span>`
    +`<div class="why">${esc(a.reason)}</div></div>`)+`</div>`;
}
function renderDetail(c){
  const a=c.answer,k=a.case,t=c.trigger||{};
  const gid=k.written_to_graph?`<span class="badge b-g">✔ graph: ${esc(k.graph_case_id)}</span>`:'';
  const pc=Math.round((k.fraud_probability||0)*100);
  const trace=(c.trace||[]).map(s=>{
    const arc=Object.entries(s.args||{}).map(([x,y])=>`<span class="chip">${esc(x)}=${esc(y)}</span>`).join('');
    const st=s.ok?`<span class="st-ok">ok</span>`:`<span class="st-err">error</span>`;
    const body=s.ok?esc(s.result_summary||'(no result)'):esc(s.error||s.result_summary||'(failed)');
    return `<details class="tstep" open><summary><span class="tn">${s.step}. ${esc(s.tool)}</span> `
      +`<span class="mcp">▸ via TigerGraph MCP</span>${st} ${arc}</summary>`
      +`<div class="r">${body}</div></details>`;}).join('')
    ||'<span class="none">P1/P2 use a one-shot pre-assembled bundle — no live tool loop.</span>';
  const nsteps=(c.trace||[]).length;
  const tiles=`<div class="tiles">`
    +`<div class="tile"><b>${(+a.latency_s||0).toFixed(1)}s</b><span>total latency</span></div>`
    +`<div class="tile"><b>${(a.tokens||0).toLocaleString()}</b><span>LLM tokens</span></div>`
    +`<div class="tile"><b>${a.tool_calls||0}</b><span>graph tool calls</span></div>`
    +`<div class="tile"><b>${nsteps}</b><span>MCP steps traced</span></div></div>`;
  const ev=list(k.evidence,e=>`<div class="ev"><span class="src">${esc(e.source)}</span>${esc(e.claim)}`
    +`<div class="muted" style="font-size:11.5px">ref: ${esc(e.ref)} ${chips(e.entity_ids)}</div></div>`);
  const er=list(a.evidence_requests,r=>`<div class="ev"><b>${esc(r.type)}</b> <span class="muted">(after step ${r.asked_after_step})</span>`
    +`<div class="muted" style="font-size:12px">assumed: ${esc(r.assumed_response)}</div></div>`);
  const nba=a.next_best_actions||{initial:[],final:[]};
  const chg=(nba.what_changed&&nba.what_changed!=='nothing')?`<div class="chg"><b>What changed after evidence:</b> ${esc(nba.what_changed)}</div>`:'';
  const sar=(a.sar&&a.sar.file)?`<div class="card"><h3>SAR — filed</h3><div class="muted">${esc(a.sar.reason)}</div>`
    +`<p>${esc(a.sar.narrative)}</p><div class="kv"><span>subjects: ${chips(a.sar.subjects)}</span>`
    +`<span><b>$${(a.sar.total_amount_usd||0).toLocaleString()}</b></span>`
    +`<span>dates: ${esc((a.sar.activity_dates||[]).join(' → '))}</span></div></div>`:'';
  window.__H={a,k,t,gid,pc,trace,tiles,ev,er,nba,chg,sar};
  paint2();
}
function paint2(){const {a,k,t,gid,pc,trace,tiles,ev,er,nba,chg,sar}=window.__H;
  $('#detail').innerHTML=
    `<h2 class="cid">${esc(a.case_id)} ${vbadge(k.verdict)} ${gid}</h2>`
   +`<div class="card"><div class="kv"><span>pattern <b>${esc(k.pattern)}</b></span>`
   +`<span>status <b>${esc(k.status)}</b></span><span>exposure <b>$${(k.exposure_usd||0).toLocaleString()}</b></span>`
   +`<span>tokens <b>${(a.tokens||0).toLocaleString()}</b></span><span>tool calls <b>${a.tool_calls||0}</b></span>`
   +`<span>latency <b>${(+a.latency_s||0).toFixed(1)}s</b></span></div>`
   +`<div class="muted" style="margin-top:8px;font-size:12px">confidence of fraud · p=${k.fraud_probability}</div>`
   +`<div class="meter"><i style="width:${pc}%"></i></div>`
   +`<div class="muted" style="font-size:12px">stop: ${esc(a.stop_reason)}</div></div>`
   +`<div class="card"><h3>① Trigger</h3><div class="kv"><span>type <b>${esc(t.trigger_type||'—')}</b></span>`
   +`<span>flagged txn <b>${esc(t.flagged_txn_id||'—')}</b></span><span>card <b>${esc(t.card_id||'—')}</b></span>`
   +`<span>customer <b>${esc(t.customer_id||'—')}</b></span><span>risk <b>${esc(t.risk_score||'—')}</b></span></div>`
   +`<p class="muted" style="margin:8px 0 0">${esc(t.trigger_text||'')}</p></div>`
   +`<div class="card"><h3>② Investigation — evidence returned from TigerGraph via MCP</h3>${tiles}${trace}</div>`
   +`<div class="grid2"><div class="card"><h3>③ Findings</h3>${ev}</div>`
   +`<div class="card"><h3>④ Uncertainty — evidence requested before deciding</h3>${er}</div></div>`
   +chg+`<div class="grid2">`+nbaCol('⑤ Initial — before extra evidence',nba.initial)
   +nbaCol('Final — after evidence received',nba.final)+`</div>`+sar
   +`<div class="card"><h3>⑥ Case record</h3><p>${esc(k.summary)}</p>`
   +`<div class="kv"><span>affected txns: ${chips(k.affected_txn_ids)}</span></div>`
   +`<div class="kv" style="margin-top:6px"><span>connected cards: ${chips(k.connected_card_ids)}</span></div>`
   +`<div class="kv" style="margin-top:6px"><span>devices: ${chips(k.connected_device_profiles)}</span></div>`
   +`<div class="kv" style="margin-top:6px"><span>similar prior: ${chips(k.similar_prior_cases)}</span></div></div>`;
}
function sysPanel(){
  const s=DATA.summary||{}, P=s.pipelines||{};
  const row=(name,label)=>{const p=P[name]; if(!p) return '';
    const v=p.verdicts||{};
    const mix=Object.entries(v).map(([kk,n])=>`${esc(kk)}:${n}`).join('  ')||'—';
    return `<tr><td><b>${name}</b> ${label}</td><td>${p.tool_calls_total}</td>`
      +`<td>${(p.tokens_total||0).toLocaleString()}</td><td>${p.latency_total_s}s</td>`
      +`<td>${p.n_clean}/${p.n_ok}</td><td>${mix}</td></tr>`;};
  $('#sys').innerHTML=
    `<div class="kv" style="margin-bottom:2px">`
    +`<span>shared LLM <b>${esc(s.model||'—')}</b></span>`
    +`<span>graph <b>FraudInvestigation</b> · TigerGraph</span>`
    +`<span>MCP layer <b>GRIP</b> · stdio</span>`
    +`<span>knowledge <b>vector doc-layer</b></span>`
    +`<span>cases <b>${s.n_cases||0}</b></span></div>`
    +`<table class="ptable"><thead><tr><th>pipeline</th><th>tool calls</th><th>tokens</th>`
    +`<th>latency</th><th>clean</th><th>verdict mix</th></tr></thead><tbody>`
    +row('P1','Plain RAG')+row('P2','GraphRAG')+row('P3','Agentic GraphRAG')
    +`</tbody></table>`
    +`<div class="muted" style="font-size:11px;margin-top:8px">Model · policy · schema · validator held constant across P1/P2/P3 — only graph exposure varies. `
    +`P3 is the deliverable: each case is also written back to the graph as an InvestigationCase.</div>`;
}
stat();sysPanel();sidebar();select(0);
"""  # __JS__


if __name__ == "__main__":
    main()

