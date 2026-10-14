// Stories, and the story editor.
// Plain scripts sharing one global scope, loaded in order by index.html; no build step.

/* ---------- stories ---------- */
function dateRange(a, b) {
  const d = x => { const [y, m, day] = x.split("-").map(Number); return new Date(y, m - 1, day); };
  const [s, e] = [d(a), d(b)], md = { month:"short", day:"numeric" };
  if (a === b) return s.toLocaleDateString(undefined, { ...md, year:"numeric" });
  if (s.getFullYear() !== e.getFullYear())
    return `${s.toLocaleDateString(undefined, { ...md, year:"numeric" })} – ${e.toLocaleDateString(undefined, { ...md, year:"numeric" })}`;
  const end = s.getMonth() === e.getMonth() ? e.getDate() : e.toLocaleDateString(undefined, md);
  return `${s.toLocaleDateString(undefined, md)}–${end}, ${e.getFullYear()}`;
}
function poster(x, acts = false) {
  const by = { claude: "✨ by Claude", you: "✏️ by you" }[x.made_by];
  return `<a class="poster ${x.kind === "year" ? "year" : ""}" href="/review/${x.id}" target="_blank" title="${x.made_by ? "play" : "make & play"}">
    ${x.cover ? `<img loading="lazy" src="/thumb/${x.cover}.jpg" alt="">` : ""}
    ${by && x.kind === "trip" ? `<span class="by">${by}${x.edited ? ", edited" : ""}</span>` : ""}
    ${acts ? `<span class="pacts">${x.made_by ? `<span data-go="/review/${x.id}?download=1" title="download, to send to family">⤓</span>` : ""}<span data-go="#edit/${x.id}" title="edit">✎</span></span>` : ""}
    <div class="pt"><h3>${esc(x.title)}</h3><small>${x.kind === "trip" ? dateRange(x.start, x.end) + " · " : ""}${x.photos.toLocaleString()} photos${by && x.kind === "year" ? " · " + by : ""}</small></div>
  </a>`;
}
views.stories = async () => {
  const r = await loadStories.fresh();
  $("trips").innerHTML = r.filter(x => x.kind === "trip").map(x => poster(x, true)).join("") || `<p class="status">No trips found yet: they need photos with locations.</p>`;
  $("years").innerHTML = r.filter(x => x.kind === "year").map(x => poster(x, true)).join("");
};
loadStories.fresh = async () => (await api("/api/stories")).results;  // edits change titles and authors
// links inside a poster link: open their own target, not the slideshow
document.addEventListener("click", e => {
  const a = e.target.closest(".pacts [data-go]"); if (!a) return;
  e.preventDefault(); e.stopPropagation();
  location.href = a.dataset.go;
}, true);

/* ---------- story editor ---------- */
// E.story is the story being edited; every change snapshots it for undo, re-renders, and saves after a pause.
const E = { story: null, undo: [], timer: 0, typed: null, drag: null, pick: null, found: [] };
const shortDate = d => { const [y, m, day] = d.split("-").map(Number); return new Date(y, m - 1, day).toLocaleDateString(undefined, { month:"short", day:"numeric" }); };
const firstNames = p => (p.persons || []).slice(0, 3).map(n => n.split(" ")[0]).join(" & ");
const used = () => new Set(E.story.chapters.flatMap(c => c.photos.map(p => p.uuid)));

views.edit = async id => {
  if (E.timer) await saveStory();
  closePick();
  $("edstatus").textContent = "loading…"; $("edchapters").innerHTML = "";
  try { E.story = (await api("/api/story", { id })).results; }
  catch (e) { $("edstatus").textContent = e.message; return; }
  E.undo = []; renderEdit(); $("edstatus").textContent = "";
};
function leaveEdit() { closePick(); if (E.timer) saveStory(); }
addEventListener("pagehide", () => { if (E.timer) saveStory(true); });

