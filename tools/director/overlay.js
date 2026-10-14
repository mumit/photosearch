// Injected by director.py into the page it records (never part of the app): a cursor that glides to things and
// clicks them, typing that looks like a person's, and captions. Everything is drawn above the page and ignores the mouse.
window.__demo = (() => {
  const style = document.createElement("style");
  style.textContent = `
    #__cur { position:fixed; z-index:2147483647; left:0; top:0; pointer-events:none; will-change:transform; }
    #__cur svg { display:block; filter:drop-shadow(0 2px 4px rgba(0,0,0,.45)); transition:transform .12s; }
    #__cur.down svg { transform:scale(.86); }
    .__ripple { position:fixed; z-index:2147483646; width:44px; height:44px; margin:-22px 0 0 -22px; border-radius:50%;
                border:2.5px solid rgba(255,255,255,.95); box-shadow:0 0 0 2px rgba(0,0,0,.15); pointer-events:none;
                animation:__ripple .55s cubic-bezier(.2,.7,.3,1) forwards; }
    @keyframes __ripple { from { transform:scale(.25); opacity:1 } to { transform:scale(1.5); opacity:0 } }
    #__cap { position:fixed; z-index:2147483645; left:50%; bottom:6.5%; transform:translate(-50%, 12px); opacity:0;
             max-width:min(80vw, 980px); padding:14px 26px; border-radius:16px; text-align:center; pointer-events:none;
             font:600 clamp(18px, 2.3vw, 30px)/1.25 -apple-system, BlinkMacSystemFont, system-ui, sans-serif; letter-spacing:-.01em;
             color:#fff; background:rgba(14,13,12,.78); backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px);
             box-shadow:0 12px 40px rgba(0,0,0,.35); transition:opacity .35s, transform .35s; }
    #__cap.on { opacity:1; transform:translate(-50%, 0); }
    #__cap small { display:block; margin-top:4px; font-weight:500; font-size:.6em; color:rgba(255,255,255,.75); }`;
  document.documentElement.append(style);
  const cur = document.createElement("div");
  cur.id = "__cur";
  cur.innerHTML = `<svg width="26" height="30" viewBox="0 0 26 30"><path d="M3 2 L3 24 L9 18.5 L13.2 27.5 L17.4 25.6 L13.3 16.8 L21.5 16.6 Z"
    fill="#111" stroke="#fff" stroke-width="2" stroke-linejoin="round"/></svg>`;
  const cap = document.createElement("div");
  cap.id = "__cap";
  const ready = () => document.body && !cur.isConnected && document.body.append(cur, cap);
  ready(); addEventListener("DOMContentLoaded", ready);

  let x = innerWidth * 0.62, y = innerHeight * 0.72;
  const place = () => { cur.style.transform = `translate(${x - 3}px, ${y - 2}px)`; };
  place();
  const sleep = ms => new Promise(ok => setTimeout(ok, ms));
  const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  const el = sel => {
    const e = typeof sel === "string" ? document.querySelector(sel) : sel;
    if (!e) throw new Error("nothing matches " + sel);
    return e;
  };

  // Glide along a slight curve, as a hand does, taking longer for longer trips.
  async function moveTo(tx, ty, ms) {
    ready();
    const sx = x, sy = y, d = Math.hypot(tx - sx, ty - sy);
    ms = ms ?? Math.min(1100, 380 + d * 0.6);
    const bend = (Math.random() - .5) * Math.min(120, d * .25), nx = -(ty - sy) / (d || 1), ny = (tx - sx) / (d || 1);
    const t0 = performance.now();
    await new Promise(done => {
      const step = now => {
        const t = Math.min(1, (now - t0) / ms), e = ease(t), arc = Math.sin(Math.PI * e) * bend;
        x = sx + (tx - sx) * e + nx * arc; y = sy + (ty - sy) * e + ny * arc; place();
        t < 1 ? requestAnimationFrame(step) : done();
      };
      requestAnimationFrame(step);
    });
  }

  async function to(sel, { dx = 0.5, dy = 0.5, ms } = {}) {
    const e = el(sel);
    e.scrollIntoView({ block: "nearest", inline: "nearest" });
    const r = e.getBoundingClientRect();
    await moveTo(r.left + r.width * dx, r.top + r.height * dy, ms);
    return e;
  }

  async function click(sel, opts) {
    const e = await to(sel, opts);
    await sleep(90);
    cur.classList.add("down");
    const ring = document.createElement("div");
    ring.className = "__ripple"; ring.style.left = x + "px"; ring.style.top = y + "px";
    document.body.append(ring); setTimeout(() => ring.remove(), 700);
    await sleep(110);
    cur.classList.remove("down");
    e.click();
    return e;
  }

  // Types like a person: an uneven rhythm, a little longer after a space.
  async function type(sel, text, { cps = 13 } = {}) {
    const e = await click(sel);
    e.focus();
    for (const ch of text) {
      e.value += ch;
      e.dispatchEvent(new Event("input", { bubbles: true }));
      await sleep(1000 / cps * (0.55 + Math.random() * 0.9) + (ch === " " ? 70 : 0));
    }
    return e;
  }

  function caption(text, sub) {
    if (!text) return cap.classList.remove("on");
    cap.innerHTML = text + (sub ? `<small>${sub}</small>` : "");
    cap.classList.add("on");
  }

  const hide = () => { cur.style.opacity = 0; };
  const show = () => { cur.style.opacity = 1; };
  return { moveTo, to, click, type, caption, sleep, hide, show };
})();
