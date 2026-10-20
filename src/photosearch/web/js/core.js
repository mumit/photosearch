// Helpers every view uses, routing (#mode/argument), photo tiles in justified rows, and the lightbox.
// Plain scripts sharing one global scope, loaded in order by index.html; no build step.

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
const api = async (path, params = {}) => {
  const res = await fetch(path + "?" + new URLSearchParams(params));
  if (res.status === 401) { location.replace("/login"); throw new Error("sign in first"); }
  const r = await res.json();
  if (r.error) throw new Error(r.error);
  return r;
};
const post = async (path, body) => {
  const r = await (await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) })).json();
  if (r.error) throw new Error(r.error);
  return r.results;
};
// A photo kept only in iCloud has a tiny local preview. Shown big, ask the server to fetch its full-size copy
// (~1 s, or longer when iCloud is slow) and swap that in, unless the view has moved on to another photo by then.
async function sharpen(img, uuid) {
  const still = () => img.isConnected && img.src.includes(uuid);
  try {
    let st = (await post("/api/sharp", { uuids: [uuid] }))[uuid];
    if (st !== "fetching") return;
    for (let i = 0; i < 40 && st === "fetching" && still(); i++) {
      await new Promise(ok => setTimeout(ok, 1500));
      st = (await api("/api/sharp", { uuids: uuid })).results[uuid];
    }
    if (st === "sharp" && still()) img.src = `/photo/${uuid}.jpg?sharp`;
  } catch {}  // the preview stays: fine
}
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
                set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} } };
const once = fn => { let p; const f = () => p ??= fn().catch(e => { p = null; throw e; }); f.reset = () => { p = null; }; return f; };
// someone's portrait, around their face where Photos knows it (people.py), else the whole thumbnail
const faceSrc = (uuid, who) => `/face/${uuid}.jpg?who=${encodeURIComponent(who)}`;
const short = place => (place || "").split(",")[0];
const longDate = (d, opt = { weekday:"long", month:"long", day:"numeric", year:"numeric" }) => {
  const [y, m, day] = d.split("-").map(Number); return new Date(y, m - 1, day).toLocaleDateString(undefined, opt);
};
// A photo's date as sure as it is: dates from the date detective may be a month or a year
const photoDate = (x, opt) => x.undated ? "date unknown" : x.approx === "year" ? x.date.slice(0, 4)
  : x.approx === "month" ? longDate(x.date, { month: opt?.month || "long", year: "numeric" }) : longDate(x.date, opt);
const ago = n => !n ? "Earlier this year" : n === 1 ? "A year ago" : `${n} years ago`;
// the header's height, for the full-screen modes to fit under it
new ResizeObserver(([e]) => document.documentElement.style.setProperty("--hh", e.target.offsetHeight + "px")).observe(document.querySelector("header"));

/* ---------- routing: #mode or #mode/argument, so back and forward work everywhere ---------- */
const views = {}, leave = {};
let tab = null;
function route() {
  const h = location.hash.slice(1) || "home", k = h.indexOf("/");
  const next = k < 0 ? h : h.slice(0, k), arg = k < 0 ? "" : h.slice(k + 1);
  lbOff(); closeSugg(); closePanel();
  if (tab && tab !== next) leave[tab]?.();
  tab = views[next] ? next : "home";
  document.querySelectorAll("#tabs a").forEach(a => a.classList.toggle("on", a.hash === "#" + ({ edit: "stories", math: "play", person: "home", album: "albums", cleanup: "albums", clutter: "albums", judge: "play" }[tab] || tab)));
  document.querySelectorAll("main section").forEach(s => s.classList.toggle("on", s.id === tab));
  $("q").placeholder = PLACEHOLDER[tab] || PLACEHOLDER.home;
  if (!["search", "galaxy", "time"].includes(tab)) $("q").value = "";
  if (tab !== "frame") { frameOff(); lastHash = "#" + h; }
  $("omni").classList.toggle("bare", tab === "galaxy" || tab === "time");
  if (tab !== "search" && FIELDS.some(k => F[k])) { for (const k of FIELDS) F[k] = ""; AUTO = new Set(); renderChips(); }  // chips describe the results on show
  views[tab](arg);
}
// modes cross-fade where the browser can (the header stays put); the photo views need no help
addEventListener("hashchange", () => document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches
  ? document.startViewTransition(route) : route());