function renderEdit() {
  const s = E.story;
  for (const f of ["title", "intro", "outro"]) $("ed" + f).value = s[f] || "";
  $("edplay").href = `/review/${s.id}`;
  $("edundo").disabled = !E.undo.length;
  $("edchapters").innerHTML = s.chapters.map((c, ci) => `
    <div class="ch" data-ch="${ci}">
      <div class="chhead">
        <input data-f="title" value="${esc(c.title)}" placeholder="Chapter title">
        <button class="ghost tiny" data-a="up" title="move chapter up" ${ci ? "" : "disabled"}>↑</button>
        <button class="ghost tiny" data-a="down" title="move chapter down" ${ci < s.chapters.length - 1 ? "" : "disabled"}>↓</button>
        <button class="ghost tiny" data-a="drop" title="delete chapter and its photos (undo brings it back)">✕</button>
      </div>
      <input data-f="text" value="${esc(c.text || "")}" placeholder="A line for the chapter card (optional)">
      <div class="strip">
        ${c.photos.map((p, i) => `
          <figure draggable="true" data-i="${i}">
            <img src="/thumb/${p.uuid}.jpg" loading="lazy" alt="" draggable="false">
            <div class="tools"><button data-a="left" title="earlier">←</button><span class="sp"></span>
              <button data-a="swap" title="swap for a similar photo">↻</button><button data-a="del" title="remove">✕</button>
              <span class="sp"></span><button data-a="right" title="later">→</button></div>
            <textarea data-f="caption" rows="3" placeholder="caption">${esc(p.caption)}</textarea>
            <small>${shortDate(p.date)}${p.place ? " · " + esc(p.place.split(",")[0]) : ""}</small>
          </figure>`).join("") || `<span class="empty">No photos yet: drag some here, or add them →</span>`}
        <button class="ghost add" data-a="add">+ Add photos</button>
      </div>
    </div>`).join("");
}

function snapshot() {
  E.undo.push(JSON.stringify(E.story));
  if (E.undo.length > 100) E.undo.shift();
}
function changed(rerender = true) {
  if (rerender) renderEdit();
  $("edundo").disabled = !E.undo.length;
  $("edstatus").textContent = "editing…";
  clearTimeout(E.timer); E.timer = setTimeout(saveStory, 700);
}
async function saveStory(leaving = false) {
  clearTimeout(E.timer); E.timer = 0;
  const s = E.story;
  const body = { id: s.id, title: s.title, intro: s.intro || "", outro: s.outro || "",
                 chapters: s.chapters.map(c => ({ title: c.title, text: c.text || "",
                                                   photos: c.photos.map(p => ({ uuid: p.uuid, caption: p.caption || "" })) })) };
  try {
    const r = await fetch("/api/story", { method: "POST", headers: { "content-type": "application/json" },
                                          body: JSON.stringify(body), keepalive: leaving });
    const j = await r.json();
    if (!r.ok || j.error) throw new Error(j.error || r.statusText);
    if (location.hash.startsWith("#edit/" + s.id)) $("edstatus").textContent = "saved ✓";
  } catch (e) { $("edstatus").textContent = "not saved: " + e.message; }
}
$("edundo").onclick = () => {
  if (!E.undo.length) return;
  E.story = JSON.parse(E.undo.pop()); E.typed = null; changed();
};
addEventListener("keydown", e => {  // ⌘Z / Ctrl-Z undoes story changes; inside a text box it stays the box's own undo
  if (location.hash.startsWith("#edit/") && (e.metaKey || e.ctrlKey) && e.key === "z" && !e.shiftKey
      && !/INPUT|TEXTAREA/.test(document.activeElement?.tagName)) { e.preventDefault(); $("edundo").click(); }
});

// typing: one undo step per field visit, and no re-render (it would steal the cursor)
$("ed").addEventListener("focusin", e => { if (e.target.dataset.f) E.typed = null; });
$("ed").addEventListener("input", e => {
  const f = e.target.dataset.f; if (!f) return;
  if (E.typed !== e.target) { snapshot(); E.typed = e.target; }
  const ch = e.target.closest(".ch"), fig = e.target.closest("figure");
  const c = ch && E.story.chapters[ch.dataset.ch];
  if (fig) c.photos[fig.dataset.i].caption = e.target.value;
  else if (c) c[f] = e.target.value;
  else E.story[f] = e.target.value;
  changed(false);
});

