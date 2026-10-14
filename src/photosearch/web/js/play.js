// Play: games solo or pass-and-play, and photo math.
// Plain scripts sharing one global scope, loaded in order by index.html; no build step.

/* ---------- games: solo, or pass-and-play with the family ---------- */
const GAMES = {
  year:  { name: "Guess the Year", glyph: "📅", text: "A random photo. When was it taken?", art: "linear-gradient(180deg, transparent 10%, rgba(120,45,12,.55) 45%, #42170a 82%)" },
  place: { name: "Guess the Place", glyph: "📍", text: "Drop a pin where you think it was taken.", art: "linear-gradient(180deg, transparent 10%, rgba(14,80,90,.55) 45%, #0b2a30 82%)" },
  first: { name: "Which Came First?", glyph: "⚖️", text: "Two photos. Tap the older one.", art: "linear-gradient(180deg, transparent 10%, rgba(70,40,130,.55) 45%, #1e1236 82%)" },
};
const P = { mode: null, round: 0, rounds: 10, players: [], turn: 0, cur: null, guess: null, map: null, layers: [] };
const COLORS = ["#f2b33d", "#5cc8ff", "#ff7aa8", "#7bd88f", "#c79bff", "#ff9f5a"];
views.play = () => { if (!P.mode) playMenu(); };
const loadCollage = once(async () => (await api("/api/rediscover", { n: 9 })).results);
function players() { return store.get("players", []); }
function playMenu() {
  P.mode = null;
  const best = store.get("best", {}), ps = players();
  $("playroot").innerHTML = `
    <div class="kick">Play</div>
    <h1>Game night, with your own photos</h1>
    <p class="status" style="margin:0 0 18px">${ps.length > 1 ? `${ps.length} players take turns · 5 rounds each` : "10 rounds · up to 100 points each"} · add players to pass the phone around</p>
    <div class="players">${ps.map((p, k) => `<span class="player" style="--c:${COLORS[k % COLORS.length]}">${esc(p)}<button data-k="${k}" aria-label="remove">✕</button></span>`).join("")}
      <form id="addp"><input id="pname" placeholder="${ps.length ? "+ another player" : "+ add players (optional)"}" maxlength="16"></form></div>
    <div class="cards">
      ${Object.entries(GAMES).map(([m, g]) => `<div class="card" data-mode="${m}" style="--art:${g.art}"><div class="collage"></div><span class="glyph">${g.glyph}</span><h3>${g.name}</h3>
        <p>${g.text}</p><p style="margin-top:10px"><b>Best: ${best[m] ?? "–"}</b> / 1000</p></div>`).join("")}
      <a class="card" href="#math" style="--art:linear-gradient(180deg, transparent 10%, rgba(110,25,70,.55) 45%, #2c0d1f 82%)"><div class="collage"></div><span class="glyph">∑</span><h3>Photo Math</h3>
        <p>This photo + snow − summer = ?</p></a>
    </div>`;
  $("playroot").querySelectorAll(".card[data-mode]").forEach(c => c.onclick = () => startGame(c.dataset.mode));
  $("playroot").querySelector(".players").onclick = e => {
    const k = e.target.dataset.k; if (k == null) return;
    const ps = players(); ps.splice(+k, 1); store.set("players", ps); playMenu();
  };
  $("addp").onsubmit = e => {
    e.preventDefault(); const n = $("pname").value.trim(); if (!n) return;
    if (players().some(p => p.toLowerCase() === n.toLowerCase())) { $("pname").value = ""; return; }  // already playing
    store.set("players", [...players(), n].slice(0, 6)); playMenu(); $("pname").focus();
  };
  loadCollage().then(r => document.querySelectorAll("#playroot .collage").forEach((c, k) =>
    c.innerHTML = r.slice((k * 2) % 8, (k * 2) % 8 + 3).map(x => `<img src="/thumb/${x.uuid}.jpg" alt="">`).join(""))).catch(() => {});
}
async function startGame(mode) {
  const ps = players();
  P.mode = mode; P.round = 0; P.turn = -1;
  P.players = (ps.length ? ps : ["You"]).map((name, k) => ({ name, score: 0, color: COLORS[k % COLORS.length] }));
  P.rounds = P.players.length > 1 ? 5 * P.players.length : 10;
  if (mode === "place") await loadLeaflet();
  nextRound();
}
async function gameRound(mode) {
  if (mode !== "first") return (await api("/api/game", { mode })).results;
  for (let tries = 0; ; tries++) {  // two photos at least a year apart, so there's a right answer to see
    const [a, b] = await Promise.all([api("/api/game", { mode: "year" }), api("/api/game", { mode: "year" })]);
    const [x, y] = [a.results, b.results];
    if (Math.abs(+x.date.slice(0, 4) - +y.date.slice(0, 4)) >= 1 || tries > 4) return { pair: [x, y] };
  }
}
async function nextRound() {
  if (P.round >= P.rounds) return endGame();
  P.round++; P.turn = (P.turn + 1) % P.players.length; P.guess = null; P.revealed = false;
  scrollTo(0, 0);
  const me = P.players[P.turn], solo = P.players.length === 1;
  try { P.cur = await gameRound(P.mode); }
  catch (e) { $("playroot").innerHTML = `<p>${esc(e.message)}</p>`; return; }
  const c = P.cur;
  const head = `<div class="ghead">
      <span>Round ${P.round} / ${P.rounds}</span>
      ${solo ? "" : `<span class="turn" style="--c:${me.color}">${esc(me.name)}'s turn</span>`}
      <span class="sp"></span>
      <span class="scores">${P.players.map(p => `<span style="--c:${p.color}">${solo ? "Score" : esc(p.name)} <b>${p.score}</b></span>`).join("")}</span>
      <a href="#play" id="quit">quit</a></div>`;
  if (P.mode === "first") {
    $("playroot").innerHTML = head + `
      <h2 class="ask">Which came first?</h2>
      <div class="pair">${c.pair.map((x, k) => `<figure data-k="${k}"><img src="/photo/${x.uuid}.jpg" alt=""><figcaption></figcaption></figure>`).join("")}</div>
      <div class="gfoot"><div class="reveal" id="reveal"></div><button id="go" hidden>Next →</button></div>`;
    c.pair.forEach((x, k) => sharpen($("playroot").querySelectorAll(".pair img")[k], x.uuid));
    $("playroot").querySelector(".pair").onclick = e => { const f = e.target.closest("figure"); if (f && !P.revealed) { P.guess = +f.dataset.k; reveal(); } };
  } else {
    $("playroot").innerHTML = head + `
      <div id="play-area">
        <img id="play-photo" src="/photo/${c.uuid}.jpg" alt="">
        <div id="guess">${P.mode === "year" ? `
          <div id="bigyear">${Math.round((c.first + c.last) / 2)}</div>
          <input type="range" id="yr" min="${c.first}" max="${c.last}" value="${Math.round((c.first + c.last) / 2)}">
          <div class="score"><span>${c.first}</span><span>${c.last}</span></div>` : `
          <div id="map"></div><div class="status">tap the map to drop your pin</div>`}
          <button id="go">Guess</button>
          <div class="reveal" id="reveal"></div>
        </div>
      </div>`;
    sharpen($("play-photo"), c.uuid);
    if (P.mode === "year") $("yr").oninput = () => { $("bigyear").textContent = $("yr").value; };
    else {
      P.map = L.map("map", { worldCopyJump: true }).setView([20, 0], 1);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(P.map);
      P.map.on("click", ev => {
        if (P.revealed) return;
        P.guess = ev.latlng; P.layers.forEach(l => l.remove());
        P.layers = [L.circleMarker(ev.latlng, { radius: 8, color: me.color, fillOpacity: .8 }).addTo(P.map)];
      });
    }
  }
  $("quit").onclick = e => { e.preventDefault(); playMenu(); };
  $("go").onclick = reveal;
}
function km(a, b) {
  const R = 6371, r = Math.PI / 180, dLat = (b[0] - a[0]) * r, dLon = (b[1] - a[1]) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
function reveal() {
  if (P.revealed) return nextRound();
  const c = P.cur, me = P.players[P.turn]; let pts, msg;
  if (P.mode === "first") {
    const [a, b] = c.pair, older = a.date <= b.date ? 0 : 1, right = P.guess === older;
    pts = right ? 100 : 0;
    const figs = $("playroot").querySelectorAll(".pair figure");
    figs.forEach((f, k) => { f.classList.add(k === older ? "right" : "wrong");
      f.querySelector("figcaption").innerHTML = `<b>${c.pair[k].date.slice(0, 4)}</b> ${longDate(c.pair[k].date, { month:"long", day:"numeric" })}${c.pair[k].place ? " · " + esc(short(c.pair[k].place)) : ""}`; });
    const gap = Math.abs(+a.date.slice(0, 4) - +b.date.slice(0, 4));
    msg = right ? `Right! ${gap ? `${gap} year${gap > 1 ? "s" : ""} apart.` : "Same year, but yes."}` : `Not this time: the other one is older${gap ? ` by ${gap} year${gap > 1 ? "s" : ""}` : ""}.`;
    $("go").hidden = false;
  } else if (P.mode === "year") {
    const g = +$("yr").value, real = +c.date.slice(0, 4), off = Math.abs(g - real);
    pts = Math.round(100 * Math.exp(-off / 2.5));
    msg = off === 0 ? `Exactly ${real}!` : `It was <b>${real}</b> (${longDate(c.date, { month:"long", day:"numeric", year:"numeric" })}): ${off} year${off > 1 ? "s" : ""} off.`;
  } else {
    if (!P.guess) return;
    const d = km([P.guess.lat, P.guess.lng], [c.lat, c.lon]);
    pts = Math.round(100 * Math.exp(-d / 600));
    P.layers.push(L.marker([c.lat, c.lon]).addTo(P.map), L.polyline([P.guess, [c.lat, c.lon]], { dashArray: "6", color: me.color }).addTo(P.map));
    P.map.fitBounds(L.latLngBounds([P.guess, [c.lat, c.lon]]).pad(0.4));
    msg = `${esc(c.place) || "Here"}: ${d < 1 ? "spot on" : Math.round(d).toLocaleString() + " km away"}.`;
  }
  me.score += pts; P.revealed = true;
  const ppl = P.mode === "first" ? [] : c.persons;
  $("reveal").innerHTML = `${msg} <b class="pts">+${pts}</b>${ppl.length ? `<div class="status">${esc(ppl.join(", "))}</div>` : ""}`;
  const nextUp = P.players[(P.turn + 1) % P.players.length];
  $("go").textContent = P.round >= P.rounds ? "See the scores" : P.players.length > 1 ? `${nextUp.name}'s turn →` : "Next photo →";
  $("playroot").querySelectorAll(".scores b")[P.turn].textContent = me.score;
}
function endGame() {
  const mode = P.mode, ranked = [...P.players].sort((a, b) => b.score - a.score), solo = P.players.length === 1;
  const best = store.get("best", {}), was = best[mode] ?? 0, top = solo ? P.players[0].score : 0;
  if (solo && top > was) { best[mode] = top; store.set("best", best); }
  const max = (P.rounds / P.players.length) * 100;
  $("playroot").innerHTML = `<div class="kick">${GAMES[mode].name}</div>
    ${solo ? `<h1>${top} / ${max}</h1><p>${top > was ? "🎉 New best!" : `Best so far: ${was}`}</p>`
           : `<h1>${esc(ranked[0].name)} wins!</h1>
              <ol class="podium">${ranked.map((p, k) => `<li style="--c:${p.color}"><span>${["🥇", "🥈", "🥉"][k] || k + 1}</span><b>${esc(p.name)}</b><i style="width:${(p.score / max * 100).toFixed(0)}%"></i><em>${p.score}</em></li>`).join("")}</ol>`}
    <p style="display:flex;gap:8px;margin-top:22px"><button id="again">Play again</button><button class="ghost" id="menu">Other game</button></p>`;
  $("again").onclick = () => startGame(mode);
  $("menu").onclick = playMenu;
}

