// The one search box (filters as chips, suggestions as you type) and the results.
// Plain scripts sharing one global scope, loaded in order by index.html; no build step.

/* ---------- the search box: filters as chips, suggestions as you type, and what ↵ does depends on the mode ---------- */
const FIELDS = ["person", "place", "after", "before", "season", "kind", "exclude"];
const F = Object.fromEntries(FIELDS.map(k => [k, ""]));
let AUTO = new Set();  // filters Jev read out of the description: dropped again on the next search
const SMART = { enabled: false };
api("/api/parse").then(r => { SMART.enabled = r.results.enabled; $("smartbox").hidden = !SMART.enabled; }).catch(() => {});
const CHIP = { person: v => "👤 " + v, place: v => "📍 " + v, after: v => "after " + v, before: v => "before " + v,
               season: v => ({ spring:"🌱", summer:"☀️", autumn:"🍂", winter:"❄️" }[v] || "") + " " + v, kind: v => v === "video" ? "🎞 videos" : "📷 photos only",
               exclude: v => "− " + v };
function renderChips() {
  const day = F.after && F.before && nextDay(F.after) === F.before;  // one day: one chip, not "after" and "before"
  $("fchips").innerHTML = $("rchips").innerHTML = (day ? `<span class="fchip">📅 ${esc(longDate(F.after, { month:"short", day:"numeric", year:"numeric" }))}<button type="button" data-k="after,before" aria-label="remove">✕</button></span>` : "") +
    FIELDS.filter(k => F[k] && !(day && (k === "after" || k === "before"))).map(k =>
    `<span class="fchip ${AUTO.has(k) ? "auto" : ""}" title="${AUTO.has(k) ? "✨ read from your words" : k}">${esc(CHIP[k](F[k]))}<button type="button" data-k="${k}" aria-label="remove">✕</button></span>`).join("");
  $("ftoggle").classList.toggle("set", FIELDS.some(k => F[k]));
}
$("fchips").onclick = $("rchips").onclick = e => {
  const k = e.target.dataset.k; if (!k) return;
  for (const f of k.split(",")) { F[f] = ""; AUTO.delete(f); }
  renderChips();
  if (tab === "search") searchFor($("q").value.trim(), {}, true);
};
function openPanel() {
  for (const k of FIELDS) $("f" + k).value = F[k];
  closeSugg(); $("fpanel").classList.add("on"); $("ftoggle").setAttribute("aria-expanded", true);
  loadOverview().catch(() => {});
}
function closePanel() { $("fpanel").classList.remove("on"); $("ftoggle").setAttribute("aria-expanded", false); }
$("ftoggle").onclick = () => $("fpanel").classList.contains("on") ? closePanel() : openPanel();
$("fapply").onclick = () => {
  for (const k of FIELDS) { const v = $("f" + k).value.trim(); if (v !== F[k]) AUTO.delete(k); F[k] = v; }
  closePanel(); renderChips(); submit();
};
$("fclear").onclick = () => { for (const k of FIELDS) $("f" + k).value = ""; };
$("fpanel").addEventListener("keydown", e => { if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); $("fapply").click(); } });
document.addEventListener("pointerdown", e => { if (!$("omni").contains(e.target)) { closeSugg(); closePanel(); } });

// search: the hash carries the words and the filters, so results survive back/forward and a reload
function searchHash(q, f = F, auto = AUTO) {
  const p = new URLSearchParams(Object.entries(f).filter(([k, v]) => v && FIELDS.includes(k)));
  const a = [...auto].filter(k => f[k]); if (a.length) p.set("auto", a.join(","));
  return "search/" + encodeURIComponent(q) + (p.size ? "?" + p : "");
}
const only = f => Object.fromEntries(FIELDS.map(k => [k, f[k] || ""]));
function searchFor(q, extra = {}, keep = false) {
  if (!keep) { for (const k of AUTO) F[k] = ""; AUTO = new Set(); }
  Object.assign(F, extra); renderChips();
  go(searchHash(q));
}
async function submit(how) {
  const q = $("q").value.trim(); closeSugg(); closePanel();
  how ||= { galaxy: "galaxy", time: "time" }[tab] || "search";
  if (how === "galaxy") return go("galaxy/" + encodeURIComponent(q));
  if (how === "time") return q && go("time/" + encodeURIComponent(q));
  for (const k of AUTO) F[k] = ""; AUTO = new Set();
  if (!q && !FIELDS.some(k => F[k])) return go("home");
  if (q && SMART.enabled && $("smart").checked) {
    $("status").textContent = "understanding…"; $("f").classList.add("busy");
    try {
      const r = (await api("/api/parse", { q })).results;
      for (const [k, v] of Object.entries(r.filters || {})) if (v && FIELDS.includes(k) && !F[k]) { F[k] = v; AUTO.add(k); }
    } catch {}  // search still works without it
    $("f").classList.remove("busy");
  }
  renderChips(); go(searchHash(q));
}
$("f").onsubmit = e => {
  e.preventDefault();
  const cur = $("sugg").querySelector("a.cur");
  if ($("sugg").classList.contains("on") && cur) return cur.click();
  submit();
};

