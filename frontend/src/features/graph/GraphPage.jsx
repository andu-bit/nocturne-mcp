import React, { useEffect, useRef, useState, useMemo } from 'react';
import { getGraph } from '../../lib/api';

// ---------------------------------------------------------------------------
// Nocturne Memory 3D Graph — FULL PAGE.
// Uses the proven software-2D-canvas force-simulation renderer as the PRIMARY
// (guaranteed to render in every browser, no WebGL dependency, never blank).
// Drag to orbit · scroll to zoom · hover highlights · auto-rotate when idle.
// Data: GET /api/browse/graph (nodes + edges from nocturne_data.db).
// ---------------------------------------------------------------------------

const DOMAIN_COLORS = {
  core: "#00ddff", owl: "#aa66ff", project: "#22cc66", sop: "#ffbb33",
  vault: "#ff8844", writer: "#ff66aa", game: "#ff4455", notes: "#55ddff",
  narrative: "#ff88cc",
};
const DOMAIN_LABELS = {
  core: "Core", owl: "Owl", project: "Project", sop: "SOP", vault: "Vault",
  writer: "Writer", game: "Game", notes: "Notes", narrative: "Narrative",
};

const SIM = { rest: 3.0, k: 0.05, rep: 26, damp: 0.86, center: 0.002, maxR: 15 };

function buildSim3D(graph) {
  const nodes = (graph.nodes || []).map((n) => {
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    const r = 2 + Math.random() * 5;
    return {
      id: n.id, label: n.label, group: n.group || "?",
      color: n.color || DOMAIN_COLORS[n.group] || "#888888",
      val: n.val || 2,
      x: r * Math.sin(phi) * Math.cos(theta),
      y: r * Math.cos(phi),
      z: r * Math.sin(phi) * Math.sin(theta),
      vx: 0, vy: 0, vz: 0,
    };
  });
  const byId = {};
  nodes.forEach((n) => { byId[n.id] = n; });
  const edges = (graph.edges || [])
    .map((e) => ({ source: byId[e.source], target: byId[e.target], weight: e.weight || 1 }))
    .filter((e) => e.source && e.target);
  return { nodes, edges, byId };
}

function stepSim3D(sim) {
  const { nodes, edges } = sim;
  const { rest, k, rep, damp, center, maxR } = SIM;
  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i];
    a.vx *= damp; a.vy *= damp; a.vz *= damp;
    for (let j = i + 1; j < nodes.length; j++) {
      const b = nodes[j];
      let dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
      let d2 = dx * dx + dy * dy + dz * dz;
      if (d2 < 0.01) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; dz = Math.random() - 0.5; d2 = 1; }
      const d = Math.sqrt(d2);
      const f = rep / d2;
      const fx = (dx / d) * f, fy = (dy / d) * f, fz = (dz / d) * f;
      a.vx += fx; a.vy += fy; a.vz += fz;
      b.vx -= fx; b.vy -= fy; b.vz -= fz;
    }
    a.vx += -a.x * center; a.vy += -a.y * center; a.vz += -a.z * center;
  }
  for (let i = 0; i < edges.length; i++) {
    const e = edges[i];
    if (!e.source || !e.target) continue;
    const dx = e.target.x - e.source.x;
    const dy = e.target.y - e.source.y;
    const dz = e.target.z - e.source.z;
    const d = Math.max(Math.sqrt(dx * dx + dy * dy + dz * dz), 0.01);
    const f = (d - rest) * k * e.weight;
    const fx = (dx / d) * f, fy = (dy / d) * f, fz = (dz / d) * f;
    e.source.vx += fx; e.source.vy += fy; e.source.vz += fz;
    e.target.vx -= fx; e.target.vy -= fy; e.target.vz -= fz;
  }
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i];
    n.x += n.vx; n.y += n.vy; n.z += n.vz;
    const r2 = n.x * n.x + n.y * n.y + n.z * n.z;
    if (r2 > maxR * maxR) {
      const r = Math.sqrt(r2); const s = maxR / r;
      n.x *= s; n.y *= s; n.z *= s;
    }
  }
}

function createCamera() {
  return { theta: -0.6, phi: 0.35, dist: 42, fov: 50, minD: 20, maxD: 110 };
}