function movePhoto(from, to) {  // from/to: [chapter, index]; to's index is counted before removing
  const [fc, fi] = from, [tc, ti] = to, src = E.story.chapters[fc].photos, dst = E.story.chapters[tc].photos;
  const [p] = src.splice(fi, 1);
  dst.splice(fc === tc && ti > fi ? ti - 1 : ti, 0, p);
}
$("edchapters").onclick = e => {
  const b = e.target.closest("[data-a]"); if (!b) return;
  const cs = E.story.chapters, ci = +b.closest(".ch").dataset.ch, c = cs[ci];
  const i = b.closest("figure") ? +b.closest("figure").dataset.i : -1;
  const a = b.dataset.a;
  if (a === "add") return openPick("add", ci);
  if (a === "swap") return openPick("swap", ci, i);
  snapshot();
  if (a === "del") c.photos.splice(i, 1);
  if (a === "left") i > 0 ? movePhoto([ci, i], [ci, i - 1]) : ci > 0 && movePhoto([ci, i], [ci - 1, cs[ci - 1].photos.length]);
  if (a === "right") i < c.photos.length - 1 ? movePhoto([ci, i], [ci, i + 2]) : ci < cs.length - 1 && movePhoto([ci, i], [ci + 1, 0]);
  if (a === "up" || a === "down") { const j = a === "up" ? ci - 1 : ci + 1; [cs[ci], cs[j]] = [cs[j], cs[ci]]; }
  if (a === "drop") cs.splice(ci, 1);
  changed();
};
$("edaddch").onclick = () => { snapshot(); E.story.chapters.push({ title: "New chapter", text: "", photos: [] }); changed(); };

// drag and drop: onto a photo puts it before that photo; onto the rest of a strip puts it at the end
$("edchapters").addEventListener("dragstart", e => {
  const fig = e.target.closest?.("figure"); if (!fig) return;
  E.drag = [+fig.closest(".ch").dataset.ch, +fig.dataset.i];
  e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", "");
  fig.classList.add("drag");
});
$("edchapters").addEventListener("dragend", () => {
  E.drag = null; document.querySelectorAll("#edchapters .drag, #edchapters .over").forEach(x => x.classList.remove("drag", "over"));
});
$("edchapters").addEventListener("dragover", e => {
  if (!E.drag) return;
  const strip = e.target.closest(".strip"); if (!strip) return;
  e.preventDefault();
  const fig = e.target.closest("figure");
  document.querySelectorAll("#edchapters .over").forEach(x => x.classList.remove("over"));
  (fig || strip).classList.add("over");
});
$("edchapters").addEventListener("drop", e => { if (E.drag && e.target.closest(".strip")) { e.preventDefault(); dropOn(e.target); } });
function dropOn(el) {
  const strip = el?.closest?.(".strip"); if (!E.drag || !strip) return;
  const tc = +strip.closest(".ch").dataset.ch, fig = el.closest("figure");
  const to = [tc, fig ? +fig.dataset.i : E.story.chapters[tc].photos.length];
  if (to[0] !== E.drag[0] || (to[1] !== E.drag[1] && to[1] !== E.drag[1] + 1)) { snapshot(); movePhoto(E.drag, to); changed(); }
}
// touch: press and hold a photo to pick it up, drag it, let go to drop it (the same rules as the mouse)
const TD = { timer: 0, on: false, ghost: null, x: 0, y: 0 };
$("edchapters").addEventListener("pointerdown", e => {
  if (e.pointerType === "mouse") return;
  const fig = e.target.closest(".strip figure"); if (!fig || e.target.closest("button, textarea")) return;
  TD.x = e.clientX; TD.y = e.clientY; clearTimeout(TD.timer);
  TD.timer = setTimeout(() => {
    TD.on = true; E.drag = [+fig.closest(".ch").dataset.ch, +fig.dataset.i]; fig.classList.add("drag");
    TD.ghost = fig.querySelector("img").cloneNode(); TD.ghost.className = "tghost"; document.body.append(TD.ghost);
    moveGhost(TD.x, TD.y); navigator.vibrate?.(12);
  }, 380);
});
const moveGhost = (x, y) => { TD.ghost.style.transform = `translate(${x - 50}px, ${y - 50}px) rotate(-4deg)`; };
addEventListener("pointermove", e => {
  if (!TD.on) { if (TD.timer && Math.hypot(e.clientX - TD.x, e.clientY - TD.y) > 8) { clearTimeout(TD.timer); TD.timer = 0; } return; }
  moveGhost(e.clientX, e.clientY);
  const el = document.elementFromPoint(e.clientX, e.clientY);
  document.querySelectorAll("#edchapters .over").forEach(x => x.classList.remove("over"));
  const strip = el?.closest(".strip"); if (strip) (el.closest("figure") || strip).classList.add("over");
  if (e.clientY < 90) scrollBy(0, -14); else if (e.clientY > innerHeight - 90) scrollBy(0, 14);  // to reach other chapters
});
addEventListener("touchmove", e => { if (TD.on) e.preventDefault(); }, { passive: false });  // no scrolling while carrying a photo
function touchDrop(e, drop) {
  clearTimeout(TD.timer); TD.timer = 0; if (!TD.on) return;
  TD.on = false; TD.ghost.remove();
  if (drop) dropOn(document.elementFromPoint(e.clientX, e.clientY));
  E.drag = null; document.querySelectorAll("#edchapters .drag, #edchapters .over").forEach(x => x.classList.remove("drag", "over"));
}
addEventListener("pointerup", e => touchDrop(e, true));
addEventListener("pointercancel", e => touchDrop(e, false));

