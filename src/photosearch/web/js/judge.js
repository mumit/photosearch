// Judge a test: an experiment's blind sheets (photosearch eval), one search at a time, from any device.
// Plain scripts sharing one global scope, loaded in order by index.html; no build step.

/* ---------- judge a test: which photos fit the search, in two rows from two versions of search ---------- */
const JG = { sheet: null, x: new Set(), y: new Set(), first: "same" };
views.judge = arg => {  // #judge, #judge/NAME (my next sheet), #judge/NAME/7, #judge/NAME/results
  const [name, n] = arg.split("/").map(decodeURIComponent);
  if (!picker()) return judgeWho(() => views.judge(arg));
  if (!name) return judgeList();
  if (n === "results") return judgeResults(name);
  judgeSheet(name, n ? +n : null);
};
const judgeHead = (sub = "") => `<div class="edtop"><a href="#${sub ? "judge" : "play"}">← ${sub ? "All tests" : "Play"}</a><span class="sp"></span>
  <span class="status">judging as ${esc(picker())} · <a href="" id="jme">change</a></span></div><div class="kick">Judge a test${sub ? " · " + esc(sub) : ""}</div>`;
function judgeBind() {
  const me = $("jme"); if (me) me.onclick = e => { e.preventDefault(); store.set("who", ""); route(); };
}
function judgeWho(then) {
  $("jroot").innerHTML = `<div class="kick">Judge a test</div><h1>Who's judging?</h1>
    <p class="lede">Each judge's answers are kept under their name, so two people's can be compared.</p>
    <form class="jwho" id="jwho"><input id="jwhoi" placeholder="your name" maxlength="24" autocomplete="off"><button>OK</button></form>`;
  $("jwhoi").focus();
  $("jwho").onsubmit = e => { e.preventDefault(); const w = $("jwhoi").value.trim(); if (w) { store.set("who", w); then(); } };
}
async function judgeList() {
  $("jroot").innerHTML = judgeHead() + `<h1>Which photos fit the search?</h1>
    <p class="lede">Each test compares two versions of search. For every search you see two rows of photos, X and Y, in random
      order, and nothing says which version is which. Tap the photos that fit. The results are shown when you've judged them all.</p>
    <div class="jlist" id="jlist"><p class="status">looking…</p></div>`;
  judgeBind();
  let r; try { r = (await api("/api/evals")).results; } catch (e) { $("jlist").innerHTML = `<p class="status">${esc(e.message)}</p>`; return; }
  const me = picker();
  $("jlist").innerHTML = r.map(t => {
    const mine = t.judges[me] || 0, others = Object.entries(t.judges).filter(([j]) => j !== me && t.judges[j]);
    return `<a class="jrun" href="#judge/${encodeURIComponent(t.name)}${mine >= t.searches ? "/results" : ""}"><div><b>${esc(t.name)}</b>
      <small>${t.searches} searches${others.length ? " · judged by " + others.map(([j, n]) => `${esc(j)}${n < t.searches ? ` (${n})` : ""}`).join(", ") : ""}</small></div>
      <span class="sp"></span><span class="pill">${mine >= t.searches ? "Results" : mine ? `Continue · ${t.searches - mine} left` : "Start"}</span></a>`;
  }).join("") || `<p class="status">No tests yet. Start one in the terminal with <code>photosearch eval run</code>.</p>`;
}
async function judgeSheet(name, n) {
  let s;
  try { s = (await api("/api/eval_sheet", { name, who: picker(), ...(n ? { n } : {}) })).results; }
  catch (e) { $("jroot").innerHTML = judgeHead(name) + `<p class="status">${esc(e.message)}</p>`; judgeBind(); return; }
  if (s.done) return go(`judge/${encodeURIComponent(name)}/results`);
  JG.sheet = s; JG.x = new Set(s.verdict?.x || []); JG.y = new Set(s.verdict?.y || []); JG.first = s.verdict?.first || "same";
  const row = (r, ps) => `<div class="jrow" style="--k:${s.k}" data-r="${r}"><b>${r.toUpperCase()}</b>${ps.map((p, i) =>
    `<figure data-i="${i + 1}" class="${JG[r].has(i + 1) ? "fit" : ""}">${p.gone ? "" : `<img src="/thumb/${p.uuid}.jpg" alt="">`}
      <span class="n">${i + 1}</span>${p.gone ? "" : `<button class="zoom" data-a="zoom" title="see it big">⤢</button>`}</figure>`).join("")}</div>`;
  $("jroot").innerHTML = judgeHead(name) + `<p class="status">Search ${s.n} of ${s.total} · ${s.left} left to judge</p>
    <div class="jq">“${esc(s.q)}”</div>
    <p class="status">Tap every photo that fits the search.</p>
    ${row("x", s.x)}${row("y", s.y)}
    <div class="jfirst"><span>Whose first photo fits better?</span>
      <div class="seg" id="jfirst">${[["x", "X"], ["same", "About the same"], ["y", "Y"]].map(([v, t]) =>
        `<button data-v="${v}" class="${JG.first === v ? "on" : ""}">${t}</button>`).join("")}</div></div>
    <div class="jnav">${s.n > 1 ? `<button class="ghost" id="jprev">← Previous</button>` : ""}<span class="sp"></span>
      <span class="status" id="jsave"></span><button id="jnext">${s.left <= 1 && !s.verdict ? "Save and see the results" : "Save · next →"}</button></div>`;
  judgeBind();
  document.querySelectorAll("#jroot .jrow").forEach(el => el.onclick = e => {
    const fig = e.target.closest("figure"); if (!fig) return;
    const r = el.dataset.r, i = +fig.dataset.i, photos = s[r];
    if (e.target.closest("[data-a=zoom]")) return lightbox(photos.filter(p => !p.gone), photos.slice(0, i - 1).filter(p => !p.gone).length);
    JG[r].has(i) ? JG[r].delete(i) : JG[r].add(i);
    fig.classList.toggle("fit", JG[r].has(i));
  });
  $("jfirst").onclick = e => { const v = e.target.dataset.v; if (!v) return; JG.first = v;
    $("jfirst").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.v === v)); };
  if ($("jprev")) $("jprev").onclick = () => go(`judge/${encodeURIComponent(name)}/${s.n - 1}`);
  $("jnext").onclick = async () => {
    $("jnext").disabled = true; $("jsave").textContent = "saving…";
    try {
      const r = await post("/api/eval_score", { name, n: s.n, who: picker(), x: [...JG.x], y: [...JG.y], first: JG.first });
      const to = !r.left ? "/results" : s.verdict && s.n < s.total ? "/" + (s.n + 1) : "";  // rejudging: the next one; else the next new one
      go(`judge/${encodeURIComponent(name)}${to}`);
    } catch (e) { $("jsave").textContent = e.message; $("jnext").disabled = false; }
  };
}
async function judgeResults(name) {
  $("jroot").innerHTML = judgeHead(name) + `<p class="status">adding up…</p>`; judgeBind();
  let r;
  try { r = (await api("/api/eval_results", { name, who: picker() })).results; }
  catch (e) { $("jroot").innerHTML = judgeHead(name) + `<p class="status">${esc(e.message)}</p>`; judgeBind(); return; }
  const me = picker(), t = r.judges[me];
  const pair = ([a, b]) => a > b ? `<b>${esc(r.a)}</b>` : b > a ? `<b>${esc(r.b)}</b>` : "neither";
  $("jroot").innerHTML = judgeHead(name) + `<h1>What you found</h1>
    <p class="lede">Row X and row Y unblinded: <b>${esc(r.a)}</b> against <b>${esc(r.b)}</b>, over ${r.searches} searches.</p>
    <table class="jres"><tr><th></th><th>${esc(r.a)}</th><th>${esc(r.b)}</th></tr>
    ${Object.entries(r.judges).map(([j, x]) => `<tr><td>Photos that fit, for ${esc(j)}${x.sheets < r.searches ? ` (${x.sheets} of ${r.searches} searches)` : ""}</td>
      <td>${x.fit.A}</td><td>${x.fit.B}</td></tr><tr><td>Better first photo, for ${esc(j)}${x.better.same ? ` (${x.better.same} about the same)` : ""}</td>
      <td>${x.better.A}</td><td>${x.better.B}</td></tr>`).join("")}</table>
    <p>For you, more photos fit with ${pair([t.fit.A, t.fit.B])}, of ${t.sheets * r.k * 2} shown.</p>
    ${Object.entries(r.agree).filter(([, g]) => g.sheets).map(([j, g]) =>
      `<p>You and ${esc(j)} both judged ${g.sheets} searches and called ${g.same} of ${g.photos} photos the same way (${Math.round(100 * g.same / g.photos)}%).</p>`).join("")}
    <p class="jnav"><a class="pill" href="#judge/${encodeURIComponent(name)}/1">Look at your answers again</a><a class="pill" href="#judge">All tests</a></p>`;
  judgeBind();
}
