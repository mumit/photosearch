// Smart albums, and tidying up near-duplicates.
// Plain scripts sharing one global scope, loaded in order by index.html; no build step.

/* ---------- smart albums: a search that keeps itself up to date, taught by taking photos out ---------- */
const AL = { a: null, ranked: [], pinnedExtra: [], n: 0, scored: true, timer: 0, isNew: false, del: false };
const albumSummary = a => [a.q ? `“${esc(a.q)}”` : "", ...Object.entries(a.filters || {}).filter(([, v]) => v).map(([k, v]) => esc(CHIP[k] ? CHIP[k](v) : v))].filter(Boolean).join(" · ");
views.albums = async () => {
  $("albumgrid").innerHTML = skeleton(4, .75);
  try {
    const r = (await api("/api/albums")).results;
    $("albumgrid").innerHTML = r.map(x => `<a class="poster" href="#album/${x.id}">
        ${x.cover ? `<img loading="lazy" src="/thumb/${x.cover}.jpg" alt="">` : ""}
        ${x.new ? `<span class="by">+${x.new} new since copied to Photos</span>` : ""}
        <div class="pt"><h3>${esc(x.name)}</h3><small>${x.n.toLocaleString()} photos · ${albumSummary(x)}</small></div></a>`).join("")
      + `<a class="poster newalb" href="#album/new"><span>＋</span><div class="pt"><h3>New album</h3><small>from any search, person or place</small></div></a>`;
  } catch (e) { $("albumgrid").innerHTML = `<p class="status">${esc(e.message)}</p>`; }
  api("/api/dupes", { limit: 3 }).then(r => {
    const d = r.results;
    $("tidyn").textContent = `${d.total.toLocaleString()} groups · ${d.extra.toLocaleString()} extra photos`;
    $("tidyart").innerHTML = d.groups.flatMap(g => g.photos.slice(0, 1)).map(p => `<img src="/thumb/${p.uuid}.jpg" alt="">`).join("");
  }).catch(() => {});
  api("/api/clutter").then(r => {
    const ks = r.results.kinds.filter(k => k.n);
    $("clutn").textContent = ks.length ? ks.map(k => `${k.n.toLocaleString()} ${k.few}`).join(" · ") : "none found";
    $("clutart").innerHTML = ks.filter(k => k.kind !== "ids").map(k => k.covers[0]).slice(0, 3).map(u => `<img src="/thumb/${u}.jpg" alt="">`).join("");
  }).catch(() => {});
};
views.album = async arg => {
  const [id, ps] = (arg || "").split("?");
  clearTimeout(AL.timer); AL.del = false; $("albdel").textContent = "Delete album";
  if (id === "new") {  // from a search: its words and filters
    const p = new URLSearchParams(ps || ""), q = p.get("q") || "";
    const filters = Object.fromEntries(FIELDS.filter(k => k !== "exclude" && p.get(k)).map(k => [k, p.get(k)]));
    AL.a = { name: q ? q[0].toUpperCase() + q.slice(1) : filters.person || filters.place || "", q, exclude: p.get("exclude") || "", filters, pinned: [], removed: [] };
    AL.isNew = true; AL.n = 0;
  } else {
    try { AL.a = (await api("/api/album", { id })).results.album; } catch (e) { $("albstatus").textContent = e.message; return; }
    AL.a.exclude = (AL.a.exclude || []).join(", "); AL.isNew = false; AL.n = null;
  }
  $("albname").value = AL.a.name; $("albq").value = AL.a.q || "";
  $("albchips").innerHTML = Object.entries(AL.a.filters || {}).map(([k, v]) => `<span class="fchip">${esc(CHIP[k] ? CHIP[k](v) : v)}</span>`).join("");
  $("albsave").hidden = !AL.isNew; $("albdel").hidden = AL.isNew; $("albphotos").hidden = AL.isNew || !SERVER.local;
  $("albstatus").textContent = AL.isNew ? "" : "changes save as you go";
  albumRefresh(true);
};
async function albumRefresh(first = false) {
  const a = AL.a;
  if (!a.q && !Object.values(a.filters || {}).some(Boolean) && !a.pinned.length) {
    $("albgrid").innerHTML = `<p class="status">Type what the album is of, e.g. “kids at the beach”.</p>`; $("albmiss").hidden = true; return;
  }
  $("albcount").textContent = "…";
  let r;
  try { r = await post("/api/album_preview", a); } catch (e) { $("albstatus").textContent = e.message; return; }
  AL.ranked = r.ranked; AL.pinnedExtra = r.pinned; AL.scored = r.scored;
  if (AL.n == null || first) {  // an existing album: where its threshold falls now; a new one: close to the best match
    AL.n = a.threshold != null && !AL.isNew ? r.ranked.filter(x => x.score >= a.threshold - 1e-6).length
         : Math.min(150, Math.max(10, r.ranked.filter(x => x.score >= (r.ranked[0]?.score ?? 0) - 0.07).length));
  }
  AL.n = Math.max(1, Math.min(AL.n, r.ranked.length));
  $("albcut").hidden = !AL.scored;
  Object.assign($("albn"), { min: 1, max: r.ranked.length, value: AL.n });
  albumRender();
}
function albumMembers() {
  const top = AL.scored ? AL.ranked.slice(0, AL.n) : AL.ranked;
  const have = new Set(top.map(x => x.uuid));
  return [...top, ...AL.ranked.slice(AL.n).filter(x => x.pinned && !have.has(x.uuid)), ...AL.pinnedExtra];
}
function albumRender() {
  const a = AL.a, members = albumMembers(), inSet = new Set(members.map(x => x.uuid));
  const miss = AL.scored ? AL.ranked.slice(AL.n).filter(x => !inSet.has(x.uuid)).slice(0, 36) : [];
  $("albcount").textContent = `${members.length.toLocaleString()} photos`;
  $("albtaught").textContent = a.removed.length || a.pinned.length
    ? `taught by ${[a.removed.length && `${a.removed.length} taken out`, a.pinned.length && `${a.pinned.length} always in`].filter(Boolean).join(", ")}` : "";
  const acts = (x, inAlbum) => `<div class="tacts">${inAlbum ? `<button data-a="out" title="not this one: take it out, and find fewer like it">✕</button>` : ""}
    <button data-a="pin" class="${x.pinned ? "on" : ""}" title="${x.pinned ? "always in (tap to undo)" : "always keep this one in"}">${x.pinned ? "★" : inAlbum ? "☆" : "＋"}</button></div>`;
  const grid = (el, list, inAlbum) => {
    el._list = list;
    bindGrid(el, list, () => justify(el, list));
    el.querySelectorAll(".tile").forEach(t => t.insertAdjacentHTML("beforeend", acts(list[+t.dataset.i], inAlbum)));
    el.onclick = e => {
      const b = e.target.closest(".tacts button"), t = e.target.closest(".tile"); if (!t) return;
      const x = list[+t.dataset.i];
      if (!b) return lightbox(list, +t.dataset.i);
      if (b.dataset.a === "out") { a.removed.push(x.uuid); a.pinned = a.pinned.filter(u => u !== x.uuid); }
      else a.pinned = a.pinned.includes(x.uuid) ? a.pinned.filter(u => u !== x.uuid) : [...a.pinned, x.uuid];
      albumChanged(true);
    };
    const r = el._render; el._render = () => { const h = r(); setTimeout(() => el.querySelectorAll(".tile").forEach(t => { if (!t.querySelector(".tacts")) t.insertAdjacentHTML("beforeend", acts(list[+t.dataset.i], inAlbum)); })); return h; };
  };
  grid($("albgrid"), members, true);
  $("albmiss").hidden = !miss.length;
  if (miss.length) grid($("albmissgrid"), miss, false);
}
function albumChanged(rerank = false) {
  if (rerank) albumRefresh(); else albumRender();
  if (AL.isNew) return;
  $("albstatus").textContent = "saving…"; clearTimeout(AL.timer);
  AL.timer = setTimeout(albumSave, 800);
}
async function albumSave() {
  clearTimeout(AL.timer);
  const a = AL.a;
  try {
    const r = await post("/api/album", { ...a, name: $("albname").value.trim(), q: $("albq").value.trim(), n: AL.scored ? AL.n : undefined });
    if (AL.isNew) { AL.isNew = false; location.replace("#album/" + r.id); return; }
    $("albstatus").textContent = `saved ✓ · ${r.n.toLocaleString()} photos`;
  } catch (e) { $("albstatus").textContent = "not saved: " + e.message; }
}
$("albn").oninput = () => { AL.n = +$("albn").value; albumChanged(); };
$("albname").oninput = () => { AL.a.name = $("albname").value; if (!AL.isNew) albumChanged(); };
$("albq").onchange = () => { AL.a.q = $("albq").value.trim(); AL.a.threshold = null; AL.n = null; albumChanged(true); };  // new words: start from the default size
$("albsave").onclick = () => { if (!$("albname").value.trim()) { $("albname").focus(); $("albstatus").textContent = "give it a name first"; return; } albumSave(); };
$("albshow").onclick = () => openFrame({ list: albumMembers(), title: AL.a.name });
$("albphotos").onclick = async () => {
  $("albphotos").disabled = true; $("albstatus").textContent = "copying into Photos…";
  try { await albumSave(); const r = await post("/api/album_photos", { id: AL.a.id });
        $("albstatus").textContent = `Photos now has “${AL.a.name}”: ${r.added ? `${r.added} added` : "already up to date"} (${r.total} in all)`; }
  catch (e) { $("albstatus").textContent = e.message; }
  $("albphotos").disabled = false;
};
$("albdel").onclick = async () => {  // two taps, no browser dialog
  if (!AL.del) { AL.del = true; $("albdel").textContent = "Tap again to delete (Photos keeps any copy)"; return; }
  try { await post("/api/album_delete", { id: AL.a.id }); go("albums"); } catch (e) { $("albstatus").textContent = e.message; }
};
leave.album = () => { if (AL.timer) albumSave(); };

