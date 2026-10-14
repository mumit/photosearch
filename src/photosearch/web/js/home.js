// Home: on this day as a slow slideshow, then shelves.
// Plain scripts sharing one global scope, loaded in order by index.html; no build step.

/* ---------- home: on this day as a slow slideshow, then shelves ---------- */
const HOME = { day: null, slides: [], at: 0, timer: 0, data: null };
const md = d => `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const shiftDay = (day, n) => { const [m, d] = day.split("-").map(Number); return md(new Date(2000, m - 1, d + n)); };  // 2000: has Feb 29
const dayName = day => { const [m, d] = day.split("-").map(Number); return new Date(2000, m - 1, d).toLocaleDateString(undefined, { month:"long", day:"numeric" }); };
const HERO_MS = 7000;
views.home = arg => {
  const day = /^\d{2}-\d{2}$/.test(arg) ? arg : md(new Date());
  if (day !== HOME.day) loadHero(day); else heroShow(HOME.at);
  loadShelves();
};
leave.home = () => clearTimeout(HOME.timer);
async function loadHero(day) {
  HOME.day = day; clearTimeout(HOME.timer);
  const isToday = day === md(new Date());
  $("hday").innerHTML = isToday ? "" : `<a href="#home">back to today</a>`;
  $("hprev").onclick = e => { e.stopPropagation(); go("home/" + shiftDay(day, -1)); };
  $("hnext").onclick = e => { e.stopPropagation(); go("home/" + shiftDay(day, 1)); };
  let r;
  try { r = (await api("/api/today", { day })).results; } catch (e) { $("hago").textContent = e.message; return; }
  if (HOME.day !== day) return;
  // each year's best photo first (the most striking year leading), then the next best of each, and so on
  const byYear = r.years.map(y => y.photos.map(p => ({ ...p, ago: y.ago, year: y.year, trip: y.trip })));
  const per = byYear.map(ps => [...ps].sort((a, b) => b.interest - a.interest)).sort((a, b) => b[0].interest - a[0].interest);
  let slides = [];
  for (let k = 0; per.some(p => p[k]); k++) per.forEach(p => p[k] && slides.push(p[k]));
  HOME.empty = !slides.length;
  if (HOME.empty) slides = (await api("/api/rediscover", { n: 8 })).results;
  HOME.slides = slides.slice(0, 16);
  $("hkick").textContent = HOME.empty ? `Nothing from ${dayName(day)} in other years · from the archive` : `${isToday ? "On this day" : dayName(day)}${r.window ? " · the week around it" : ""}`;
  $("hslides").innerHTML = HOME.slides.map((x, k) => `<div class="hs" data-k="${k}" style="--kx:${(k % 3 - 1) * 2}%;--ky:${(k % 2 ? -1 : 1) * 1.5}%">
    <div class="hb"></div><img alt="" class="${x.ar < 1.15 && innerWidth > 760 ? "contain" : ""}"></div>`).join("");
  $("hdots").innerHTML = HOME.slides.length > 1 ? HOME.slides.map((_, k) => `<i data-k="${k}"></i>`).join("") : "";
  $("hdots").style.setProperty("--hd", HERO_MS + "ms");
  heroShow(0);
  // the rest of the day's photos, by year
  const all = byYear.flat();
  $("hmore").hidden = all.length <= 1;
  $("hmoreh").textContent = isToday ? "More from this day" : `More from ${dayName(day)}`;
  $("hmorep").textContent = r.years.length ? `${r.years.length} year${r.years.length > 1 ? "s" : ""}, newest first` : "";
  bindShelf($("todayshelf"), all, x => x.year);
}
function heroShow(k) {
  const n = HOME.slides.length; if (!n) return;
  HOME.at = k = (k + n) % n;
  const x = HOME.slides[k], el = $("hslides").children[k];
  const img = el.querySelector("img");
  if (!img.src) { img.src = `/photo/${x.uuid}.jpg`; el.querySelector(".hb").style.backgroundImage = `url(/thumb/${x.uuid}.jpg)`; sharpen(img, x.uuid); }
  [...$("hslides").children].forEach((s, j) => s.classList.toggle("on", j === k));
  [...$("hdots").children].forEach((d, j) => d.classList.toggle("on", j === k));
  $("hcount").textContent = n > 1 ? `${k + 1} / ${n}` : "";
  const nx = HOME.slides[(k + 1) % n]; if (nx) new Image().src = `/photo/${nx.uuid}.jpg`;
  if (HOME.empty) {
    $("hago").textContent = x.undated ? "From the archive" : x.date.slice(0, 4);
    $("hsub").innerHTML = `${x.undated ? "" : longDate(x.date)}${x.place ? " · " + esc(short(x.place)) : ""}`;
  } else {
    $("hago").textContent = ago(x.ago);
    $("hsub").innerHTML = `${longDate(x.date)}${x.place ? " · " + esc(short(x.place)) : ""}`
      + (x.trip ? ` · on the <a href="/review/${x.trip.id}" target="_blank">${esc(x.trip.name)} trip ▶</a>` : "")
      + (x.persons?.length ? `<br>${esc(x.persons.slice(0, 4).join(", "))}` : "");
  }
  clearTimeout(HOME.timer);
  if (n > 1 && tab === "home") HOME.timer = setTimeout(() => heroShow(HOME.at + 1), HERO_MS);
}
$("hdots").onclick = e => { e.stopPropagation(); const k = e.target.dataset.k; if (k != null) heroShow(+k); };
$("hero").onclick = e => { if (!e.target.closest("a, button, #hdots")) lightbox(HOME.slides, HOME.at); };

const loadStories = once(async () => (await api("/api/stories")).results);
const ASKS = ["birthday cake with candles", "sunset at the beach", "kids playing in the snow", "dinner with family", "mountains and a lake",
              "a dog", "halloween costumes", "fireworks", "first day of school", "a picnic in the park", "a selfie with friends", "an old photo"];
let shelvesDone = false;
async function loadShelves() {
  if (shelvesDone) return; shelvesDone = true;
  $("asks").innerHTML = ASKS.map(a => `<a class="pill" href="#${searchHash(a, {}, new Set())}">${esc(a)}</a>`).join("");
  $("rediscover").innerHTML = skeleton(8); $("tripshelf").innerHTML = skeleton(6, .75); $("yearshelf").innerHTML = skeleton(8, 1);
  shuffle();
  loadPeople().then(p => {  // no one tagged (a new library, a demo): no shelf at all
    $("peopleshelf").innerHTML = p.map(x => avatar(x)).join(""); $("peopleshelf").closest(".hsec").hidden = !p.length;
  }).catch(() => {});
  showCal().catch(() => {});
  try {
    const s = await loadStories();
    $("tripshelf").innerHTML = s.filter(x => x.kind === "trip").map(x => poster(x)).join("") || `<p class="status">No trips found yet: they need photos with locations.</p>`;
    $("yearshelf").innerHTML = s.filter(x => x.kind === "year").map(x => poster(x)).join("");
    const n = s.filter(x => x.kind === "year").reduce((a, x) => a + x.photos, 0);
    $("hfoot").textContent = `${n.toLocaleString()} dated photos across ${s.filter(x => x.kind === "year").length} years and ${s.filter(x => x.kind === "trip").length} trips · press / to search from anywhere, ? for all shortcuts`;
  } catch (e) { $("tripshelf").innerHTML = `<p class="status">${esc(e.message)}</p>`; }
}
async function shuffle() {
  try { const r = (await api("/api/rediscover", { n: 24 })).results; bindShelf($("rediscover"), r, x => x.date.slice(0, 4)); }
  catch (e) { $("rediscover").innerHTML = `<p class="status">${esc(e.message)}</p>`; }
}
$("shuffle").onclick = shuffle;