function projectNode(cam, p, w, h) {
  const ct = Math.cos(cam.theta), st = Math.sin(cam.theta);
  const cp = Math.cos(cam.phi), sp = Math.sin(cam.phi);
  const cx = cam.dist * cp * st, cy = cam.dist * sp, cz = cam.dist * cp * ct;
  const dl = Math.sqrt(cx * cx + cy * cy + cz * cz) || 1;
  const vx = -cx / dl, vy = -cy / dl, vz = -cz / dl;
  let rx = -vz, ry = 0, rz = vx;
  const rl = Math.sqrt(rx * rx + rz * rz) || 1; rx /= rl; rz /= rl;
  let ux = ry * vz - rz * vy, uy = rz * vx - rx * vz, uz = rx * vy - ry * vx;
  const ul = Math.sqrt(ux * ux + uy * uy + uz * uz) || 1; ux /= ul; uy /= ul; uz /= ul;
  const relX = p.x - cx, relY = p.y - cy, relZ = p.z - cz;
  const px = relX * rx + relY * ry + relZ * rz;
  const py = relX * ux + relY * uy + relZ * uz;
  const depth = relX * vx + relY * vy + relZ * vz;
  if (depth <= 0.1) return { sx: NaN, sy: NaN, depth: Infinity, visible: false };
  const F = (h / 2) / Math.tan((cam.fov * Math.PI) / 360);
  const scale = F / depth;
  return { sx: w / 2 + px * scale, sy: h / 2 - py * scale, depth, visible: true };
}
const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