// the picker: photos from the story's days, to add to a chapter or to swap in
function openPick(mode, ci, i) {
  E.pick = { mode, ci, i };
  const c = E.story.chapters[ci];
  $("pickt").textContent = mode === "swap" ? "Swap for a similar photo" : `Add to “${c.title}”`;
  $("pickq").value = "";
  $("edpick").classList.add("on");
  loadPick(mode === "swap" ? { like: c.photos[i].uuid } : {});
}
function closePick() { $("edpick").classList.remove("on"); E.pick = null; }
$("pickclose").onclick = closePick;
$("pickf").onsubmit = e => {
  e.preventDefault();
  const q = $("pickq").value.trim(), p = E.pick;
  loadPick(q ? { q } : p.mode === "swap" ? { like: E.story.chapters[p.ci].photos[p.i].uuid } : {});
};
async function loadPick(params) {
  const what = params.q ? `matches for “${params.q}”` : params.like ? "look-alikes" : "photos";
  $("pickstatus").textContent = `finding ${what} from these days…`; $("pickgrid").innerHTML = "";
  try { E.found = (await api("/api/story_photos", { id: E.story.id, ...params })).results; }
  catch (e) { $("pickstatus").textContent = e.message; return; }
  renderPick(what);
}
function renderPick(what) {
  const have = used();
  $("pickstatus").textContent = E.found.length ? `${E.found.length} ${what} · dimmed ones are already in the story` : `no ${what}`;
  $("pickgrid").innerHTML = E.found.map((p, k) => `<figure data-k="${k}" class="${have.has(p.uuid) ? "used" : ""}">
    <img src="/thumb/${p.uuid}.jpg" loading="lazy" alt=""><small>${shortDate(p.date)}${p.place ? " · " + esc(p.place.split(",")[0]) : ""}</small></figure>`).join("");
}
$("pickgrid").onclick = e => {
  const fig = e.target.closest("figure"); if (!fig || fig.classList.contains("used") || !E.pick) return;
  const p = E.found[fig.dataset.k], { mode, ci, i } = E.pick, photos = E.story.chapters[ci].photos;
  snapshot();
  if (mode === "swap") {  // keep the caption: a look-alike is usually the same moment
    photos[i] = { ...p, caption: photos[i].caption };
    closePick();
  } else {  // slot it in by time, and stay open to add more
    const at = photos.findIndex(x => x.taken > p.taken);
    photos.splice(at < 0 ? photos.length : at, 0, { ...p, caption: firstNames(p) });
    fig.classList.add("used");
  }
  changed();
};
leave.edit = leaveEdit;
