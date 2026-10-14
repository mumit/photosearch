// Time machine: one photo a year, for a search or a person.
// Plain scripts sharing one global scope, loaded in order by index.html; no build step.

/* ---------- time machine ---------- */
const T = { years: [], at: 0, timer: 0, key: null, q: "", person: "", speed: store.get("tspeed", "slow"), front: 0 };
const T_PRESETS = ["birthday cake", "christmas tree", "beach", "snow", "first day of school", "family dinner",
                   "halloween costume", "fireworks", "hiking in the mountains", "a selfie"];
$("tchips").innerHTML = T_PRESETS.map(p => `<a class="pill" href="#time/${encodeURIComponent(p)}">${p}</a>`).join("");
const timeHash = (q, person) => "time/" + encodeURIComponent(q || "") + (person ? "?person=" + encodeURIComponent(person) : "");
views.time = arg => {  // #time/birthday cake, #time/birthday cake?person=Name, or #time/?person=Name (their best each year)
  const [qs, ps] = (arg || "").split("?"), q = decodeURIComponent(qs || ""), person = new URLSearchParams(ps || "").get("person") || "";
  $("q").value = q || (person ? "" : T.q);
  const key = q + "|" + person;
  $("tempty").hidden = !!(q || person) || !!T.years.length;
  if ((q || person) && key !== T.key) runTime(q, person);
  loadPeople().then(p => { $("tpeople").innerHTML = p.slice(0, 10).map(x => `<a href="#${timeHash("", x.name)}" title="${esc(x.name)}"><img src="/thumb/${x.cover}.jpg" alt=""><span>${esc(firstName(x.name))}</span></a>`).join(""); }).catch(() => {});
};
$("twho").onclick = async () => {
  if (!$("twhop").hidden) { $("twhop").hidden = true; return; }
  const p = await loadPeople().catch(() => []);
  $("twhop").innerHTML = `<a href="#${timeHash(T.q, "")}">👥 Anyone</a>` + p.slice(0, 16).map(x =>
    `<a href="#${timeHash(T.q, x.name)}"><img src="/thumb/${x.cover}.jpg" alt="">${esc(x.name)}</a>`).join("");
  $("twhop").hidden = false;
};
$("twhop").onclick = e => { if (e.target.closest("a")) $("twhop").hidden = true; };
$("tspeed").onclick = e => {
  const v = e.target.dataset.v; if (!v) return;
  T.speed = v; store.set("tspeed", v); speedUI(); if (T.timer) { stopPlay(); $("tplay").click(); }
};
function speedUI() {
  document.querySelectorAll("#tspeed button").forEach(b => b.classList.toggle("on", b.dataset.v === T.speed));
  $("stage").style.setProperty("--fade", T.speed === "flip" ? ".18s" : ".7s");
}
speedUI();
leave.time = () => stopPlay();
async function runTime(q, person = "") {
  const key = q + "|" + person;
  T.key = key; T.q = q; T.person = person; stopPlay();
  $("tempty").hidden = true; $("tq").textContent = q ? `“${q}”` : `${person}`;
  $("twho").textContent = person ? `👤 ${firstName(person)}` : "👤 Anyone";
  $("tstatus").textContent = "travelling…";
  const r = await api("/api/timeline", person ? { q, person } : { q });
  if (T.key !== key) return;
  if (!r.results.length) { $("tstatus").textContent = "nothing found"; $("strip").innerHTML = ""; return; }
  const best = Math.max(...r.results.map(y => y.results[0].score));
  T.years = r.results.map(y => ({ ...y.results[0], year: y.year, weak: !!q && y.results[0].score < best - 0.08 }));
  $("tstatus").textContent = q ? `${T.years.length} years · faded ones are weak matches · ← →` : `${T.years.length} years of ${firstName(person)} · ← →`;
  $("strip").innerHTML = T.years.map((y, i) =>
    `<div data-i="${i}" class="${y.weak ? "weak" : ""}"><img src="/thumb/${y.uuid}.jpg" data-i="${i}">${y.year}</div>`).join("");
  showYear(T.years.findIndex(y => !y.weak));
}
function showYear(i) {
  if (i < 0 || i >= T.years.length) return;
  T.at = i; const y = T.years[i];
  // two layers: the next year loads behind, then dissolves over the last one
  const back = [$("timg"), $("timg2")][1 - T.front], front = [$("timg"), $("timg2")][T.front];
  back.onload = () => { if (T.years[T.at] !== y) return; back.classList.add("on"); front.classList.remove("on"); T.front = 1 - T.front;
                        $("tbg").style.backgroundImage = `url(/thumb/${y.uuid}.jpg)`; };
  back.src = `/photo/${y.uuid}.jpg`; sharpen(back, y.uuid);
  $("tyear").textContent = y.year;
  $("tmeta").innerHTML = `${longDate(y.date, { month:"long", day:"numeric" })}<br>${esc(short(y.place))}<br>${esc(y.persons.slice(0, 4).join(", "))}`;
  document.querySelectorAll("#strip > div").forEach((d, j) => d.classList.toggle("cur", j === i));
  document.querySelector("#strip .cur")?.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
  const nx = T.years[i + 1]; if (nx) new Image().src = `/photo/${nx.uuid}.jpg`;  // preload
}
$("stage").onclick = e => { if (e.target.classList.contains("tl")) lightbox(T.years, T.at); };
$("strip").onclick = e => { const i = e.target.closest("[data-i]")?.dataset.i; if (i != null) { stopPlay(); showYear(+i); } };
function stopPlay() { clearInterval(T.timer); T.timer = 0; $("tplay").textContent = "▶ Play"; }
$("tplay").onclick = () => {
  if (T.timer) return stopPlay();
  if (!T.years.length) return;
  $("tplay").textContent = "❚❚ Pause";
  const strong = () => T.years.map((y, i) => i).filter(i => !T.years[i].weak);
  T.timer = setInterval(() => { const s = strong(); showYear(s[(s.indexOf(T.at) + 1) % s.length]); }, T.speed === "flip" ? 550 : 1800);
};
addEventListener("keydown", e => {
  if (tab !== "time" || $("lb").classList.contains("on") || /INPUT|TEXTAREA/.test(e.target.tagName)) return;
  if (e.key === "ArrowRight") { stopPlay(); showYear(T.at + 1); }
  if (e.key === "ArrowLeft") { stopPlay(); showYear(T.at - 1); }
  if (e.key === " ") { e.preventDefault(); $("tplay").click(); }
});