function loadLeaflet() {
  if (window.L) return Promise.resolve();
  const css = document.createElement("link");
  css.rel = "stylesheet"; css.href = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css";
  document.head.append(css);
  return new Promise((ok, fail) => {
    const s = document.createElement("script");
    s.src = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"; s.onload = ok; s.onerror = fail;
    document.head.append(s);
  });
}

/* ---------- photo math ---------- */
const M = { base: null };
const M_PRESETS = [["night", "day"], ["snow", "summer"], ["a painting", "a photograph"], ["crowded", "empty"],
                   ["sunset", "midday"], ["rain", "sunshine"], ["", "people"], ["kids", "adults"]];
$("mchips").innerHTML = M_PRESETS.map(([p, m], i) => `<a class="pill" data-i="${i}">${p ? "+ " + p : ""} ${m ? "− " + m : ""}</a>`).join("");
$("mchips").onclick = e => { const i = e.target.dataset.i; if (i == null) return;
  [$("mplus").value, $("mminus").value] = M_PRESETS[i]; runMath(); };
$("mw").oninput = () => { $("mwv").textContent = (+$("mw").value).toFixed(1); };
function setMathBase(x) {
  M.base = x;
  $("mathbase").innerHTML = x ? `<img src="/thumb/${x.uuid}.jpg"><a href="#math" id="mclear" class="status">change</a>`
                              : `<input id="mtext" placeholder="start from… e.g. a street" style="width:220px">`;
  if (x) $("mclear").onclick = e => { e.preventDefault(); setMathBase(null); };
}
setMathBase(null);
views.math = () => {
  if (!M.base && !$("mgrid").innerHTML)
    $("mstatus").textContent = "Start from a photo (open one anywhere → “∑ Math”) or from words, then add and take away ideas.";
};
$("mf").onsubmit = e => { e.preventDefault(); runMath(); };
async function runMath() {
  const base = M.base ? M.base.uuid : $("mtext")?.value.trim();
  if (!base) { $("mstatus").textContent = "pick a starting photo or type a starting point"; return; }
  $("mstatus").textContent = "computing…";
  const r = await api("/api/math", { base, plus: $("mplus").value, minus: $("mminus").value, w: $("mw").value });
  $("mstatus").textContent = `${r.results.length} results · ${r.ms} ms`;
  bindGrid($("mgrid"), r.results);
}