const go = h => { if (location.hash !== "#" + h) location.hash = h; else route(); };
const PLACEHOLDER = { home: "Search your photos… e.g. “kids in the snow”", galaxy: "Light up the galaxy… e.g. beach",
                      time: "Something that happens every year… e.g. birthday cake" };
addEventListener("keydown", e => {  // "?": the shortcuts
  if (e.key === "?" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName)) $("keys").hidden = !$("keys").hidden;
  else if (e.key === "Escape") $("keys").hidden = true;
});
$("keys").onclick = () => { $("keys").hidden = true; };
addEventListener("keydown", e => {  // "/" or ⌘K: to the search box from anywhere
  if ((e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName)) || ((e.metaKey || e.ctrlKey) && e.key === "k")) {
    e.preventDefault(); lbOff(); $("q").focus(); $("q").select();
  }
});

/* ---------- photo tiles ---------- */
const clampAr = ar => Math.min(2.4, Math.max(0.55, ar || 1));
const loaded = "this.classList.add('ok')";
const mmss = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
// A video found by a later moment (`photosearch videos`) shows that moment's frame, and says when, and whether it was heard.
const tileSrc = x => x.frame != null ? `/frame/${x.uuid}/${x.frame}.jpg` : `/thumb/${x.uuid}.jpg`;
const vidLabel = x => x.at != null ? `${x.heard ? "🔊 heard" : "▶"} at ${mmss(x.at)}` : "▶ video";
function tileHTML(x, i, { badge, caption = true } = {}) {
  return `<figure class="tile" data-i="${i}" style="--ar:${clampAr(x.ar)}"${x.kind === "video" ? ` data-v="${x.uuid}"` : ""}>
    <img loading="lazy" src="${tileSrc(x)}" alt="" onload="${loaded}">
    ${badge ? `<b class="badge">${esc(badge)}</b>` : ""}${x.kind === "video" ? `<span class="vid">${vidLabel(x)}</span>` : ""}
    ${caption ? `<figcaption><span>${photoDate(x, { month:"short", day:"numeric", year:"numeric" })}</span><span>${esc(short(x.place))}</span></figcaption>` : ""}
  </figure>`;
}
// Justified rows, like a photo book: each row fills the width and every photo keeps its shape.
const innerW = el => { const c = getComputedStyle(el); return el.clientWidth - parseFloat(c.paddingLeft) - parseFloat(c.paddingRight); };
function justify(el, items, base = 0) {
  const W = innerW(el), gap = 6, h = Math.max(110, Math.min(230, W / 2.8));
  if (!W) return "";
  let html = "", row = [], sum = 0;
  const flush = last => {
    if (!row.length) return;
    const rh = Math.min((W - gap * (row.length - 1)) / sum, last ? h * 1.1 : Infinity);
    const fill = !last || rh < h * 1.1;
    html += `<div class="jrow" style="height:${rh.toFixed(1)}px">` + row.map(([x, i]) =>
      tileHTML(x, i).replace('style="', `style="flex:${fill ? clampAr(x.ar) + " 1 0" : "none"};width:${(clampAr(x.ar) * rh).toFixed(1)}px;`)).join("") + "</div>";
    row = []; sum = 0;
  };
  items.forEach((x, i) => {
    row.push([x, base + i]); sum += clampAr(x.ar);
    if (sum * h + gap * (row.length - 1) >= W) flush(false);
  });
  flush(true);
  return html;
}
// A grid of photos: clicking one opens it big, and the layout redoes itself when the width changes.
function bindGrid(el, results, render = () => justify(el, results)) {
  el._render = render; el.innerHTML = render();
  el.onclick = e => { const t = e.target.closest(".tile"); if (t) lightbox(el._list || results, +t.dataset.i); };
  if (!el._ro) { let w = el.clientWidth; el._ro = new ResizeObserver(() => { if (el.clientWidth !== w) { w = el.clientWidth; el.innerHTML = el._render(); } }); el._ro.observe(el); }
}
function bindShelf(el, list, badge) {
  el.innerHTML = list.map((x, i) => tileHTML(x, i, { badge: badge?.(x) })).join("");
  el.onclick = e => { const t = e.target.closest(".tile"); if (t) lightbox(list, +t.dataset.i); };
}
// Hovering over a video flips through its frames, a preview without the video file (which may be only in iCloud).
const framesOf = {};
const videoFrames = uuid => framesOf[uuid] ??= api("/api/frames", { uuid }).then(r => r.results).catch(() => []);
document.addEventListener("mouseover", async e => {
  const t = e.target.closest?.(".tile[data-v]");
  if (!t || t._flip || !matchMedia("(hover: hover)").matches) return;
  const img = t.querySelector("img"), back = img.src, fs = await videoFrames(t.dataset.v);
  if (!fs.length || !t.matches(":hover")) return;
  let k = 0;
  t._flip = setInterval(() => { img.src = `/frame/${t.dataset.v}/${fs[k++ % fs.length]}.jpg`; }, 450);
  t.addEventListener("mouseleave", () => { clearInterval(t._flip); t._flip = 0; img.src = back; }, { once: true });
});
const skeleton = (n, w = 1.3) => Array.from({ length: n }, () => `<div class="tile skel" style="aspect-ratio:${w}"></div>`).join("");

