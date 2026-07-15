# Genera el visualizador HTML del grafo de inferencia desde los CSVs de graph-ai/datasets.
import json
from pathlib import Path

import pandas as pd

DS = Path(__file__).parent / "datasets"
OUT = Path(__file__).parent / "grafo_vivia.html"

amen = pd.read_csv(DS / "amenidades.csv").fillna("")
temas = pd.read_csv(DS / "temas.csv")
tipos = pd.read_csv(DS / "tipos_propiedad.csv")
ops = pd.read_csv(DS / "operaciones.csv")
auds = pd.read_csv(DS / "audiencias.csv")
buckets = pd.read_csv(DS / "buckets.csv").fillna("")
evoca = pd.read_csv(DS / "pesos_evoca.csv")
priors = pd.read_csv(DS / "pesos_priors.csv")
regla_aud = pd.read_csv(DS / "reglas_audiencia.csv")
bloqueos = pd.read_csv(DS / "bloqueos.csv")
drafts = json.load(open(DS / "drafts_ejemplo.json"))

nodes = []
for _, r in ops.iterrows():
    nodes.append({"id": f"op:{r['operacion']}", "label": r["operacion"], "col": 0, "grupo": "Operación", "detalle": r["tono"]})
for _, r in tipos.iterrows():
    nodes.append({"id": f"tipo:{r['tipo']}", "label": r["tipo"], "col": 0, "grupo": "Tipo de propiedad", "detalle": r["narrativa"]})
for _, r in buckets.iterrows():
    nodes.append({"id": f"bk:{r['bucket']}", "label": r["bucket"], "col": 0, "grupo": "Atributos (buckets)", "detalle": f"{r['condicion']} — {r['descripcion']}".strip(" —")})
for _, r in amen.iterrows():
    nodes.append({"id": f"am:{r['amenidad']}", "label": r["nombre_db"], "col": 0, "grupo": "Amenidades", "detalle": f"aliases: {r['aliases']}"})
for _, r in temas.iterrows():
    nodes.append({"id": f"tema:{r['tema']}", "label": r["tema"].replace("_", " "), "col": 1, "grupo": "Temas", "detalle": f"“{r['frase_1']}” / “{r['frase_2']}”"})
for _, r in auds.iterrows():
    nodes.append({"id": f"aud:{r['audiencia']}", "label": r["audiencia"].replace("_", " "), "col": 2, "grupo": "Audiencias", "detalle": r["frase"]})

def src_id(origen: str, origen_tipo: str) -> str:
    return {"tipo": f"tipo:{origen}", "operacion": f"op:{origen}", "bucket": f"bk:{origen}"}[origen_tipo]

edges = []
for _, r in evoca.iterrows():
    for tema in evoca.columns[1:]:
        if pd.notna(r[tema]):
            edges.append({"s": f"am:{r['amenidad']}", "t": f"tema:{tema}", "w": float(r[tema]), "k": "evoca"})
for _, r in priors.iterrows():
    edges.append({"s": src_id(r["origen"], r["origen_tipo"]), "t": f"tema:{r['tema']}", "w": float(r["peso"]), "k": "prior"})
for _, r in regla_aud.iterrows():
    edges.append({"s": src_id(r["origen"], r["origen_tipo"]), "t": f"aud:{r['audiencia']}", "w": float(r["peso"]), "k": "sugiere"})
for _, r in bloqueos.iterrows():
    edges.append({"s": src_id(r["origen"], r["origen_tipo"]), "t": f"tema:{r['tema_bloqueado']}", "w": -10.0, "k": "bloquea", "why": r["porque"]})

alias_map = {}
for _, r in amen.iterrows():
    for a in str(r["aliases"]).split("|") + [r["nombre_db"]]:
        if a:
            alias_map[a.strip().lower()] = r["amenidad"]

data = {
    "nodes": nodes, "edges": edges, "alias": alias_map,
    "drafts": [d["draft"] for d in drafts],
    "hechos": {"a_estrenar": "a estrenar", "construccion_reciente": "construcción reciente",
               "con_historia": "más de 30 años: carácter e historia", "area_amplia": "superficie amplia",
               "area_compacta": "espacio compacto y eficiente", "en_condominio": "forma parte de un condominio",
               "sin_estacionamiento": "no mencionar estacionamientos"},
}

