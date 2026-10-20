// Photo frame: a slow, endless slideshow for a spare screen, and what to show in it.
// Plain scripts sharing one global scope, loaded in order by index.html; no build step.

/* ---------- photo frame: a slow, endless slideshow for a spare screen (or of any set of photos) ---------- */
const FR = { list: [], at: -1, timer: 0, ambient: false, paused: false, lock: null, hide: 0 };
const FRAME_MS = 9000;
async function openFrame({ list = null, title = "", start = 0, ambient = false } = {}) {
  lbOff(); $("frame").classList.toggle("amb", ambient || !list); $("fpick").hidden = true; FR.picking = false;
  FR.ambient = !list; FR.list = list ? [...list] : []; FR.at = start - 1; FR.paused = false; FR.title = title;
  $("frame").classList.add("on"); $("fslides").innerHTML = "";
  $("ftitle").textContent = title || "Photo frame";
  try { FR.lock = await navigator.wakeLock?.request("screen"); } catch {}  // keep the screen on
  document.documentElement.requestFullscreen?.().catch(() => {});
  tick(); frameNext(); frameUI();
}
function closeFrame() {
  if (!$("frame").classList.contains("on")) return;
  $("frame").classList.remove("on"); clearTimeout(FR.timer); clearInterval(FR.clock);
  FR.lock?.release?.().catch(() => {}); FR.lock = null;
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  if (tab === "frame") location.hash = lastHash;
}
async function frameNext(step = 1) {
  if (FR.ambient && FR.at + step >= FR.list.length - 2) {  // the frame never runs out: fetch more
    try { FR.list.push(...(await api("/api/rediscover", { n: 30 })).results); } catch {}
  }
  const n = FR.list.length; if (!n) return;
  FR.at = FR.ambient ? Math.max(0, FR.at + step) : (FR.at + step + n) % n;
  const x = FR.list[FR.at];
  const el = document.createElement("div");
  const k = FR.at % 4;
  el.className = "fs"; el.style.cssText = `--kx:${[2, -2, 1.5, -1.5][k]}%;--ky:${[1.5, -1, -1.5, 1][k]}%`;
  el.innerHTML = `<div class="hb" style="background-image:url(/thumb/${x.uuid}.jpg)"></div><img alt="" class="${(x.ar || 1) < 1.15 && innerWidth > innerHeight ? "contain" : ""}">`;
  const img = el.querySelector("img");
  img.onload = () => {
    $("fslides").append(el);
    requestAnimationFrame(() => { el.classList.add("on"); });
    setTimeout(() => [...$("fslides").children].slice(0, -1).forEach(o => o.remove()), 1800);
    $("fdate").textContent = x.undated ? "" : longDate(x.date, { month:"long", day:"numeric", year:"numeric" });
    $("fwhere").textContent = [short(x.place), (x.persons || []).slice(0, 3).join(", ")].filter(Boolean).join(" · ");
    $("fby").textContent = x.by?.length ? `♥ ${x.by.join(", ")}` : "";
    $("fpos").textContent = FR.ambient ? "" : `${FR.at + 1} / ${n}`;
    sharpen(img, x.uuid);
  };
  img.src = `/photo/${x.uuid}.jpg`;
  const nx = FR.list[FR.at + 1]; if (nx) new Image().src = `/photo/${nx.uuid}.jpg`;
  clearTimeout(FR.timer);
  if (!FR.paused) FR.timer = setTimeout(() => frameNext(), FRAME_MS);
}
function tick() {
  const t = () => { const d = new Date(); $("fclock").textContent = d.toLocaleTimeString(undefined, { hour:"numeric", minute:"2-digit" });
                    $("fday").textContent = d.toLocaleDateString(undefined, { weekday:"long", month:"long", day:"numeric" }); };
  t(); clearInterval(FR.clock); FR.clock = setInterval(t, 10000);
}
function frameUI() {  // the controls show on a touch or mouse move, then fade away
  $("frame").classList.add("ui"); clearTimeout(FR.hide);
  FR.hide = setTimeout(() => { if (!FR.picking) $("frame").classList.remove("ui"); }, 2800);
}
function framePause(p = !FR.paused) {
  FR.paused = p; $("fpp").textContent = p ? "▶" : "❚❚";
  clearTimeout(FR.timer); if (!p) FR.timer = setTimeout(() => frameNext(), FRAME_MS);
}
$("frame").addEventListener("pointermove", frameUI);
$("frame").addEventListener("pointerdown", frameUI);
$("fclose").onclick = closeFrame;
$("fsrc").onclick = e => { e.stopPropagation(); framePick(); };
$("fpp").onclick = () => framePause();
$("fprev").onclick = () => frameNext(-1);
$("fnext").onclick = () => frameNext(1);
$("finfo").onclick = () => { const x = FR.list[FR.at]; if (x) { framePause(true); lightbox(FR.list, FR.at); } };
addEventListener("keydown", e => {
  if (!$("frame").classList.contains("on") || $("lb").classList.contains("on")) return;
  if (e.key === "Escape") return FR.picking ? framePickOff() : closeFrame();
  if (FR.picking) return;
  if (e.key === " ") { e.preventDefault(); framePause(); }
  if (e.key === "ArrowRight") frameNext(1);
  if (e.key === "ArrowLeft") frameNext(-1);
  frameUI();
});
function frameOff() { if ($("frame").classList.contains("on")) { $("frame").classList.remove("on"); clearTimeout(FR.timer); clearInterval(FR.clock); FR.lock?.release?.().catch(() => {}); } }

