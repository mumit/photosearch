// People pages, and the calendar of days.
// Plain scripts sharing one global scope, loaded in order by index.html; no build step.

/* ---------- people: a page per person, with their best photo from every year ---------- */
const loadPeople = once(async () => (await api("/api/people")).results);
const firstName = n => n.split(" ")[0];
const initials = n => n.split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();
const fmtN = n => n > 999 ? (n / 1000).toFixed(n > 9999 ? 0 : 1) + "k" : String(n);
function avatar(p, note) {
  return `<a class="avatar" href="#person/${encodeURIComponent(p.name)}" title="${esc(p.name)}">
    ${p.cover ? `<img loading="lazy" src="${faceSrc(p.cover, p.name)}" alt="">` : `<span class="ini">${esc(initials(p.name))}</span>`}
    <b>${esc(p.name)}</b><small>${note ?? p.n.toLocaleString() + " photos"}</small></a>`;
}
const PV = { name: null };
views.person = async arg => {
  const name = decodeURIComponent(arg || "");
  if (!name) return go("home");
  if (PV.name === name) return;
  PV.name = name; scrollTo(0, 0);
  $("pv").innerHTML = `<div class="phead"><div class="pportrait skel"></div><div><div class="kick">&nbsp;</div><h1>${esc(name)}</h1></div></div>`;
  let r, best, ppl;
  try {
    [r, best, ppl] = await Promise.all([api("/api/person", { name }), api("/api/search", { person: name, k: 48 }), loadPeople().catch(() => [])]);
  } catch (e) { $("pv").innerHTML += `<p class="status pad">${esc(e.message)}</p>`; return; }
  if (PV.name !== name) return;
  r = r.results;
  const cover = new Map(ppl.map(p => [p.name, p.cover])), years = r.years, latest = years.at(-1);
  const span = r.first.slice(0, 4) === r.last.slice(0, 4) ? r.first.slice(0, 4) : `${r.first.slice(0, 4)}–${r.last.slice(0, 4)}`;
  const only1 = f => "#" + searchHash("", only(f), new Set());
  $("pv").innerHTML = `
    <div class="phead">
      ${r.portrait ? `<img class="pportrait" src="${faceSrc(r.portrait, name)}" alt="">` : latest ? `<img class="pportrait" src="/thumb/${latest.uuid}.jpg" alt="">` : ""}
      <div><div class="kick">${r.n.toLocaleString()} photos · ${span}</div><h1>${esc(name)}</h1>
        <div class="pbtns">${years.length >= 3 ? `<button id="pgrow">▶ ${esc(firstName(name))} through the years</button>` : ""}
          <a class="pill" href="#frame/?person=${encodeURIComponent(name)}">🖼 Photo frame</a>
          <a class="pill" href="${only1({ person: name })}">All photos →</a></div></div>
    </div>
    ${years.length > 1 ? `<div class="hsec"><div class="shead"><h2>Through the years</h2><p>the best photo of ${esc(firstName(name))} from each year</p></div><div class="shelf tall" id="pyears"></div></div>` : ""}
    ${r.together.length ? `<div class="hsec"><div class="shead"><h2>Often with</h2></div><div class="avatars">${r.together.map(([p, n]) => avatar({ name: p, cover: cover.get(p) }, `together in ${n.toLocaleString()}`)).join("")}</div></div>` : ""}
    ${r.places.length ? `<div class="hsec"><div class="shead"><h2>Places</h2></div><div class="asks">${r.places.map(([p, n]) => `<a class="pill" href="${only1({ person: name, place: p })}">📍 ${esc(p)} <small class="status">${n.toLocaleString()}</small></a>`).join("")}</div></div>` : ""}
    <div class="hsec"><div class="shead"><h2>Favourites</h2><p>the most striking photos of ${esc(firstName(name))}</p></div><div id="pbest"></div></div>`;
  if ($("pyears")) bindShelf($("pyears"), years, x => x.year);
  if ($("pgrow")) $("pgrow").onclick = () => openFrame({ list: years, title: `${firstName(name)} through the years` });
  bindGrid($("pbest"), best.results);
};