/* ---------- lightbox ---------- */
const LB = { list: [], at: 0, trail: [], simsFor: null, timer: 0 };
function lightbox(list, i, keepTrail = false) {
  if (!keepTrail) LB.trail = [];
  LB.list = list; LB.at = i;
  const x = list[i];
  if (x.frame != null) $("lbimg").src = tileSrc(x);  // the moment that matched; the poster is a tap away in the strip
  else { $("lbimg").src = `/photo/${x.uuid}.jpg`; sharpen($("lbimg"), x.uuid); }
  $("lbbg").style.backgroundImage = `url(/thumb/${x.uuid}.jpg)`;
  $("lbdate").textContent = x.undated ? "Date unknown" : photoDate(x);
  $("lbplace").innerHTML = x.place ? `<a data-place="${esc(short(x.place))}" title="more from here">${esc(x.place)}</a>` : "";
  $("lbppl").innerHTML = (x.persons || []).map(p => `<a data-person="${esc(p)}" title="${esc(p)}'s page">${esc(p)}</a>`).join("");
  $("lbday").hidden = !!(x.undated || x.approx);
  filmstrip(x);
  $("lbprev").style.visibility = i > 0 ? "" : "hidden"; $("lbnext").style.visibility = i < list.length - 1 ? "" : "hidden";
  $("lbpos").textContent = list.length > 1 ? `${i + 1} of ${list.length}` : "";
  $("lbtrail").innerHTML = LB.trail.map((t, k) => `<img src="/thumb/${t.uuid}.jpg" data-k="${k}" title="back to here">`).join("");
  const wq = x.kind === "photo" ? whyQuery() : "";
  lovedShow(x);
  $("lbportrait").hidden = !SERVER.local || SERVER.demo || x.kind !== "photo" || !x.persons?.length;
  $("lbportrait").textContent = "👤 Portrait";
  $("lbwhy").hidden = !wq;
  if (WHY.on && wq) explainPhoto(x, wq); else whyClear();
  $("lb").classList.add("on"); lbTop();
  clearTimeout(LB.timer); LB.timer = setTimeout(() => loadSims(x), 220);  // not on every arrow press while flicking through
}
LB.mode = store.get("wander", "like");
async function loadSims(x) {
  const key = x.uuid + LB.mode;
  document.querySelectorAll("#lbmode button").forEach(b => b.classList.toggle("on", b.dataset.w === LB.mode));
  if (LB.simsFor === key) return;
  LB.simsFor = key; $("lbsims").innerHTML = "";
  if (LB.mode === "day" && x.undated) { $("lbsims").innerHTML = `<span class="status">no date on this one</span>`; return; }
  try {
    const q = LB.mode === "day" ? { after: x.date, before: nextDay(x.date), k: 60 } : { like: x.uuid, k: 16 };
    let r = (await api("/api/search", q)).results;
    if (LB.simsFor !== key) return;
    r = r.filter(s => s.uuid !== x.uuid);
    if (!r.length) { $("lbsims").innerHTML = `<span class="status">nothing else from that day</span>`; return; }
    LB.sims = r;
    $("lbsims").innerHTML = r.map((s, k) => `<img src="/thumb/${s.uuid}.jpg" data-k="${k}" style="width:${(76 * clampAr(s.ar)).toFixed(0)}px" alt="">`).join("");
  } catch {}
}
// A video's frames under it in the lightbox (phones can't hover): the moment that matched is marked, and tapping a frame shows it.
async function filmstrip(x) {
  const el = $("lbfilm"); el.innerHTML = ""; el.hidden = true;
  if (x.kind !== "video") return;
  const fs = await videoFrames(x.uuid);
  if (LB.list[LB.at] !== x || !fs.length) return;
  el.innerHTML = (x.at != null ? `<span>${vidLabel(x)}</span>` : "") +
    fs.map(t => `<img src="/frame/${x.uuid}/${t}.jpg" data-t="${t}" title="${mmss(t)}" class="${t === x.frame ? "on" : ""}" alt="">`).join("");
  el.hidden = false; lbTop();
}
// On a phone the info sits above the photo, and names, a filmstrip and the buttons can take several lines.
const lbTop = () => $("lb").style.setProperty("--lbtop", `${$("lbinfo").offsetHeight + 28}px`);
$("lbfilm").onclick = e => {
  const im = e.target.closest("img[data-t]"); if (!im) return;
  $("lbfilm").querySelectorAll("img").forEach(i => i.classList.toggle("on", i === im));
  $("lbimg").src = im.src;
};
function lbOff() { $("lb").classList.remove("on"); LB.simsFor = null; WHY.on = false; whyClear(); $("lbwho").hidden = true; }

