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
      <div class="card" id="detcard" style="--art:linear-gradient(180deg, transparent 10%, rgba(40,70,40,.55) 45%, #142414 82%)"><div class="collage"></div><span class="glyph">🕵️</span><h3>Date Detective</h3>
        <p>Photos without a real date. Your answer becomes the date.</p></div>
      <div class="card" id="tncard" style="--art:linear-gradient(180deg, transparent 10%, rgba(30,60,110,.55) 45%, #0d1a30 82%)"><div class="collage"></div><span class="glyph">⏳</span><h3>Then and Now</h3>
        <p>The same spot or the same person, years apart.</p></div>
      <div class="card" id="rccard" style="--art:linear-gradient(180deg, transparent 10%, rgba(120,90,20,.55) 45%, #2e230a 82%)"><div class="collage"></div><span class="glyph">📸</span><h3>Recreate This</h3>
        <p>Pick an old photo, take it again today, see them side by side.</p></div>
      <a class="card" href="#math" style="--art:linear-gradient(180deg, transparent 10%, rgba(110,25,70,.55) 45%, #2c0d1f 82%)"><div class="collage"></div><span class="glyph">∑</span><h3>Photo Math</h3>
        <p>This photo + snow − summer = ?</p></a>
    </div>`;
  $("playroot").querySelectorAll(".card[data-mode]").forEach(c => c.onclick = () => startGame(c.dataset.mode));
  $("detcard").onclick = () => detective();
  $("tncard").onclick = () => thenNow();
  $("rccard").onclick = () => recreate();
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

/* ---------- date detective: photos whose date in Photos is a placeholder ---------- */
const DT = { skip: [], g: null, out: new Set() };
const MONTH_NAMES = Array.from({ length: 12 }, (_, k) => new Date(2000, k, 1).toLocaleDateString(undefined, { month: "long" }));
async function detective(done) {
  P.mode = "detective"; scrollTo(0, 0);
  let r;
  try { r = (await api("/api/undated", { skip: DT.skip.join("|") })).results; }
  catch (e) { $("playroot").innerHTML = `<p>${esc(e.message)}</p>`; return; }
  const g = DT.g = r.group; DT.out = new Set();
  const head = `<div class="ghead"><span>Date Detective</span><span class="sp"></span>
    <span>${r.left ? `${r.left.toLocaleString()} photos left, in ${r.groups} groups` : ""}</span><a href="#play" id="quit">done</a></div>`;
  if (!g) {
    $("playroot").innerHTML = head + `<h2 class="ask">Every photo has a date.</h2>${done || ""}`;
    $("quit").onclick = e => { e.preventDefault(); playMenu(); }; return;
  }
  const shown = g.photos.slice(0, 24), more = g.photos.length - shown.length;
  const y0 = g.guess?.year || new Date().getFullYear(), m0 = g.guess?.month || 0;
  $("playroot").innerHTML = head + `
    ${done ? `<div class="reveal dtdone">${done}</div>` : ""}
    <h2 class="ask">When were these taken?</h2>
    <p class="status">${g.album ? `The album “${esc(g.album)}”` : "Photos that look alike, with no album to go on"} · ${g.photos.length} photo${g.photos.length > 1 ? "s" : ""} · tap one to leave it out</p>
    <div class="dtgrid">${shown.map((x, k) => `<figure data-k="${k}"><img src="/thumb/${x.uuid}.jpg" alt="" loading="lazy"></figure>`).join("")}</div>
    ${more ? `<p class="status">and ${more} more from the same album</p>` : ""}
    <div id="play-area" class="dtarea">
      <div><h3>Clues</h3><ul class="clues">${g.clues.map(c => `<li>${esc(c)}</li>`).join("") || "<li>None.</li>"}</ul>
        ${g.alike.length ? `<h3>It looks like these</h3><div class="dtalike">${g.alike.map(x => `<figure><img src="/thumb/${x.uuid}.jpg" alt=""><figcaption>${photoDate(x, { month:"short", year:"numeric" })}</figcaption></figure>`).join("")}</div>` : ""}</div>
      <div id="guess">
        <div id="bigyear">${y0}</div>
        <div class="dtyear"><button class="ghost" data-d="-1" aria-label="a year earlier">‹</button>
          <input type="range" id="yr" min="1950" max="${new Date().getFullYear()}" value="${y0}"><button class="ghost" data-d="1" aria-label="a year later">›</button></div>
        <select id="mo"><option value="0">Month: don't know</option>${MONTH_NAMES.map((n, k) => `<option value="${k + 1}"${k + 1 === m0 ? " selected" : ""}>${n}</option>`).join("")}</select>
        ${g.guess ? `<p class="status">My guess, from ${esc(g.guess.how)}.</p>` : ""}
        <button id="go"></button>
        <button class="ghost" id="skip">Skip: I don't know</button>
      </div>
    </div>`;
  const count = () => { const n = g.photos.length - DT.out.size; $("go").textContent = `Date ${n === 1 ? "this photo" : `these ${n} photos`}`; $("go").disabled = !n; };
  count();
  $("playroot").querySelector(".dtgrid").onclick = e => {
    const f = e.target.closest("figure"); if (!f) return;
    const u = shown[+f.dataset.k].uuid; DT.out.has(u) ? DT.out.delete(u) : DT.out.add(u);
    f.classList.toggle("out", DT.out.has(u)); count();
  };
  $("yr").oninput = () => { $("bigyear").textContent = $("yr").value; };
  $("playroot").querySelectorAll(".dtyear button").forEach(b => b.onclick = () => { $("yr").value = +$("yr").value + +b.dataset.d; $("yr").oninput(); });
  $("quit").onclick = e => { e.preventDefault(); playMenu(); };
  $("skip").onclick = () => { DT.skip.push(g.id); detective(); };
  $("go").onclick = async () => {
    const uuids = g.photos.map(x => x.uuid).filter(u => !DT.out.has(u)), year = +$("yr").value, month = +$("mo").value || null;
    $("go").disabled = true;
    try { await post("/api/undated", { uuids, year, month }); }
    catch (e) { $("go").textContent = e.message; return; }
    const when = month ? `${MONTH_NAMES[month - 1]} ${year}` : year;
    detective(`Dated ${uuids.length} photo${uuids.length > 1 ? "s" : ""} to ${when}. <a href="#play" id="dtundo" data-u="${uuids.join(",")}">Undo</a>`);
  };
  const un = $("dtundo");
  if (un) un.onclick = async e => { e.preventDefault(); await post("/api/undated_undo", { uuids: un.dataset.u.split(",") }); detective("Undone: back to no date."); };
}

/* ---------- then and now: the same spot or the same person, years apart (thennow.py) ---------- */
const TN = { by: store.get("tnby", "place"), lists: {}, at: 0 };
async function thenNow(at = 0) {
  P.mode = "thennow"; scrollTo(0, 0);
  const by = TN.by;
  if (!TN.lists[by]) {
    $("playroot").innerHTML = `<p class="status">Looking for photos ${by === "person" ? "of the same person" : "from the same spot"}, years apart…</p>`;
    try { TN.lists[by] = (await api("/api/thennow", { by })).results; }
    catch (e) { $("playroot").innerHTML = `<p>${esc(e.message)}</p>`; return; }
  }
  const L = TN.lists[by], n = L.length;
  TN.at = at = n ? (at + n) % n : 0;
  const head = `<div class="ghead tnhead"><span class="tntitle">Then and Now</span>
    <span class="seg" id="tnby"><button data-by="place"${by === "place" ? ' class="on"' : ""}>📍 Same spot</button><button data-by="person"${by === "person" ? ' class="on"' : ""}>👤 Same person</button></span>
    <span class="sp"></span><span>${n ? `${at + 1} of ${n}` : ""}</span><a href="#play" id="quit">done</a></div>`;
  if (!n) {
    $("playroot").innerHTML = head + `<h2 class="ask">No pairs yet.</h2><p class="status">${by === "person"
      ? "It needs photos where Photos names the same person, at least 4 years apart."
      : "It needs photos with GPS from the same spot, at least 4 years apart."}</p>`;
  } else {
    const x = L[at], side = (p, label) => `<figure data-u="${p.uuid}"><img src="/photo/${p.uuid}.jpg" alt="">
      <figcaption><b>${label}</b> ${photoDate(p, { month: "long", year: "numeric" })}</figcaption></figure>`;
    const where = x.who ? esc(firstName(x.who)) : x.now.place ? esc(short(x.now.place)) : "";
    $("playroot").innerHTML = head + `
      <h2 class="ask">${where ? `${where} · ` : ""}${x.years} years apart</h2>
      <div class="tnpair">${side(x.then, "Then")}${side(x.now, "Now")}</div>
      <div class="tnnav"><button class="ghost" id="tnprev">‹ Previous</button><button id="tnnext">Next ›</button></div>`;
    $("tnprev").onclick = () => thenNow(at - 1);
    $("tnnext").onclick = () => thenNow(at + 1);
    $("playroot").querySelector(".tnpair").onclick = e => {
      const f = e.target.closest("figure"); if (f) lightbox([x.then, x.now], f.dataset.u === x.then.uuid ? 0 : 1);
    };
  }
  $("tnby").onclick = e => {
    const b = e.target.closest("button"); if (!b || b.dataset.by === TN.by) return;
    TN.by = b.dataset.by; store.set("tnby", TN.by); thenNow();
  };
  $("quit").onclick = e => { e.preventDefault(); playMenu(); };
}
addEventListener("keydown", e => {
  if (P.mode !== "thennow" || $("lb").classList.contains("on") || location.hash !== "#play" || e.target.closest("input, textarea")) return;
  if (e.key === "ArrowRight") thenNow(TN.at + 1);
  if (e.key === "ArrowLeft") thenNow(TN.at - 1);
});

/* ---------- recreate this: pick an old photo, shoot it again, see the two together (recreate.py) ---------- */
const RC = { tab: "ideas", ideas: [], more: true, state: null };
async function recreate(tab = RC.tab, note = "") {
  if (P.mode !== "recreate" || tab !== RC.tab) scrollTo(0, 0);
  P.mode = "recreate"; RC.tab = tab;
  try {
    RC.state = (await api("/api/recreate")).results;
    if (tab === "ideas" && !RC.ideas.length) { RC.ideas = (await api("/api/recreate", { view: "ideas" })).results; RC.more = RC.ideas.length === 24; }
  } catch (e) { $("playroot").innerHTML = `<p>${esc(e.message)}</p>`; return; }
  const st = RC.state, found = st.todo.filter(x => x.shot).length;
  const tabs = [["ideas", "💡 Ideas"], ["todo", `📋 To do${st.todo.length ? ` (${st.todo.length})` : ""}${found ? " ✨" : ""}`], ["done", `✅ Done${st.done.length ? ` (${st.done.length})` : ""}`]];
  const head = `<div class="ghead tnhead"><span class="tntitle">Recreate This</span>
    <span class="seg" id="rctabs">${tabs.map(([k, n]) => `<button data-t="${k}"${k === tab ? ' class="on"' : ""}>${n}</button>`).join("")}</span>
    <span class="sp"></span><a href="#play" id="quit">done</a></div>${note ? `<div class="reveal dtdone">${note}</div>` : ""}`;
  const who = x => x.who ? esc(firstName(x.who)) : "";
  const when = x => photoDate(x, { month: "short", year: "numeric" });
  let body;
  if (tab === "ideas") {
    body = `<h2 class="ask">Which would be fun to take again?</h2>
      <p class="status">Old photos that look posed. Tap ＋ to add one to your list, then take it again with your phone. When the new photo is in Photos and <code>photosearch index</code> has run, it shows up under To do.</p>
      <div class="rcgrid">${RC.ideas.map(x => `<figure data-u="${x.uuid}"><img src="/thumb/${x.uuid}.jpg" alt="" loading="lazy">
        <figcaption><span>${who(x)} · ${when(x)}</span><button class="rcadd" data-u="${x.uuid}" aria-label="add to my list">＋</button></figcaption></figure>`).join("")}</div>
      ${RC.more ? `<p style="text-align:center"><button class="ghost" id="rcmore">More ideas</button></p>` : ""}`;
  } else if (tab === "todo") {
    body = !st.todo.length ? `<h2 class="ask">Nothing on your list yet.</h2><p class="status">Pick some under Ideas.</p>`
      : `<div class="rctodo">${st.todo.map(x => `<div class="rcrow">
          <figure data-u="${x.then.uuid}"><img src="/thumb/${x.then.uuid}.jpg" alt=""><figcaption>${who(x)} · ${when(x.then)}</figcaption></figure>
          ${x.shot ? `<figure data-u="${x.shot.uuid}" class="rcshot"><img src="/thumb/${x.shot.uuid}.jpg" alt=""><figcaption>${when(x.shot)}</figcaption></figure>
            <div class="rcask"><b>Is this the new one?</b><button data-a="yes" data-u="${x.then.uuid}" data-m="${x.shot.uuid}">Yes</button><button class="ghost" data-a="no" data-u="${x.then.uuid}" data-m="${x.shot.uuid}">No</button></div>`
            : `<div class="rcask"><span class="status">Not taken yet</span><button class="ghost" data-a="unpick" data-u="${x.then.uuid}">Remove</button></div>`}
        </div>`).join("")}</div>`;
  } else {
    body = !st.done.length ? `<h2 class="ask">None done yet.</h2>`
      : st.done.map(x => `<h2 class="ask">${who(x) ? `${who(x)} · ` : ""}${x.years} years apart</h2>
          <div class="tnpair">${[["Then", x.then], ["Now", x.now]].map(([l, p]) => `<figure data-u="${p.uuid}"><img src="/photo/${p.uuid}.jpg" alt="" loading="lazy">
            <figcaption><b>${l}</b> ${photoDate(p, { month: "long", year: "numeric" })}</figcaption></figure>`).join("")}</div>
          <p style="text-align:right"><button class="ghost" data-a="undo" data-u="${x.then.uuid}">Not a match</button></p>`).join("");
  }
  $("playroot").innerHTML = head + `<div id="rcbody">${body}</div>`;
  $("quit").onclick = e => { e.preventDefault(); playMenu(); };
  $("rctabs").onclick = e => { const b = e.target.closest("button"); if (b) recreate(b.dataset.t); };
  const all = [...RC.ideas, ...st.todo.flatMap(x => [x.then, x.shot].filter(Boolean)), ...st.done.flatMap(x => [x.then, x.now])];
  $("rcbody").onclick = async e => {
    const b = e.target.closest("button[data-u]");
    if (b) {
      e.stopPropagation(); b.disabled = true;
      const action = b.classList.contains("rcadd") ? "pick" : b.dataset.a;
      try { await post("/api/recreate", { uuid: b.dataset.u, action, match: b.dataset.m }); }
      catch (err) { b.textContent = err.message; return; }
      if (action === "pick") { RC.ideas = RC.ideas.filter(x => x.uuid !== b.dataset.u); return recreate("ideas", "Added to your list."); }
      return recreate(tab, action === "yes" ? "Done! It's under Done." : "");
    }
    const f = e.target.closest("figure[data-u]");
    if (f) { const i = all.findIndex(x => x.uuid === f.dataset.u); if (i >= 0) lightbox(all, i); }
  };
  const more = $("rcmore");
  if (more) more.onclick = async () => {
    more.disabled = true;
    const r = (await api("/api/recreate", { view: "ideas", offset: RC.ideas.length })).results;
    RC.ideas.push(...r); RC.more = r.length === 24; recreate("ideas");
  };
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
