// Galaxy: the whole library as a map of look-alikes.
// Plain scripts sharing one global scope, loaded in order by index.html; no build step.

/* ---------- galaxy ---------- */
const G = { data: null, s: 1, ox: 0, oy: 0, hi: null, imgs: new Map(), vis: [], raf: 0 };
const yearColor = (y, a = 1) => {
  if (!y) return `rgba(150,150,160,${a * 0.6})`;  // undated
  const t = (y - G.y0) / Math.max(1, G.y1 - G.y0);
  return `hsla(${250 - 215 * t}, 85%, ${55 + 8 * t}%, ${a})`;
};
const cv = $("gcanvas"), cx = cv.getContext("2d");

async function openGalaxy() {
  resizeGalaxy();
  if (G.data || G.loading) return;
  G.loading = true;
  $("gstatus").textContent = "mapping your library… (the first time takes a minute)";
  try {
    G.data = (await api("/api/galaxy")).results;
  } catch (e) { $("gstatus").textContent = "couldn't map: " + e.message; G.loading = false; return; }
  G.y0 = Math.min(...G.data.year.filter(Boolean)); G.y1 = Math.max(...G.data.year);
  $("gy0").textContent = G.y0; $("gy1").textContent = G.y1;
  $("ggrad").style.background = `linear-gradient(90deg, ${[0, .25, .5, .75, 1].map(t => yearColor(G.y0 + t * (G.y1 - G.y0))).join(",")})`;
  $("gstatus").textContent = `${G.data.uuids.length.toLocaleString()} photos · similar photos sit together · scroll to zoom · drag to pan · click a photo`;
  Object.assign($("gyr"), { min: G.y0, max: G.y1, value: G.y1 });
  fitGalaxy();
  if (G.hi) flyTo(G.hi);
  loadPeople().then(p => { $("gppl").innerHTML = p.slice(0, 8).map(x => `<img src="/thumb/${x.cover}.jpg" alt="" title="${esc(x.name)}" data-name="${esc(x.name)}">`).join(""); }).catch(() => {});
};
function resizeGalaxy() {
  const r = cv.getBoundingClientRect(), d = devicePixelRatio || 1;
  cv.width = r.width * d; cv.height = r.height * d; cx.setTransform(d, 0, 0, d, 0, 0);
  G.w = r.width; G.h = r.height; draw();
}
function fitGalaxy() {
  G.s0 = G.s = Math.min(G.w, G.h) * 0.88 / 1000;
  G.ox = (G.w - 1000 * G.s) / 2; G.oy = (G.h - 1000 * G.s) / 2 + 16; draw();
}
addEventListener("resize", () => { if ($("galaxy").classList.contains("on")) resizeGalaxy(); });
function draw() { if (!G.raf) G.raf = requestAnimationFrame(render); }
function render() {
  G.raf = 0;
  cx.clearRect(0, 0, G.w, G.h);
  const d = G.data; if (!d) return;
  const n = d.uuids.length, zoom = G.s / G.s0;
  const vis = [];
  for (let i = 0; i < n; i++) {
    if (G.upto && (!d.year[i] || d.year[i] > G.upto)) continue;  // not taken yet, at this point in the years
    const sx = d.x[i] * 1000 * G.s + G.ox, sy = d.y[i] * 1000 * G.s + G.oy;
    if (sx > -60 && sx < G.w + 60 && sy > -60 && sy < G.h + 60) vis.push([i, sx, sy]);
  }
  const ts = Math.min(110, 4 * zoom);  // thumbnails grow as you zoom in
  const thumbs = ts >= 12 && vis.length <= 1500;
  G.vis = vis; G.ts = thumbs ? ts : 0;
  const lit = G.hi;
  for (const [i, sx, sy] of vis) {
    const on = !lit || lit.has(d.uuids[i]);
    if (thumbs) {
      const im = thumb(d.uuids[i]);
      cx.globalAlpha = on ? 1 : 0.12;
      if (im.complete && im.naturalWidth) {
        const r = Math.min(im.naturalWidth, im.naturalHeight);
        cx.drawImage(im, (im.naturalWidth - r) / 2, (im.naturalHeight - r) / 2, r, r, sx - ts / 2, sy - ts / 2, ts, ts);
      } else { cx.fillStyle = yearColor(d.year[i]); cx.fillRect(sx - ts / 2, sy - ts / 2, ts, ts); }
    } else {
      if (lit && on) continue;  // drawn on top below
      cx.globalAlpha = 1;
      cx.fillStyle = on ? yearColor(d.year[i], 0.85) : "rgba(120,120,140,.18)";
      const r = Math.min(6, 2.2 * Math.sqrt(zoom)) * (G.upto && d.year[i] === G.upto ? 2 : 1);  // this year's photos stand out
      cx.fillRect(sx - r / 2, sy - r / 2, r, r);
    }
  }
  cx.globalAlpha = 1;
  if (lit && !thumbs) {  // matches glow on top of the dimmed map
    for (const [i, sx, sy] of vis) {
      if (!lit.has(d.uuids[i])) continue;
      cx.beginPath(); cx.arc(sx, sy, 4.5, 0, 7);
      cx.fillStyle = yearColor(d.year[i]); cx.shadowColor = cx.fillStyle; cx.shadowBlur = 10; cx.fill();
    }
    cx.shadowBlur = 0;
  }
  if (zoom < 4 && !lit) {  // region names, biggest first, skipping any that would overlap one already drawn
    cx.textAlign = "center"; cx.textBaseline = "middle";
    const placed = [];
    for (const g of [...d.regions].sort((a, b) => b.n - a.n)) {
      if (!g.name) continue;
      const sx = g.x * 1000 * G.s + G.ox, sy = g.y * 1000 * G.s + G.oy;
      cx.font = `600 ${Math.round(11 + Math.min(6, g.n / 120))}px -apple-system, system-ui`;
      const w = cx.measureText(g.name).width / 2 + 6, h = 11;
      if (placed.some(([x, y, pw]) => Math.abs(x - sx) < w + pw && Math.abs(y - sy) < 2 * h)) continue;
      placed.push([sx, sy, w]);
      cx.lineWidth = 4; cx.strokeStyle = "rgba(0,0,0,.75)"; cx.strokeText(g.name, sx, sy);
      cx.fillStyle = "rgba(255,255,255,.92)"; cx.fillText(g.name, sx, sy);
    }
  }
}
function thumb(u) {
  let im = G.imgs.get(u);
  if (!im) { im = new Image(); im.onload = draw; im.src = `/thumb/${u}.jpg`; G.imgs.set(u, im); }
  return im;
}
function pick(mx, my) {
  let best = -1, bd = Math.max(8, G.ts / 2) ** 2;
  for (const [i, sx, sy] of G.vis) {
    const dd = (sx - mx) ** 2 + (sy - my) ** 2;
    if (dd < bd) { bd = dd; best = i; }
  }
  return best;
}
const pointers = new Map(); let dragged = false, pinch0 = 0;
cv.onpointerdown = e => { cv.setPointerCapture(e.pointerId); pointers.set(e.pointerId, [e.offsetX, e.offsetY]); dragged = false;
  if (pointers.size === 2) { const [a, b] = [...pointers.values()]; pinch0 = Math.hypot(a[0] - b[0], a[1] - b[1]); } };