/* ---------- family picks: ♡ a photo under your own name (each device remembers who's picking) ---------- */
const picker = () => store.get("who", "");
async function lovedShow(x) {
  const b = $("lbpick"); b.textContent = "♡ Love"; b.classList.remove("on"); b.title = "love this one: the family's picks show on Home and in the photo frame";
  $("lbwho").hidden = true;
  try { lovedSet(x, (await api("/api/loved", { uuid: x.uuid })).results); } catch {}
}
function lovedSet(x, by) {
  if (LB.list[LB.at] !== x) return;
  const b = $("lbpick"), me = by.includes(picker());
  b.classList.toggle("on", me);
  b.textContent = by.length ? `♥ ${by.length > 2 ? `${by.slice(0, 2).join(", ")} +${by.length - 2}` : by.join(", ")}` : "♡ Love";
  b.title = by.length ? `loved by ${by.join(", ")}${me ? " (tap to undo yours)" : ""}` : b.title;
}
async function lovedToggle() {
  const x = LB.list[LB.at];
  if (!picker()) return askWho(lovedToggle);
  try { lovedSet(x, await post("/api/pick", { uuid: x.uuid, who: picker(), on: !$("lbpick").classList.contains("on") })); loadPicks(); }
  catch (e) { $("lbpick").textContent = e.message; }
}
// Who's picking: the names already used, or a new one. Asked once per device (and on Home, "change").
async function askWho(then) {
  const f = $("lbwho"); f.hidden = false; lbTop();
  let ppl = []; try { ppl = (await api("/api/picks")).results.people.map(p => p.who); } catch {}
  f.innerHTML = `<span>Who's picking?</span>${ppl.map(w => `<button type="button" data-w="${esc(w)}">${esc(w)}</button>`).join("")}
    <input id="lbwhoi" placeholder="${ppl.length ? "or a new name" : "your name"}" maxlength="24" autocomplete="off"><button>OK</button>`;
  const done = w => { w = w.trim(); if (!w) return; store.set("who", w); f.hidden = true; lbTop(); then?.(); };
  f.onclick = e => { const w = e.target.dataset?.w; if (w) done(w); };
  f.onsubmit = e => { e.preventDefault(); done($("lbwhoi").value); };
  if (!ppl.length) $("lbwhoi").focus();
}
$("lbpick").onclick = lovedToggle;