/* ---------- photo frame: what to show ---------- */
let lastHash = "#home";
const shuffled = a => { a = [...a]; for (let k = a.length - 1; k > 0; k--) { const j = Math.floor(Math.random() * (k + 1)); [a[k], a[j]] = [a[j], a[k]]; } return a; };
views.frame = async arg => {
  const p = new URLSearchParams((arg || "").replace(/^\?/, ""));
  let list = null, title = "";
  try {
    if (p.get("person")) { title = p.get("person"); list = shuffled((await api("/api/search", { person: title, k: 240 })).results); }
    else if (p.get("q")) { title = `“${p.get("q")}”`; list = shuffled((await api("/api/search", { q: p.get("q"), k: 160 })).results); }
    else if (p.get("picks")) {  // the family's picks, everyone's or one person's
      title = p.get("who") ? `${p.get("who")}'s picks` : "Family picks";
      list = shuffled((await api("/api/picks", p.get("who") ? { who: p.get("who") } : {})).results.photos);
    }
    else if (p.get("day")) { title = "On this day"; list = (await api("/api/today", {})).results.years.flatMap(y => y.photos); }
  } catch {}
  openFrame({ list: list?.length ? list : null, title, ambient: true });
};
async function framePick() {
  FR.picking = true; frameUI(); framePause(true);
  const ppl = await loadPeople().catch(() => []);
  const fam = await api("/api/picks").then(r => r.results.people).catch(() => []);
  $("fpick").innerHTML = `<div class="kick">Show in the frame</div>
    <div class="fopts"><a href="#frame">✨ The best of everything</a><a href="#frame/?day=today">📅 On this day</a>${fam.length ? `<a href="#frame/?picks=1">♥ Family picks</a>` : ""}${fam.length > 1 ? fam.map(f => `<a href="#frame/?picks=1&who=${encodeURIComponent(f.who)}">♥ ${esc(f.who)}'s</a>`).join("") : ""}</div>
    <div class="favs">${ppl.slice(0, 10).map(p => `<a href="#frame/?person=${encodeURIComponent(p.name)}"><img src="${faceSrc(p.cover, p.name)}" alt=""><span>${esc(firstName(p.name))}</span></a>`).join("")}</div>
    <form id="fq"><input id="fqi" placeholder="or anything… e.g. sunsets at the beach"><button>Show</button></form>
    <button class="ibtn" id="fpickx" title="close">✕</button>`;
  $("fpick").hidden = false;
  $("fq").onsubmit = e => { e.preventDefault(); const q = $("fqi").value.trim(); if (q) location.hash = "frame/?q=" + encodeURIComponent(q); };
  $("fpickx").onclick = framePickOff;
  $("fpick").onclick = e => { if (e.target.closest("a")) framePickOff(); };
}
function framePickOff() { FR.picking = false; $("fpick").hidden = true; framePause(false); frameUI(); }
