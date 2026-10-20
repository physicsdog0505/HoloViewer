"""Dependency-free internal dashboard shell; intentionally outside site/**."""


def render_dashboard() -> str:
    return """<!doctype html>
<html lang="zh-Hant"><meta charset="utf-8"><title>PTT History Admin</title>
<style>body{font:14px system-ui;margin:2rem;max-width:1200px}nav button,button{margin:.25rem;padding:.55rem}.panel{display:none}.panel.active{display:block}pre{white-space:pre-wrap;background:#f5f5f5;padding:1rem}.warn{color:#9b4b00}</style>
<h1>PTT History Admin Dashboard</h1>
<p class="warn">唯讀監控；HTTP 200 或程序存活不代表資料完整。重新執行同步尚未開放。</p>
<nav><button data-tab="data_coverage">Data Coverage</button><button data-tab="sync_monitor">Sync Monitor</button><button data-tab="system_health">System Health</button></nav>
<button id="refresh-all">重新整理全部狀態</button>
<button disabled title="future design only">重新執行同步（未来功能）</button>
<section id="data_coverage" class="panel active"><h2>Data Coverage</h2><label>篩選 <select id="coverage-filter"><option value="all">全部</option><option value="COMPLETE">完整</option><option value="REPAIR_NEEDED">缺漏／待同步</option><option value="CONFLICT">衝突</option><option value="UNKNOWN">未知</option></select></label><button data-refresh="data_coverage">重新整理狀態</button><pre></pre></section>
<section id="sync_monitor" class="panel"><h2>Sync Monitor</h2><button data-refresh="sync_monitor">重新整理狀態</button><pre></pre></section>
<section id="system_health" class="panel"><h2>System Health</h2><button data-refresh="system_health">重新整理狀態</button><pre></pre></section>
<script>
const cache={};
const show=(name,data)=>{cache[name]=data;let shown=data;if(name==='data_coverage'){const filter=document.querySelector('#coverage-filter').value;if(filter!=='all'){shown=JSON.parse(JSON.stringify(data));const payload=shown?.payload;if(Array.isArray(payload?.sources))payload.sources=payload.sources.filter(row=>JSON.stringify(row).includes(filter));}}document.querySelector('#'+name+' pre').textContent=JSON.stringify(shown,null,2);};
async function refresh(section){const q=section?'?section='+encodeURIComponent(section):'';try{const r=await fetch('/admin/status'+q,{method:'GET',credentials:'omit'});const data=await r.json();if(section)show(section,data[section]);else Object.entries(data).forEach(([k,v])=>show(k,v));}catch(error){if(section)show(section,{availability:'unavailable',error:String(error)});}}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.id===b.dataset.tab));});
document.querySelectorAll('[data-refresh]').forEach(b=>b.onclick=()=>refresh(b.dataset.refresh));
document.querySelector('#coverage-filter').onchange=()=>show('data_coverage',cache.data_coverage||{});
document.querySelector('#refresh-all').onclick=()=>refresh();refresh();
</script></html>"""