/* ---------- use as portrait: this photo stands for someone tagged in it, everywhere (on the Mac) ---------- */
async function portraitSet(x, name) {
  try { await post("/api/portrait", { name, uuid: x.uuid }); } catch (e) { $("lbportrait").textContent = e.message; return; }
  loadPeople.reset(); PV.name = null; shelvesDone = false;  // people's covers show it next time they're drawn
  if (LB.list[LB.at] === x) $("lbportrait").textContent = `✓ ${firstName(name)}'s portrait`;
}
$("lbportrait").onclick = () => {
  const x = LB.list[LB.at], ppl = x.persons || [];
  if (ppl.length === 1) return portraitSet(x, ppl[0]);
  const f = $("lbwho"); f.hidden = false; lbTop();
  f.innerHTML = `<span>Whose portrait?</span>${ppl.map(p => `<button type="button" data-w="${esc(p)}">${esc(firstName(p))}</button>`).join("")}`;
  f.onclick = e => { const w = e.target.dataset?.w; if (w) { f.hidden = true; lbTop(); portraitSet(x, w); } };
  f.onsubmit = e => e.preventDefault();
};

/* ---------- why: which words of the search the photo fits, what the model sees in it, and where it matched ---------- */
const WHY = { on: false, key: null };
// The words behind the photos in the lightbox, when they came straight from a search (look-alikes have none)
const whyQuery = () => tab === "search" && R.q && !R.like && (LB.list === R.results || LB.list === $("grid")._list) ? R.q : "";
function whyClear() {
  WHY.key = null; $("whypanel").hidden = true; $("lbwhy").classList.remove("on");
  const s = $("lbimg").style; s.maskImage = s.webkitMaskImage = "";
}
async function explainPhoto(x, q) {
  const key = x.uuid + "|" + q; if (WHY.key === key) return;
  whyClear(); WHY.key = key; $("lbwhy").classList.add("on");
  const p = $("whypanel"), head = `<div class="wh">Why it matches “${esc(q)}”<button class="ibtn" id="whyx" title="close">✕</button></div>`;
  p.innerHTML = head + `<p class="wnote">looking…</p>`; p.hidden = false;
  let r;
  try { r = (await api("/api/why", { q, uuid: x.uuid })).results; }
  catch (e) { if (WHY.key === key) p.innerHTML = head + `<p class="wnote">${esc(e.message)}</p>`; return; }
  if (WHY.key !== key) return;
  const top = Math.max(1e-6, ...r.words.map(w => Math.abs(w.change)));
  p.innerHTML = head +
    (r.words.length ? `<div class="wsub">How much each word counts</div>` + r.words.map(w =>
      `<div class="wrow ${w.misfit ? "neg" : ""}"><span>${esc(w.word)}</span><i><b style="width:${(Math.abs(w.change) / top * 100).toFixed(0)}%"></b></i><em>${w.misfit ? "doesn’t fit" : ""}</em></div>`).join("") : "") +
    (r.sees.length ? `<div class="wsub">What the model sees</div><div class="wsees">${r.sees.map(s => `<span>${esc(s.toLowerCase())}</span>`).join("")}</div>` : "") +
    `<div class="wsub">Where</div><p class="wnote">${r.whole ? "The whole scene matches, not one part of it." : "Lit where it matches; the rest is dimmed."}</p>`;
  if (!r.whole) whyMask(r.heat);
}
// The heat map as a mask on the photo itself: one pixel per square of the model's grid, stretched smoothly over it
function whyMask(h) {
  const c = document.createElement("canvas"); c.width = h[0].length; c.height = h.length;
  const g = c.getContext("2d"), d = g.createImageData(c.width, c.height);
  h.flat().forEach((v, i) => { d.data[i * 4 + 3] = 255 * (0.3 + 0.7 * v ** 1.5); });
  g.putImageData(d, 0, 0);
  const s = $("lbimg").style;
  s.maskImage = s.webkitMaskImage = `url(${c.toDataURL()})`; s.maskSize = s.webkitMaskSize = "100% 100%";
}
$("lbwhy").onclick = () => { WHY.on = !WHY.on; WHY.on ? explainPhoto(LB.list[LB.at], whyQuery()) : whyClear(); };
$("whypanel").onclick = e => { if (e.target.id === "whyx") $("lbwhy").click(); };
$("lbclose").onclick = lbOff;
$("lbmode").onclick = e => {
  const w = e.target.dataset.w; if (!w || w === LB.mode) return;
  LB.mode = w; store.set("wander", w); loadSims(LB.list[LB.at]);
};
$("lbprev").onclick = () => LB.at > 0 && lightbox(LB.list, LB.at - 1, true);
$("lbnext").onclick = () => LB.at < LB.list.length - 1 && lightbox(LB.list, LB.at + 1, true);
$("lbstage").onclick = e => { if (e.target.id === "lbstage") lbOff(); };
$("lbsims").onclick = e => {  // wander: hop to a look-alike, leaving a trail back
  const k = e.target.dataset.k; if (k == null) return;
  LB.trail.push(LB.list[LB.at]); if (LB.trail.length > 12) LB.trail.shift();
  lightbox(LB.sims, +k, true);
};
$("lbtrail").onclick = e => {
  const k = e.target.dataset.k; if (k == null) return;
  const back = LB.trail[k]; LB.trail = LB.trail.slice(0, +k);
  lightbox([back], 0, true);
};
$("lbppl").onclick = e => { const p = e.target.dataset.person; if (p) go("person/" + encodeURIComponent(p)); };
$("lbplace").onclick = e => { const p = e.target.dataset.place; if (p) searchFor("", only({ place: p })); };
$("lbshow").onclick = () => openFrame({ list: LB.list, start: LB.at, title: tab === "search" ? $("rtitle").textContent : "" });
$("lbday").onclick = () => go("home/" + LB.list[LB.at].date.slice(5));
$("lbmath").onclick = () => { setMathBase(LB.list[LB.at]); go("math"); };
$("lbopen").hidden = !SERVER.local || SERVER.demo;  // it opens Photos on the Mac's screen
$("lbopen").onclick = () => fetch("/api/open?uuid=" + LB.list[LB.at].uuid);
addEventListener("keydown", e => {
  if (!$("lb").classList.contains("on")) return;
  if (e.key === "Escape") lbOff();
  if (e.key === "ArrowRight") $("lbnext").click();
  if (e.key === "ArrowLeft") $("lbprev").click();
});
{ // swipe: sideways to browse, down to close
  let p0 = null;
  $("lbstage").addEventListener("pointerdown", e => { p0 = [e.clientX, e.clientY]; });
  $("lbstage").addEventListener("pointerup", e => {
    if (!p0) return; const dx = e.clientX - p0[0], dy = e.clientY - p0[1]; p0 = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) (dx < 0 ? $("lbnext") : $("lbprev")).click();
    else if (dy > 90) lbOff();
  });
}