// suggestions: people, places, trips and years from the library, plus the other modes for the same words
const loadOverview = once(async () => {
  const [o, s] = await Promise.all([api("/api/overview"), loadStories()]);
  Object.assign(OV, o.results, { stories: s });
  $("people").innerHTML = OV.people.map(([p]) => `<option value="${esc(p)}">`).join("");
  $("places").innerHTML = OV.places.map(([p]) => `<option value="${esc(p)}">`).join("");
});
const OV = { people: [], places: [], years: [], stories: [] };
const fold = s => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const wordStart = (name, t) => fold(name).split(/[\s,·&-]+/).some(w => w.startsWith(t)) || fold(name).startsWith(t);
function suggest() {
  const raw = $("q").value.trim(), t = fold(raw);
  if (!raw) return closeSugg();
  const rows = [], add = (sec, html, act) => rows.push({ sec, html, act });
  const enc = encodeURIComponent(raw);
  const mode = { galaxy: "galaxy", time: "time" }[tab] || "search";
  const MODES = { search: ["🔍", `Search for <b>“${esc(raw)}”</b>`, "Search"], time: ["⏳", `<b>“${esc(raw)}”</b> through the years`, "Time Machine"],
                  galaxy: ["✦", `Light up <b>“${esc(raw)}”</b> in the galaxy`, "Galaxy"] };
  [mode, ...Object.keys(MODES).filter(m => m !== mode)].forEach((m, k) => {
    const [g, h, name] = MODES[m]; add("", `<span class="g">${g}</span><span>${h}</span><small>${k ? name : "↵"}</small>`, () => submit(m));
  });
  if (t.length >= 2) {
    OV.people.filter(([p]) => wordStart(p, t)).slice(0, 4).forEach(([p, n]) =>
      add("People", `<span class="g">👤</span><span>${esc(p)}</span><small>${n.toLocaleString()} photos</small>`, () => { $("q").value = ""; go("person/" + encodeURIComponent(p)); }));
    OV.places.filter(([p]) => wordStart(p, t)).slice(0, 3).forEach(([p, n]) =>
      add("Places", `<span class="g">📍</span><span>${esc(p)}</span><small>${n.toLocaleString()} photos</small>`, () => { $("q").value = ""; searchFor("", only({ place: p })); }));
    OV.stories.filter(s => wordStart(s.title || "", t) || (/^\d{4}$/.test(raw) && s.id === raw) || (s.kind === "trip" && s.start.startsWith(raw)))
      .slice(0, 4).forEach(s => add("Stories", `${s.cover ? `<img src="/thumb/${s.cover}.jpg" alt="">` : `<span class="g">▶</span>`}<span>${esc(s.title)}${s.kind === "trip" ? " trip" : " · year in review"}</span><small>${s.kind === "trip" ? dateRange(s.start, s.end) : s.photos.toLocaleString() + " photos"} ▶</small>`,
        () => open(`/review/${s.id}`, "_blank")));
  }
  if (/^\d{4}$/.test(raw) && OV.years.some(([y]) => y === raw))
    add("Years", `<span class="g">📅</span><span>Best of ${raw}</span>`, () => { $("q").value = ""; searchFor("", only({ after: `${raw}-01-01`, before: `${+raw + 1}-01-01` })); });
  let last = null;
  $("sugg").innerHTML = rows.map((r, k) => { const h = r.sec && r.sec !== last ? `<div class="sh">${r.sec}</div>` : ""; last = r.sec; return h + `<a data-k="${k}" class="${k ? "" : "cur"}">${r.html}</a>`; }).join("");
  $("sugg")._rows = rows; $("sugg").classList.add("on");
}
function closeSugg() { $("sugg").classList.remove("on"); }
$("q").addEventListener("input", () => { closePanel(); loadOverview().then(suggest, suggest); suggest(); });
$("q").addEventListener("focus", () => loadOverview().catch(() => {}));
$("q").addEventListener("keydown", e => {
  const s = $("sugg"); if (!s.classList.contains("on")) return;
  const items = [...s.querySelectorAll("a")], k = items.findIndex(a => a.classList.contains("cur"));
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault(); items[k]?.classList.remove("cur");
    items[(k + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].classList.add("cur");
  }
  if (e.key === "Escape") closeSugg();
});
$("sugg").onclick = e => { const a = e.target.closest("a[data-k]"); if (a) { closeSugg(); $("sugg")._rows[a.dataset.k].act(); } };