/* ---------- tidy up: near-duplicates, the sharpest kept, the rest offered to an album in Photos ---------- */
const CL = { level: store.get("cllevel", "same"), groups: [], total: 0, extra: 0, offset: 0, sending: false };
views.cleanup = () => { CL.offset = 0; CL.groups = []; cleanupLoad(); };
async function cleanupLoad() {
  document.querySelectorAll("#cllevel button").forEach(b => b.classList.toggle("on", b.dataset.l === CL.level));
  if (!CL.offset) { $("clgroups").innerHTML = `<p class="status">finding near-duplicates… (the first time, it checks which shots are sharpest)</p>`; }
  let r;
  try { r = (await api("/api/dupes", { level: CL.level, offset: CL.offset, limit: 24 })).results; }
  catch (e) { $("clgroups").innerHTML = `<p class="status">${esc(e.message)}</p>`; return; }
  if (!CL.offset) $("clgroups").innerHTML = "";
  CL.total = r.total; CL.extra = r.extra; CL.album = r.album;
  CL.groups.push(...r.groups); CL.offset += r.groups.length;
  $("clgroups").insertAdjacentHTML("beforeend", r.groups.map(cleanupGroup).join(""));
  cleanupStats(r.sent);
  $("clmore").innerHTML = CL.offset < CL.total ? `<button class="ghost" id="clmorebtn">Show more</button>` : "";
  if ($("clmorebtn")) $("clmorebtn").onclick = cleanupLoad;
}
function cleanupStats(sent) {
  $("clstats").textContent = CL.total ? `${CL.total.toLocaleString()} groups · ${CL.extra.toLocaleString()} extra photos${sent ? ` · ${sent.toLocaleString()} already in “${CL.album}”` : ""}` : "no near-duplicates found";
  $("clsend").hidden = !SERVER.local || !CL.total;
  $("clsend").textContent = `Send the extras to “${CL.album}” in Photos`;
  $("clphone").hidden = SERVER.local;
}
function cleanupGroup(g) {
  const p0 = g.photos[0];
  return `<div class="clg" data-key="${esc(g.key)}">
    <div class="clh"><b>${p0.undated ? "" : longDate(p0.date, { month:"short", day:"numeric", year:"numeric" })}${p0.place ? " · " + esc(short(p0.place)) : ""}</b>
      <small>${g.kind === "copy" ? "the same picture, saved more than once" : `${g.photos.length} shots in a row`}</small><span class="sp"></span>
      <button class="ghost tiny" data-a="nope" title="they're different: stop suggesting this group">Not duplicates</button></div>
    <div class="clrow">${g.photos.map((p, i) => `<figure data-i="${i}" class="${p.uuid === g.keep ? "keep" : ""} ${p.sent ? "sent" : ""}" style="--ar:${clampAr(p.ar)}">
      <img loading="lazy" src="/thumb/${p.uuid}.jpg" alt=""><button class="zoom" data-a="zoom" title="see it big">⤢</button>
      <figcaption>${p.uuid === g.keep ? `✓ keep · ${g.why}` : p.sent ? "in maybe delete" : "tap to keep this one"}</figcaption></figure>`).join("")}</div></div>`;
}
$("clgroups").onclick = async e => {
  const card = e.target.closest(".clg"); if (!card) return;
  const g = CL.groups.find(x => x.key === card.dataset.key); if (!g) return;
  const b = e.target.closest("[data-a]"), fig = e.target.closest("figure");
  if (b?.dataset.a === "zoom") return lightbox(g.photos, +fig.dataset.i);
  if (b?.dataset.a === "nope") {
    try { await post("/api/dupes", { action: "nope", key: g.key }); } catch (err) { return; }
    card.remove(); CL.total--; CL.extra -= g.photos.length - 1; cleanupStats(); return;
  }
  if (fig && g.photos[+fig.dataset.i].uuid !== g.keep) {
    const u = g.photos[+fig.dataset.i].uuid;
    try { await post("/api/dupes", { action: "keep", key: g.key, uuid: u }); } catch (err) { return; }
    g.keep = u; g.why = "your pick"; card.outerHTML = cleanupGroup(g);
  }
};
$("cllevel").onclick = e => { const l = e.target.dataset.l; if (!l || l === CL.level) return; CL.level = l; store.set("cllevel", l); views.cleanup(); };
/* ---------- tidy up: clutter, by kind, each offered to its own album in Photos ---------- */
const CU = { kind: store.get("clukind", "screenshots"), photos: [], total: 0, offset: 0, sending: false, kinds: [] };
views.clutter = () => { CU.offset = 0; CU.photos = []; clutterLoad(); };
async function clutterLoad() {
  if (!CU.offset) $("clugrid").innerHTML = `<p class="status">looking…</p>`;
  let r;
  try { r = (await api("/api/clutter", { kind: CU.kind, offset: CU.offset, limit: 60 })).results; }
  catch (e) { $("clugrid").innerHTML = `<p class="status">${esc(e.message)}</p>`; return; }
  CU.kinds = r.kinds; CU.total = r.total;
  $("clukinds").innerHTML = r.kinds.map(k => `<button data-k="${k.kind}" class="${k.kind === CU.kind ? "on" : ""}">${esc(k.name)} <small>${k.n.toLocaleString()}</small></button>`).join("");
  if (!CU.offset) $("clugrid").innerHTML = "";
  const at = CU.photos.length; CU.photos.push(...r.photos); CU.offset += r.photos.length;
  $("clugrid").insertAdjacentHTML("beforeend", r.photos.map((p, i) => `<figure data-i="${at + i}" class="${p.sent ? "sent" : ""}">
    <img loading="lazy" src="/thumb/${p.uuid}.jpg" alt=""><button class="zoom" data-a="zoom" title="see it big">⤢</button>
    <button class="cluno" data-a="not" title="not clutter: stop suggesting it">✕</button>
    ${p.sent ? `<figcaption>in the album</figcaption>` : ""}</figure>`).join(""));
  if (!CU.total) $("clugrid").innerHTML = `<p class="status">None found.</p>`;
  $("clumore").innerHTML = CU.offset < CU.total ? `<button class="ghost" id="clumorebtn">Show more</button>` : "";
  if ($("clumorebtn")) $("clumorebtn").onclick = clutterLoad;
  clutterStats();
}
function clutterStats() {
  const k = CU.kinds.find(x => x.kind === CU.kind); if (!k) return;
  const todo = CU.total - k.sent;
  $("clustats").textContent = `${CU.total.toLocaleString()} photos${k.sent ? ` · ${k.sent.toLocaleString()} already in “${k.album}”` : ""}`;
  $("clusend").hidden = !SERVER.local || !todo; CU.sending = false;
  $("clusend").textContent = `Send ${todo.toLocaleString()} to “${k.album}” in Photos`;
  $("cluphone").hidden = SERVER.local;
}
$("clukinds").onclick = e => { const b = e.target.closest("[data-k]"); if (!b || b.dataset.k === CU.kind) return; CU.kind = b.dataset.k; store.set("clukind", CU.kind); views.clutter(); };
$("clugrid").onclick = async e => {
  const fig = e.target.closest("figure"); if (!fig) return;
  const b = e.target.closest("[data-a]"), p = CU.photos[+fig.dataset.i];
  if (b?.dataset.a === "not") {
    try { await post("/api/clutter", { action: "not", uuid: p.uuid }); } catch (err) { return; }
    fig.remove(); CU.total--; const k = CU.kinds.find(x => x.kind === CU.kind); k.n--; if (p.sent) k.sent--;
    $("clukinds").querySelector(".on small").textContent = k.n.toLocaleString(); clutterStats(); return;
  }
  lightbox(CU.photos, +fig.dataset.i);
};
$("clusend").onclick = async () => {  // two taps, no browser dialog
  const k = CU.kinds.find(x => x.kind === CU.kind);
  if (!CU.sending) { CU.sending = true; $("clusend").textContent = `Tap again: add them to “${k.album}” (nothing gets deleted)`; return; }
  CU.sending = false; $("clusend").disabled = true; $("clustats").textContent = "adding them in Photos…";
  try { const r = await post("/api/clutter_send", { kind: CU.kind });
        $("clustats").textContent = `Done: ${r.added.toLocaleString()} photos are in “${r.album}”. Look through it in Photos.`;
        $("clusend").hidden = true; }
  catch (err) { $("clustats").textContent = err.message; }
  $("clusend").disabled = false;
};

$("clsend").onclick = async () => {  // two taps, no browser dialog
  if (!CL.sending) { CL.sending = true; $("clsend").textContent = `Tap again: add ${CL.extra.toLocaleString()} extras to “${CL.album}” (nothing gets deleted)`; return; }
  CL.sending = false; $("clsend").disabled = true; $("clstats").textContent = "adding them in Photos… (a minute or two for thousands)";
  try { const r = await post("/api/dupes_send", { level: CL.level });
        $("clstats").textContent = `Done: ${r.added.toLocaleString()} photos are in “${r.album}”. Look through it in Photos and delete what you don't want there.`; }
  catch (err) { $("clstats").textContent = err.message; }
  $("clsend").disabled = false;
};