cv.onpointermove = e => {
  const prev = pointers.get(e.pointerId);
  if (!prev) {  // hover
    const i = G.data ? pick(e.offsetX, e.offsetY) : -1, tip = $("gtip");
    if (i < 0) { tip.style.display = "none"; return; }
    tip.innerHTML = `<img src="/thumb/${G.data.uuids[i]}.jpg"><div style="padding:3px 2px 0">${G.data.year[i] || "date unknown"}</div>`;
    tip.style.display = "block";
    tip.style.left = Math.min(e.offsetX + 14, G.w - 200) + "px"; tip.style.top = Math.min(e.offsetY + 14, G.h - 220) + "px";
    return;
  }
  pointers.set(e.pointerId, [e.offsetX, e.offsetY]);
  if (pointers.size === 2) {
    const [a, b] = [...pointers.values()], dd = Math.hypot(a[0] - b[0], a[1] - b[1]);
    zoomAt((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, dd / pinch0); pinch0 = dd; dragged = true; return;
  }
  const dx = e.offsetX - prev[0], dy = e.offsetY - prev[1];
  if (Math.abs(dx) + Math.abs(dy) > 2) dragged = true;
  G.ox += dx; G.oy += dy; $("gtip").style.display = "none"; draw();
};
cv.onpointerup = e => {
  pointers.delete(e.pointerId);
  if (!dragged && G.data) {
    const i = pick(e.offsetX, e.offsetY);
    if (i >= 0) galaxyOpen(i);
  }
};
cv.onpointerleave = () => { $("gtip").style.display = "none"; };
function zoomAt(mx, my, f) {
  const s = Math.max(G.s0 * 0.5, Math.min(G.s0 * 200, G.s * f)); f = s / G.s;
  G.ox = mx - (mx - G.ox) * f; G.oy = my - (my - G.oy) * f; G.s = s; draw();
}
cv.onwheel = e => { e.preventDefault(); zoomAt(e.offsetX, e.offsetY, Math.exp(-e.deltaY * 0.0022)); };
cv.ondblclick = e => zoomAt(e.offsetX, e.offsetY, 2.5);
async function galaxyOpen(i) {
  lightbox([(await api("/api/info", { uuid: G.data.uuids[i] })).results], 0);
}
views.galaxy = arg => {  // #galaxy/beach lights up a search; #galaxy/?person=Name, everyone's photos of them
  const [qs, ps] = (arg || "").split("?"), q = decodeURIComponent(qs || ""), person = new URLSearchParams(ps || "").get("person");
  $("q").value = q; openGalaxy();
  person ? lightUp("👤 " + person, { person, k: 6000 }, `all of ${person}'s photos`) : lightUp(q, { q, k: 250 }, `the 250 best matches for “${q}”`);
};
async function lightUp(key, params, what) {
  if (!key) return clearHi();
  if (G.litQ === key) return;
  G.litQ = key;
  const r = await api("/api/search", params);
  if (G.litQ !== key) return;
  G.hi = new Set(r.results.map(x => x.uuid)); $("glit").hidden = false; $("glitq").textContent = key.startsWith("👤") ? key : "✦ " + key;
  $("gstatus").textContent = `lit: ${what}`;
  draw(); flyTo(G.hi);
}
// glide to where most of the lit photos are (the closest 70% around their middle)
function flyTo(set) {
  const d = G.data; if (!d || !set?.size || !G.w) return;
  const pts = []; d.uuids.forEach((u, i) => { if (set.has(u)) pts.push([d.x[i], d.y[i]]); });
  if (!pts.length) return;
  const mid = k => pts.map(p => p[k]).sort((a, b) => a - b)[pts.length >> 1], mx = mid(0), my = mid(1);
  const dist = pts.map(p => Math.hypot(p[0] - mx, p[1] - my)).sort((a, b) => a - b);
  const r = Math.max(0.035, dist[Math.floor(dist.length * 0.7)]);
  const s1 = Math.max(G.s0 * 0.5, Math.min(G.s0 * 60, Math.min(G.w, G.h) * 0.42 / (r * 1000)));
  const ox1 = G.w / 2 - mx * 1000 * s1, oy1 = G.h / 2 - my * 1000 * s1, [s0, ox0, oy0] = [G.s, G.ox, G.oy], t0 = performance.now();
  const step = t => {
    const k = Math.min(1, (t - t0) / 900), e = 1 - (1 - k) ** 3;
    G.s = s0 + (s1 - s0) * e; G.ox = ox0 + (ox1 - ox0) * e; G.oy = oy0 + (oy1 - oy0) * e; render();
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
// the years: the slider shows the library as it was up to a year; ▶ plays it growing from the first
function setUpto(y) { G.upto = y; $("gyl").textContent = y ? `up to ${y}` : "All years"; $("gbig").textContent = y || ""; draw(); }
function stopGrow() { clearInterval(G.grow); G.grow = 0; $("gplay").textContent = "▶"; }
$("gyr").oninput = () => { stopGrow(); const v = +$("gyr").value; setUpto(v >= G.y1 ? null : v); };
$("gplay").onclick = () => {
  if (G.grow) return stopGrow();
  if (!G.data) return;
  let y = G.y0; $("gplay").textContent = "❚❚"; setUpto(y); $("gyr").value = y;
  G.grow = setInterval(() => {
    if (++y > G.y1) { stopGrow(); setUpto(null); $("gyr").value = G.y1; return; }
    setUpto(y); $("gyr").value = y;
  }, 750);
};
$("gppl").onclick = e => { const n = e.target.dataset.name; if (n) go("galaxy/?person=" + encodeURIComponent(n)); };
leave.galaxy = () => stopGrow();
function clearHi() {
  const was = G.litQ; G.hi = null; G.litQ = null; $("glit").hidden = true; draw();
  if (was && location.hash !== "#galaxy") history.replaceState(null, "", "#galaxy");
}
$("glit").onclick = clearHi;