// ---- software-2D canvas renderer (primary, always works) ------------------
function buildSoftwareView(container, graph, w, h, onHover, onSelect) {
  const canvas = document.createElement("canvas");
  canvas.style.cssText = "display:block;width:100%;height:100%;background:#0a0a0f;cursor:grab;touch-action:pan-y;";
  container.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  const sim = buildSim3D(graph);
  const cam = createCamera();
  const stars = [];
  for (let i = 0; i < 120; i++) stars.push({ x: (Math.random() - 0.5) * 160, y: (Math.random() - 0.5) * 160, z: (Math.random() - 0.5) * 160 });

  let raf = 0, dragging = false, lastX = 0, lastY = 0, downX = 0, downY = 0, idleFrames = 0, disposed = false, hoverRef = null;

  function resize(nw, nh) {
    w = Math.max(1, nw); h = Math.max(1, nh);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  resize(w, h);
  function projectAll() { return sim.nodes.map((n) => { const p = projectNode(cam, n, w, h); p.node = n; return p; }); }
  function draw() {
    if (disposed) return;
    for (let s = 0; s < 3; s++) stepSim3D(sim);
    if (!dragging) { idleFrames += 1; if (idleFrames > 120) cam.theta += 0.0025; }
    ctx.fillStyle = "#0a0a0f"; ctx.fillRect(0, 0, w, h);
    // stars
    ctx.fillStyle = "rgba(120,140,180,0.5)";
    for (let i = 0; i < stars.length; i++) {
      const p = projectNode(cam, stars[i], w, h);
      if (!p.visible) continue;
      ctx.globalAlpha = clamp(30 / p.depth, 0.1, 0.5);
      const r = Math.max(0.4, 1.1 * (40 / p.depth));
      ctx.fillRect(p.sx, p.sy, r, r);
    }
    ctx.globalAlpha = 1;
    const proj = projectAll();
    const projByNode = new Map(); proj.forEach((p) => projByNode.set(p.node, p));
    // edges
    const edgesDrawn = [];
    for (let i = 0; i < sim.edges.length; i++) {
      const e = sim.edges[i];
      const ps = projByNode.get(e.source), pt = projByNode.get(e.target);
      if (!ps || !pt || !ps.visible || !pt.visible) continue;
      edgesDrawn.push({ e, ps, pt, depth: (ps.depth + pt.depth) / 2 });
    }
    edgesDrawn.sort((a, b) => b.depth - a.depth);
    ctx.lineWidth = 1.2;
    for (let i = 0; i < edgesDrawn.length; i++) {
      const { e, ps, pt, depth } = edgesDrawn[i];
      ctx.strokeStyle = e.source.color || "#8899bb";
      ctx.globalAlpha = clamp(0.5 - (depth - 22) * 0.012, 0.1, 0.5);
      ctx.beginPath(); ctx.moveTo(ps.sx, ps.sy); ctx.lineTo(pt.sx, pt.sy); ctx.stroke();
    }
    ctx.globalAlpha = 1;
    // nodes
    const nodeDraw = proj.filter((p) => p.visible).sort((a, b) => b.depth - a.depth);
    for (let i = 0; i < nodeDraw.length; i++) {
      const p = nodeDraw[i], n = p.node;
      const worldR = 0.55 + n.val * 0.22;
      const F = (h / 2) / Math.tan((cam.fov * Math.PI) / 360);
      const r = Math.max(2, worldR * (F / p.depth));
      const alpha = clamp(1.25 - p.depth / 80, 0.5, 1);
      const isHover = hoverRef && hoverRef.id === n.id;
      ctx.beginPath(); ctx.arc(p.sx, p.sy, isHover ? r + 4 : r, 0, Math.PI * 2);
      ctx.fillStyle = n.color; ctx.globalAlpha = isHover ? 1 : alpha; ctx.fill();
      if (isHover) { ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 2; ctx.stroke(); }
      // label
      ctx.globalAlpha = clamp(alpha, 0.5, 1);
      ctx.fillStyle = n.color;
      ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(n.label, p.sx, p.sy - r - 5);
    }
    ctx.globalAlpha = 1;
    raf = requestAnimationFrame(draw);
  }
  function pick(ev) {
    const rect = canvas.getBoundingClientRect();
    const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    const proj = projectAll();
    let best = null, bestD = Infinity;
    for (let i = 0; i < proj.length; i++) {
      const p = proj[i]; if (!p.visible) continue;
      const n = p.node;
      const F = (h / 2) / Math.tan((cam.fov * Math.PI) / 360);
      const r = Math.max(8, (0.55 + n.val * 0.22) * (F / p.depth));
      const ddx = p.sx - mx, ddy = p.sy - my, d2 = ddx * ddx + ddy * ddy;
      if (d2 < r * r && d2 < bestD) { best = n; bestD = d2; }
    }
    onHover(best);
    return best;
  }
  function onPointerDown(ev) { dragging = true; lastX = ev.clientX; lastY = ev.clientY; downX = ev.clientX; downY = ev.clientY; idleFrames = 0; canvas.style.cursor = "grabbing"; try { canvas.setPointerCapture(ev.pointerId); } catch (e) {} }
  function onPointerMove(ev) {
    if (dragging) { cam.theta -= (ev.clientX - lastX) * 0.008; cam.phi = clamp(cam.phi + (ev.clientY - lastY) * 0.008, -1.45, 1.45); lastX = ev.clientX; lastY = ev.clientY; idleFrames = 0; }
    else hoverRef = pick(ev);
  }
  function onPointerUp(ev) {
    const moved = Math.abs(ev.clientX - downX) + Math.abs(ev.clientY - downY);
    dragging = false; canvas.style.cursor = "grab";
    try { canvas.releasePointerCapture(ev.pointerId); } catch (e) {}
    if (moved < 5) { const n = pick(ev); if (n && onSelect) onSelect(n); }
  }
  function onWheel(ev) { ev.preventDefault(); cam.dist = clamp(cam.dist * Math.exp(ev.deltaY * 0.001), cam.minD, cam.maxD); }
  canvas.addEventListener("pointerdown", onPointerDown);
  canvas.addEventListener("pointermove", onPointerMove);
  canvas.addEventListener("pointerup", onPointerUp);
  canvas.addEventListener("pointerleave", onPointerUp);
  canvas.addEventListener("wheel", onWheel, { passive: false });
  function dispose() { disposed = true; cancelAnimationFrame(raf); canvas.removeEventListener("pointerdown", onPointerDown); canvas.removeEventListener("pointermove", onPointerMove); canvas.removeEventListener("pointerup", onPointerUp); canvas.removeEventListener("pointerleave", onPointerUp); canvas.removeEventListener("wheel", onWheel); if (canvas.parentNode === container) container.removeChild(canvas); }
  raf = requestAnimationFrame(draw);
  return { resize, dispose };
}

// ---- Full-page component ---------------------------------------------------
export default function GraphPage() {
  const containerRef = useRef(null);
  const [graph, setGraph] = useState(null);
  const [error, setError] = useState(null);
  const [size, setSize] = useState({ w: 1200, h: 800 });
  const [hover, setHover] = useState(null);
  const [domain, setDomain] = useState("");
  const viewRef = useRef(null);

  useEffect(() => {
    getGraph().then(setGraph).catch((e) => setError(String((e && e.message) || e)));
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !graph || !graph.nodes || !graph.nodes.length) return;
    const w = container.clientWidth || 1200;
    const h = container.clientHeight || 800;
    const view = buildSoftwareView(container, graph, w, h, setHover, (n) => setDomain(n.group === domain ? "" : n.group));
    viewRef.current = view;
    const ro = new ResizeObserver((entries) => {
      for (const en of entries) {
        const r = en.contentRect;
        if (r.width > 50 && r.height > 50 && viewRef.current) viewRef.current.resize(r.width, r.height);
      }
    });
    ro.observe(container);
    return () => { ro.disconnect(); if (viewRef.current === view) viewRef.current = null; view.dispose(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph]);

  const domainChips = useMemo(() => {
    if (!graph) return [];
    const counts = {};
    (graph.nodes || []).forEach((n) => { counts[n.group] = (counts[n.group] || 0) + 1; });
    return Object.keys(counts).map((d) => ({ id: d, label: DOMAIN_LABELS[d] || d, count: counts[d] })).sort((a, b) => b.count - a.count);
  }, [graph]);

  return (
    <div className="relative w-full h-full bg-[#0a0a0f] text-slate-200 overflow-hidden">
      <div ref={containerRef} className="absolute inset-0" />

      {/* Minimal top overlay: title + legend, non-blocking */}
      <div className="absolute top-3 left-3 z-10 pointer-events-none">
        <div className="text-lg font-bold text-slate-100 flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 shadow-[0_0_12px_rgba(34,211,238,0.9)]" />
          Nocturne Memory — 3D Graph
        </div>
        {graph && (
          <div className="text-xs text-slate-500 mt-0.5 font-mono">
            {graph.nodes.length} nodes · {graph.edges.length} edges · drag orbit · scroll zoom
          </div>
        )}
        {error && <div className="text-xs text-rose-400 mt-2 pointer-events-auto">{String(error)}</div>}
      </div>

      {/* Domain legend (click to isolate) */}
      {domainChips.length > 0 && (
        <div className="absolute top-3 right-3 z-10 flex flex-wrap gap-1.5 justify-end max-w-[50%]">
          {domainChips.map((g) => (
            <button
              key={g.id}
              onClick={() => setDomain(domain === g.id ? "" : g.id)}
              title={g.label}
              className="pointer-events-auto flex items-center gap-1.5 px-2 py-1 rounded-full text-[11px] border transition-colors"
              style={{
                borderColor: domain === g.id ? (DOMAIN_COLORS[g.id] || "#888") : "rgba(148,163,184,0.3)",
                background: domain === g.id ? (DOMAIN_COLORS[g.id] || "#888") + "22" : "rgba(0,0,0,0.5)",
                color: domain === g.id ? DOMAIN_COLORS[g.id] : "#cbd5e1",
              }}
            >
              <span className="w-2 h-2 rounded-full inline-block" style={{ background: DOMAIN_COLORS[g.id] || "#888" }} />
              {g.label}
              <span className="opacity-60">{g.count}</span>
            </button>
          ))}
        </div>
      )}

      {/* Hover tooltip */}
      {hover && (
        <div className="absolute z-10 px-3 py-1.5 rounded-lg text-xs pointer-events-none" style={{ top: "calc(100% - 3rem)", left: "0.75rem", background: "rgba(10,14,20,0.92)", border: "1px solid " + (hover.color || "#888") }}>
          <span style={{ fontWeight: 600, color: hover.color || "#fff" }}>{hover.label}</span>
          <span className="opacity-50 ml-2">{hover.id}</span>
        </div>
      )}
    </div>
  );
}