/* ---------- calendar: a year of days, coloured by how many photos each has ---------- */
const CAL = { year: null, years: [] };
const nextDay = d => { const [y, m, dd] = d.split("-").map(Number); return new Date(Date.UTC(y, m - 1, dd + 1)).toISOString().slice(0, 10); };
async function showCal(year) {
  if (!CAL.years.length) CAL.years = (await loadStories()).filter(x => x.kind === "year").map(x => +x.id).sort((a, b) => a - b);
  year = Math.min(Math.max(year ?? CAL.years.at(-1), CAL.years[0]), CAL.years.at(-1));
  CAL.year = year; $("caly").textContent = year;
  $("calprev").disabled = year <= CAL.years[0]; $("calnext").disabled = year >= CAL.years.at(-1);
  const r = (await api("/api/days", { year })).results;
  if (CAL.year !== year) return;
  const by = new Map(r.days.map(x => [x.d, x])), max = Math.max(1, ...r.days.map(x => x.n));
  const jan1 = new Date(Date.UTC(year, 0, 1)), lead = jan1.getUTCDay(), cells = [], months = [];
  for (let k = 0; k < lead; k++) cells.push(`<i class="pad"></i>`);
  for (let t = jan1; t.getUTCFullYear() === year; t = new Date(t.getTime() + 864e5)) {
    const d = t.toISOString().slice(0, 10), x = by.get(d);
    if (t.getUTCDate() === 1) months.push(`<span style="grid-column:${Math.floor(cells.length / 7) + 1}">${t.toLocaleDateString(undefined, { month: "short", timeZone: "UTC" })}</span>`);
    cells.push(x ? `<i data-d="${d}" style="--v:${(0.22 + 0.78 * Math.log(1 + x.n) / Math.log(1 + max)).toFixed(2)}"></i>` : `<i class="none" data-d="${d}"></i>`);
  }
  const busiest = [...r.days].sort((a, b) => b.n - a.n)[0], total = r.days.reduce((a, x) => a + x.n, 0);
  $("calp").textContent = r.days.length ? `${total.toLocaleString()} photos on ${r.days.length} days · busiest: ${longDate(busiest.d, { month: "short", day: "numeric" })} (${busiest.n})` : "no photos this year";
  $("cal").innerHTML = `<div class="calm">${months.join("")}</div><div class="calg">${cells.join("")}</div>`;
  CAL.by = by;
  if (year === new Date().getFullYear()) $("cal").scrollLeft = $("cal").scrollWidth;  // today's end of the year
}
$("calprev").onclick = () => showCal(CAL.year - 1);
$("calnext").onclick = () => showCal(CAL.year + 1);
$("cal").addEventListener("pointerover", e => {
  const d = e.target.dataset?.d, x = d && CAL.by.get(d), tip = $("caltip");
  if (!x) { tip.hidden = true; return; }
  tip.innerHTML = `<img src="/thumb/${x.cover}.jpg" alt=""><div><b>${longDate(d, { weekday: "short", month: "short", day: "numeric" })}</b><br>${x.n} photo${x.n > 1 ? "s" : ""}</div>`;
  const r = e.target.getBoundingClientRect(), hr = $("calbox").getBoundingClientRect();
  tip.hidden = false;
  tip.style.left = Math.min(r.left - hr.left, hr.width - 200) + "px"; tip.style.top = (r.bottom - hr.top + 8) + "px";
});
$("cal").addEventListener("pointerleave", () => { $("caltip").hidden = true; });
$("cal").onclick = e => {
  const d = e.target.dataset?.d; if (!d || !CAL.by.get(d)) return;
  go(searchHash("", only({ after: d, before: nextDay(d) }), new Set()));
};