HTML = r"""<title>Grafo de inferencia — Vivia</title>
<style>
:root{
  --bg:#FAF9F6; --panel:#FFFFFF; --ink:#22303A; --muted:#687885; --line:#E4E1D8;
  --evoca:#3E7CB1; --prior:#8E63B5; --sugiere:#3F8F63; --bloquea:#C24A3F;
  --tema:#B67A1F; --accent:#0F766E; --chip:#EFEDE6; --hi:#FFF3D6;
}
@media (prefers-color-scheme: dark){:root{
  --bg:#14191F; --panel:#1C232B; --ink:#E7ECF0; --muted:#94A2AE; --line:#2B3540;
  --evoca:#6FA8DC; --prior:#B394D9; --sugiere:#6FBF92; --bloquea:#E07B6F;
  --tema:#D9A24A; --accent:#3AA99F; --chip:#242E38; --hi:#3A3320;
}}
:root[data-theme="light"]{
  --bg:#FAF9F6; --panel:#FFFFFF; --ink:#22303A; --muted:#687885; --line:#E4E1D8;
  --evoca:#3E7CB1; --prior:#8E63B5; --sugiere:#3F8F63; --bloquea:#C24A3F;
  --tema:#B67A1F; --accent:#0F766E; --chip:#EFEDE6; --hi:#FFF3D6;
}
:root[data-theme="dark"]{
  --bg:#14191F; --panel:#1C232B; --ink:#E7ECF0; --muted:#94A2AE; --line:#2B3540;
  --evoca:#6FA8DC; --prior:#B394D9; --sugiere:#6FBF92; --bloquea:#E07B6F;
  --tema:#D9A24A; --accent:#3AA99F; --chip:#242E38; --hi:#3A3320;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;margin:0;padding:20px}
header{max-width:1500px;margin:0 auto 14px}
h1{font-size:20px;font-weight:650;margin:0 0 2px}
header p{color:var(--muted);margin:0;max-width:72ch}
.top{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:14px 0 10px}
select{background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:7px 10px;font:inherit}
button.clear{background:none;border:1px solid var(--line);color:var(--muted);border-radius:8px;padding:6px 10px;font:inherit;cursor:pointer}
button.clear:hover{color:var(--ink)}
.legend{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);font-size:12px;align-items:center}
.legend span{display:inline-flex;align-items:center;gap:5px}
.legend i{display:inline-block;width:22px;height:0;border-top:3px solid;border-radius:2px}
.legend i.blq{border-top-style:dashed}
.wrap{max-width:1500px;margin:0 auto;display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:14px}
@media (max-width:1000px){.wrap{grid-template-columns:1fr}}
.graphbox{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:auto;max-height:86vh}
svg{display:block}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;align-self:start;position:sticky;top:14px;max-height:86vh;overflow:auto}
.panel h2{font-size:11px;font-weight:650;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 8px}
.panel .empty{color:var(--muted)}
.dec{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-bottom:10px}
.dec b{font-weight:650}
.dec .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.07em}
.score{display:grid;grid-template-columns:150px 1fr 38px;gap:8px;align-items:center;margin:3px 0;font-size:12.5px}
.score .bar{height:7px;border-radius:4px;background:var(--chip);overflow:hidden}
.score .bar i{display:block;height:100%;background:var(--tema);border-radius:4px}
.score .num{font-family:ui-monospace,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums;text-align:right;color:var(--muted)}
.score.win .num,.score.win .name{color:var(--ink);font-weight:650}
.score.blk .name{color:var(--bloquea);text-decoration:line-through}
.score .name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.why{color:var(--muted);font-size:12px;margin:6px 0 0;border-left:2px solid var(--bloquea);padding-left:8px}
.node rect{fill:var(--panel);stroke:var(--line);rx:7}
.node text{fill:var(--ink);font-size:11.5px}
.node.col1 rect{stroke:var(--tema)}
.node.col2 rect{stroke:var(--sugiere)}
.node.activo rect{fill:var(--hi);stroke:var(--tema);stroke-width:1.6}
.node.dim{opacity:.18}
.grp{fill:var(--muted);font-size:10px;letter-spacing:.09em;text-transform:uppercase;font-weight:600}
path.e{fill:none;opacity:.42}
path.e.evoca{stroke:var(--evoca)} path.e.prior{stroke:var(--prior)}
path.e.sugiere{stroke:var(--sugiere)} path.e.bloquea{stroke:var(--bloquea);stroke-dasharray:6 5}
path.e.dim{opacity:.05} path.e.hi{opacity:.95}
footer{max-width:1500px;margin:10px auto 0;color:var(--muted);font-size:12px}
@media (prefers-reduced-motion: no-preference){path.e,.node{transition:opacity .15s}}
</style>
<header>
  <h1>Grafo de inferencia — Vivia</h1>
  <p>El enrutador editorial: las fuentes del draft activan temas y audiencias por aristas ponderadas
  (grosor = peso 0.3 / 0.6 / 0.9); los bloqueos (rojo punteado) son calles en sentido contrario.
  Pasa el cursor sobre un nodo para aislar sus rutas, o simula un draft para ver la decisión completa.</p>
  <div class="top">
    <select id="draftSel"><option value="">— Simular draft… —</option></select>
    <button class="clear" id="btnClear">Limpiar</button>
    <div class="legend">
      <span><i style="border-color:var(--evoca)"></i>evoca (amenidad→tema)</span>
      <span><i style="border-color:var(--prior)"></i>prior (tipo/operación/bucket→tema)</span>
      <span><i style="border-color:var(--sugiere)"></i>sugiere (→audiencia)</span>
      <span><i class="blq" style="border-color:var(--bloquea)"></i>bloquea (−10)</span>
    </div>
  </div>
</header>
<div class="wrap">
  <div class="graphbox"><svg id="g" role="img" aria-label="Grafo de inferencia"></svg></div>
  <aside class="panel" id="panel"><h2>Decisión del grafo</h2>
    <p class="empty">Selecciona un draft para propagar la inferencia y ver la traza de decisión.</p>
  </aside>
</div>
<footer>Fuente: notebooks/graph-ai/datasets/ · k=2 temas · umbral 0.5 · desempate por arista contribuyente de mayor peso · metodología en init.md</footer>
<script>
const D = __DATA__;
const YEAR = new Date().getFullYear();
const COLX = [30, 560, 940], PILL_W = [250, 210, 230], ROW = 27, GRP_GAP = 34;
const svg = document.getElementById('g');
const NS = 'http://www.w3.org/2000/svg';
const byId = {};

// layout: columna 0 agrupada, columnas 1-2 centradas verticalmente
let maxY = 0;
{
  let y = 20; let g = '';
  for (const n of D.nodes.filter(n => n.col === 0)) {
    if (n.grupo !== g) { g = n.grupo; y += (y > 20 ? GRP_GAP : 14); n.grpLabel = g; }
    n.x = COLX[0]; n.y = y; y += ROW; byId[n.id] = n;
  }
  maxY = y + 10;
  for (const c of [1, 2]) {
    const col = D.nodes.filter(n => n.col === c);
    let y0 = (maxY - col.length * ROW * 1.5) / 2;
    col.forEach((n, i) => { n.x = COLX[c]; n.y = y0 + i * ROW * 1.5; byId[n.id] = n; });
  }
}
svg.setAttribute('viewBox', `0 0 1210 ${maxY}`);
svg.setAttribute('width', '1210'); svg.setAttribute('height', maxY);

const edgeEls = [];
for (const e of D.edges) {
  const s = byId[e.s], t = byId[e.t];
  const x1 = s.x + PILL_W[s.col], y1 = s.y + 9, x2 = t.x, y2 = t.y + 9;
  const p = document.createElementNS(NS, 'path');
  p.setAttribute('d', `M${x1},${y1} C${x1 + 90},${y1} ${x2 - 90},${y2} ${x2},${y2}`);
  p.setAttribute('class', `e ${e.k}`);
  p.setAttribute('stroke-width', e.k === 'bloquea' ? 2 : ({0.3: 1.1, 0.6: 2.1, 0.9: 3.4}[e.w] || 2));
  const ti = document.createElementNS(NS, 'title');
  ti.textContent = e.k === 'bloquea' ? `BLOQUEO: ${e.why}` : `${e.k} · peso ${e.w}`;
  p.appendChild(ti); svg.appendChild(p); e.el = p; edgeEls.push(e);
}
for (const n of D.nodes) {
  if (n.grpLabel) {
    const gt = document.createElementNS(NS, 'text');
    gt.setAttribute('x', n.x); gt.setAttribute('y', n.y - 8);
    gt.setAttribute('class', 'grp'); gt.textContent = n.grpLabel; svg.appendChild(gt);
  }
  const g = document.createElementNS(NS, 'g');
  g.setAttribute('class', `node col${n.col}`);
  const r = document.createElementNS(NS, 'rect');
  r.setAttribute('x', n.x); r.setAttribute('y', n.y - 4);
  r.setAttribute('width', PILL_W[n.col]); r.setAttribute('height', 24);
  r.setAttribute('rx', 7);
  const tx = document.createElementNS(NS, 'text');
  tx.setAttribute('x', n.x + 9); tx.setAttribute('y', n.y + 12); tx.textContent = n.label;
  const ti = document.createElementNS(NS, 'title'); ti.textContent = n.detalle || n.label;
  g.appendChild(r); g.appendChild(tx); g.appendChild(ti); svg.appendChild(g); n.el = g;
  g.addEventListener('mouseenter', () => focusNode(n.id));
  g.addEventListener('mouseleave', () => { if (!pinned) unfocus(); });
}
let pinned = null;
function focusNode(id) {
  const inc = new Set();
  for (const e of edgeEls) { if (e.s === id || e.t === id) { e.el.classList.add('hi'); e.el.classList.remove('dim'); inc.add(e.s); inc.add(e.t); } else { e.el.classList.add('dim'); e.el.classList.remove('hi'); } }
  for (const n of D.nodes) n.el.classList.toggle('dim', !inc.has(n.id) && n.id !== id);
}
function unfocus() {
  for (const e of edgeEls) e.el.classList.remove('dim', 'hi');
  for (const n of D.nodes) n.el.classList.remove('dim');
}

// ── simulador: activación → propagación → selección ──
function bucketsDe(d) {
  const ant = YEAR - d.constructionYear, b = [];
  if (ant <= 1) b.push('a_estrenar'); else if (ant <= 10) b.push('construccion_reciente');
  if (ant > 30) b.push('con_historia');
  if (d.areaM2 >= 180) b.push('area_amplia'); if (d.areaM2 <= 50) b.push('area_compacta');
  if (d.bedrooms >= 4) b.push('rec_4_mas'); else if (d.bedrooms >= 2) b.push('rec_2_3');
  else if (d.bedrooms === 1) b.push('rec_1');
  if (d.condominium) b.push('en_condominio'); if (d.parkingSpaces === 0) b.push('sin_estacionamiento');
  return b;
}
const norm = s => s.toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').trim();
const aliasN = {}; for (const [k, v] of Object.entries(D.alias)) aliasN[norm(k)] = v;

function simular(d) {
  const activos = new Set([`op:${d.availableToRent ? 'RENTA' : 'VENTA'}`]);
  for (const n of D.nodes) if (n.col === 0 && n.grupo === 'Tipo de propiedad' && norm(n.label) === norm(d.propertyType.name)) activos.add(n.id);
  const bks = bucketsDe(d); bks.forEach(b => activos.add(`bk:${b}`));
  const desconocidas = [];
  for (const a of d.amenities) { const c = aliasN[norm(a)]; if (c) activos.add(`am:${c}`); else desconocidas.push(a); }

  const score = {}, contrib = {}, bloqueadosPor = {};
  for (const e of edgeEls) {
    if (!activos.has(e.s)) continue;
    const key = e.t;
    score[key] = (score[key] || 0) + e.w;
    (contrib[key] = contrib[key] || []).push(e);
    if (e.k === 'bloquea') (bloqueadosPor[key] = bloqueadosPor[key] || []).push(e);
  }
  const temasRank = D.nodes.filter(n => n.col === 1).map(n => ({
    n, s: score[n.id] || 0, blk: !!bloqueadosPor[n.id],
    max: Math.max(0, ...(contrib[n.id] || []).filter(e => e.k !== 'bloquea').map(e => e.w)),
  })).sort((a, b) => (b.s - a.s) || (b.max - a.max));
  const ganadores = temasRank.filter(t => !t.blk && t.s >= 0.5).slice(0, 2);
  const audRank = D.nodes.filter(n => n.col === 2).map(n => ({n, s: score[n.id] || 0}))
    .sort((a, b) => b.s - a.s);
  const audiencia = audRank[0] && audRank[0].s > 0 ? audRank[0] : null;
  const idsGan = new Set(ganadores.map(g => g.n.id));
  const protag = [];
  for (const g of ganadores) for (const e of (contrib[g.n.id] || []))
    if (e.k === 'evoca') protag.push({am: byId[e.s].label, w: e.w});
  protag.sort((a, b) => b.w - a.w);
  return {activos, desconocidas, temasRank, ganadores, audiencia, bloqueadosPor, contrib, idsGan,
          protag: [...new Map(protag.map(p => [p.am, p])).values()].slice(0, 2), bks};
}

const sel = document.getElementById('draftSel');
D.drafts.forEach((d, i) => {
  const o = document.createElement('option'); o.value = i;
  o.textContent = `${d.id} · ${d.propertyType.name} · ${d.availableToRent ? 'RENTA' : 'VENTA'} · ${d.address.neighborhoodName}`;
  sel.appendChild(o);
});
document.getElementById('btnClear').addEventListener('click', () => { sel.value = ''; pinned = null; unfocus(); for (const n of D.nodes) n.el.classList.remove('activo'); render(null); });
sel.addEventListener('change', () => {
  if (sel.value === '') { pinned = null; unfocus(); render(null); return; }
  const d = D.drafts[+sel.value]; const r = simular(d); pinned = true;
  for (const n of D.nodes) n.el.classList.toggle('activo', r.activos.has(n.id) || r.idsGan.has(n.id) || (r.audiencia && n.id === r.audiencia.n.id));
  for (const n of D.nodes) n.el.classList.remove('dim');
  for (const e of edgeEls) {
    const rel = r.activos.has(e.s) && (r.idsGan.has(e.t) || (r.audiencia && e.t === r.audiencia.n.id) || e.k === 'bloquea');
    e.el.classList.toggle('hi', rel); e.el.classList.toggle('dim', !rel && !r.activos.has(e.s));
  }
  render(r, d);
});

function render(r, d) {
  const p = document.getElementById('panel');
  if (!r) { p.innerHTML = '<h2>Decisión del grafo</h2><p class="empty">Selecciona un draft para propagar la inferencia y ver la traza de decisión.</p>'; return; }
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const hechos = r.bks.filter(b => D.hechos[b]).map(b => D.hechos[b]);
  let h = `<h2>Decisión del grafo — ${esc(d.id)}</h2>`;
  h += `<div class="dec"><div class="k">Resumen para el LLM</div>` +
    `<div><b>Temas:</b> ${r.ganadores.map(g => esc(g.n.label)).join('; ') || '<i>ninguno supera el umbral</i>'}</div>` +
    `<div><b>Audiencia:</b> ${r.audiencia ? esc(r.audiencia.n.detalle) : '—'}</div>` +
    `<div><b>Protagonistas:</b> ${r.protag.map(x => esc(x.am)).join(', ') || '—'}</div>` +
    (hechos.length ? `<div><b>Hechos:</b> ${esc(hechos.join('; '))}</div>` : '') +
    (r.desconocidas.length ? `<div><b>Sin ángulo aprobado:</b> ${esc(r.desconocidas.join(', '))} <span class="k">(solo por nombre)</span></div>` : '') +
    `</div>`;
  h += `<h2>Scores de temas</h2>`;
  const mx = Math.max(0.001, ...r.temasRank.filter(t => !t.blk).map(t => t.s));
  for (const t of r.temasRank) {
    const win = r.idsGan.has(t.n.id);
    h += `<div class="score${win ? ' win' : ''}${t.blk ? ' blk' : ''}">` +
      `<span class="name">${esc(t.n.label)}</span>` +
      `<span class="bar"><i style="width:${t.blk ? 0 : Math.round(100 * t.s / mx)}%"></i></span>` +
      `<span class="num">${t.blk ? 'BLQ' : t.s.toFixed(1)}</span></div>`;
  }
  const razones = Object.values(r.bloqueadosPor).flat().map(e => `<p class="why"><b>${esc(byId[e.t].label)}</b> bloqueado por ${esc(byId[e.s].label)}: ${esc(e.why)}</p>`);
  if (razones.length) h += `<h2 style="margin-top:12px">Bloqueos activos</h2>` + razones.join('');
  p.innerHTML = h;
}
</script>
"""

OUT.write_text(HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False)), encoding="utf-8")
print(f"OK → {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")