/* ---------- search results ---------- */
const R = { key: null, results: [], sort: store.get("sort", "best"), k: 48 };
views.search = async arg => {
  const [qs, ps] = arg.split("?"), q = decodeURIComponent(qs || ""), p = new URLSearchParams(ps || "");
  for (const k of FIELDS) F[k] = p.get(k) || "";
  AUTO = new Set((p.get("auto") || "").split(",").filter(k => F[k]));
  $("q").value = q;
  renderChips();
  const like = p.get("like"), key = arg;
  if (key === R.key) return showResults();
  R.key = key; R.q = q; R.like = like; R.k = 48;
  const params = R.params = { ...(like ? { like } : { q }), ...Object.fromEntries(FIELDS.filter(k => F[k]).map(k => [k, F[k]])) };
  $("rtitle").innerHTML = title(); $("status").textContent = "searching…"; $("racts").innerHTML = ""; $("grid").innerHTML = ""; $("more").innerHTML = "";
  try {
    const r = await api("/api/search", params);
    if (R.key !== key) return;
    R.results = r.results; R.meta = r;
  } catch (e) { $("status").textContent = e.message; return; }
  showResults(); scrollTo(0, 0);
};
async function moreResults() {
  const key = R.key; R.k += 48;
  $("more").innerHTML = `<span class="status">finding more…</span>`;
  try { const r = await api("/api/search", { ...R.params, k: R.k }); if (R.key !== key) return; R.results = r.results; R.meta = r; }
  catch (e) { $("more").innerHTML = `<span class="status">${esc(e.message)}</span>`; return; }
  showResults();
}
function title() {
  if (R.like) return `<img src="/thumb/${R.like}.jpg" alt="">Look-alikes`;
  if (R.q) return `“${esc(R.q)}”`;
  if (F.person) return esc(F.person.split(",").join(" & "));
  if (F.place) return esc(F.place);
  if (F.after && F.before && nextDay(F.after) === F.before) return longDate(F.after);
  if (F.after && F.before && F.after.endsWith("-01-01") && F.before.endsWith("-01-01") && +F.before.slice(0, 4) === +F.after.slice(0, 4) + 1) return "Best of " + F.after.slice(0, 4);
  return "Your best photos";
}
function showResults() {
  const r = R.meta; if (!r) return;
  const auto = [...AUTO].map(k => CHIP[k](F[k])).join(" · ");
  $("rtitle").innerHTML = title();
  const oneDay = !R.q && !R.like && F.after && nextDay(F.after) === F.before;
  $("status").textContent = `${r.results.length} ${R.q || R.like ? "best matches" : oneDay ? `photo${r.results.length > 1 ? "s" : ""} from this day` : "favourites, by how interesting they look"} · from ${r.total.toLocaleString()} photos · ${r.ms} ms`
    + (auto ? ` · ✨ ${auto}` : "");
  const albumHash = "#album/new?" + new URLSearchParams({ ...(R.q ? { q: R.q } : {}), ...Object.fromEntries(FIELDS.filter(k => F[k]).map(k => [k, F[k]])) });
  $("racts").innerHTML = `${R.like ? "" : `<a class="pill" href="${albumHash}" title="save as an album that keeps itself up to date">＋ Album</a>`}<button class="pill" id="rshow">▶ Slideshow</button>${F.person && !F.person.includes(",") ? `<a class="pill" href="#person/${encodeURIComponent(F.person)}">👤 ${esc(firstName(F.person))}'s page</a>` : ""}${R.q ? `<a class="pill" href="#time/${encodeURIComponent(R.q)}">⏳ Through the years</a><a class="pill" href="#galaxy/${encodeURIComponent(R.q)}">✦ In the galaxy</a>` : ""}
    <div class="seg"><button data-s="best" class="${R.sort === "best" ? "on" : ""}">Best match</button><button data-s="date" class="${R.sort === "date" ? "on" : ""}">By date</button></div>`;
  $("rshow").onclick = () => openFrame({ list: $("grid")._list || r.results, title: $("rtitle").textContent });
  $("more").innerHTML = r.results.length >= R.k && R.k < 480 ? `<button class="ghost" id="morebtn">Show ${Math.min(48, 480 - R.k)} more</button>` : "";
  if ($("morebtn")) $("morebtn").onclick = moreResults;
  $("racts").querySelector(".seg").onclick = e => { const s = e.target.dataset.s; if (s) { R.sort = s; store.set("sort", s); showResults(); } };
  const el = $("grid");
  if (!r.results.length) { el.innerHTML = `<p class="status">${/["“”]/.test(R.q || "") ? "No photo has the words in quotes written in it, as far as this Mac could read." : "Nothing found. Try fewer filters, or other words."}</p>`; return; }
  if (R.sort === "best") { el._list = r.results; return bindGrid(el, r.results); }
  // by date: newest first, in years
  const sorted = [...r.results].sort((a, b) => (a.undated - b.undated) || b.date.localeCompare(a.date));
  el._list = sorted;
  const groups = [];
  sorted.forEach((x, i) => { const y = x.undated ? "Undated" : x.date.slice(0, 4); if (groups.at(-1)?.y !== y) groups.push({ y, at: i, items: [] }); groups.at(-1).items.push(x); });
  bindGrid(el, sorted, () => groups.map(g =>
    `<div class="ygroup"><h2>${g.y}<small>${g.items.length} photo${g.items.length > 1 ? "s" : ""}</small></h2>${justify(el, g.items, g.at)}</div>`).join(""));
}
