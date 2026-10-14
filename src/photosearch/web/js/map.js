// Map: where you've been, each place shown by its best photo, and regions to fly to.
// Plain scripts sharing one global scope, loaded in order by index.html; no build step.

/* ---------- map: where you've been, each place shown by its best photo ---------- */
const WM = { map: null, cells: null, layer: null, sel: null };
views.world = async () => {
  try { await loadLeaflet(); } catch { $("wstatus").textContent = "The map needs internet (it loads from OpenStreetMap). Your photos stay here."; return; }
  if (WM.map) return setTimeout(() => WM.map.invalidateSize());
  WM.map = L.map("wmap", { zoomControl: false, worldCopyJump: true, minZoom: 1 }).setView([30, 0], 2);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(WM.map);
  L.control.zoom({ position: "bottomright" }).addTo(WM.map);
  WM.layer = L.layerGroup().addTo(WM.map);
  $("wstatus").textContent = "finding where your photos were taken…";
  let w;
  try { w = (await api("/api/world")).results; WM.cells = w.cells; }
  catch (e) { $("wstatus").textContent = e.message; return; }
  const n = WM.cells.reduce((a, c) => a + c.n, 0);
  $("wstatus").textContent = `${n.toLocaleString()} photos in ${WM.cells.length.toLocaleString()} places · tap one to see it`;
  WM.map.on("zoomend", drawWorld);
  // open on home, the busiest region; the chips fly to the others
  showRegions(w.regions);
  const b = WM.regions[0].bounds;
  WM.map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: [30, 30] });
  drawWorld();
};
// Places closer than a pin's width at this zoom merge into one pin, shown by the photo of the busiest of them.
function drawWorld() {
  const m = WM.map, groups = [];
  for (const c of [...WM.cells].sort((a, b) => b.n - a.n)) {
    const p = m.latLngToLayerPoint([c.lat, c.lon]);
    const g = groups.find(g => g.p.distanceTo(p) < 58);
    if (g) { g.cells.push(c); g.n += c.n; } else groups.push({ p, cells: [c], n: c.n, head: c });
  }
  WM.layer.clearLayers();
  for (const g of groups) {
    const s = Math.round(38 + 9 * Math.log10(g.n)), h = g.head;
    const icon = L.divIcon({ className: "", iconSize: [s, s], iconAnchor: [s / 2, s / 2],
      html: `<div class="pin" style="--s:${s}px"><img src="/thumb/${h.cover}.jpg" alt=""><b>${g.n > 999 ? (g.n / 1000).toFixed(1) + "k" : g.n}</b></div>` });
    L.marker([h.lat, h.lon], { icon, title: placeLabel(g), riseOnHover: true, zIndexOffset: g.n }).on("click", () => openPlace(g)).addTo(WM.layer);
  }
}
function placeLabel(g) {
  const names = [...new Set(g.cells.map(c => c.place).filter(Boolean))].slice(0, 3);
  if (names.length) return names.join(", ");
  const h = g.head, named = WM.cells.filter(c => c.place);  // no name here: the nearest place that has one
  const near = named.reduce((a, c) => km([h.lat, h.lon], [c.lat, c.lon]) < km([h.lat, h.lon], [a.lat, a.lon]) ? c : a, named[0]);
  return near ? "Near " + near.place : "Somewhere";
}
async function openPlace(g) {
  const lats = g.cells.map(c => c.lat), lons = g.cells.map(c => c.lon);
  const spread = km([Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]);
  if (g.cells.length > 1 && spread > 3 && WM.map.getZoom() < 13)  // a bunch of places: zoom in to tell them apart
    return WM.map.flyToBounds(L.latLngBounds(g.cells.map(c => [c.lat, c.lon])).pad(0.3), { duration: .8 });
  const lat = lats.reduce((a, x, k) => a + x * g.cells[k].n, 0) / g.n, lon = lons.reduce((a, x, k) => a + x * g.cells[k].n, 0) / g.n;
  const first = g.cells.map(c => c.first).sort()[0], last = g.cells.map(c => c.last).sort().at(-1);
  $("wsheet").classList.add("on");
  $("wsh").innerHTML = `<div><div class="kick">${first.slice(0, 4) === last.slice(0, 4) ? first.slice(0, 4) : `${first.slice(0, 4)}–${last.slice(0, 4)}`}</div>
    <h2>${esc(placeLabel(g))}</h2><div class="status">${g.n.toLocaleString()} photos</div></div><span class="sp"></span>
    <button class="ghost tiny" id="wplay">▶ Slideshow</button><button class="ibtn" id="wclose" title="close">✕</button>`;
  $("wclose").onclick = () => $("wsheet").classList.remove("on");
  $("wgrid").innerHTML = skeleton(6);
  const r = (await api("/api/near", { lat, lon, km: Math.max(1, spread / 2 + 0.6), k: 60 })).results;
  $("wplay").onclick = () => openFrame({ list: r.photos, title: placeLabel(g) });
  bindGrid($("wgrid"), r.photos);
}

/* ---------- map regions: the places you've been, as chips to fly to ---------- */
function showRegions(regions) {
  WM.regions = [...regions].sort((a, b) => b.n - a.n);
  $("wregions").innerHTML = WM.regions.slice(0, 16).map((r, k) =>
    `<button class="pill" data-k="${k}">${k ? "" : "🏠 "}${esc(r.name)} <small>${fmtN(r.n)}</small></button>`).join("")
    + `<button class="pill" data-k="all">🌍 Everywhere</button>`;
  $("wregions").onclick = e => {
    const k = e.target.closest("[data-k]")?.dataset.k; if (k == null) return;
    $("wsheet").classList.remove("on");
    const b = k === "all" ? WM.regions.reduce((a, r) => [Math.min(a[0], r.bounds[0]), Math.min(a[1], r.bounds[1]), Math.max(a[2], r.bounds[2]), Math.max(a[3], r.bounds[3])], [90, 180, -90, -180])
                          : WM.regions[k].bounds;
    WM.map.flyToBounds([[b[0], b[1]], [b[2], b[3]]], { padding: [40, 40], maxZoom: 14, duration: 1.1 });
  };
}
