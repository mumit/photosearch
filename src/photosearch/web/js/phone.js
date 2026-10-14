// On your phone: the address and passcode as a QR code (shown on the Mac only).
// Plain scripts sharing one global scope, loaded in order by index.html; no build step.

/* ---------- on your phone: the address and passcode as a QR code (shown on the Mac only) ---------- */
$("phonebtn").hidden = !SERVER.local;
$("phonebtn").onclick = async () => {
  const lan = SERVER.lan;
  $("phonebody").innerHTML = lan ? `<div class="kick">On your phone or iPad</div><h2>Scan to open Photosearch</h2>
      <div id="qr"></div>
      <p>Or open <b>${esc(lan.url)}</b> and type the passcode <b class="code">${esc(lan.code)}</b></p>
      <p class="status">Same Wi-Fi as this Mac. Then use <b>Share → Add to Home Screen</b> to keep it as an app; on a spare iPad,
        open 🖼 Photo frame. To sign every device out: <code>photosearch serve --lan --new-passcode</code>.</p>`
    : `<div class="kick">On your phone or iPad</div><h2>Turn on home Wi-Fi access</h2>
      <p>Right now only this Mac can open Photosearch. To let the family's phones and iPads in (with a passcode), stop the server
        (Ctrl-C) and start it with:</p><pre>uv run photosearch serve --lan</pre>
      <p class="status">Then come back here: this button shows a QR code to scan.</p>`;
  $("phone").hidden = false;
  if (lan) {
    try {
      if (!window.QRCode) await new Promise((ok, fail) => { const sc = document.createElement("script");
        sc.src = "https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"; sc.onload = ok; sc.onerror = fail; document.head.append(sc); });
      new QRCode($("qr"), { text: `${lan.url}/login?code=${encodeURIComponent(lan.code)}`, width: 220, height: 220, colorDark: "#000", colorLight: "#fff" });
    } catch { $("qr").innerHTML = `<p class="status">(The QR code needs internet to draw; type the address instead.)</p>`; }
  }
};
$("phonex").onclick = () => { $("phone").hidden = true; };
$("phone").onclick = e => { if (e.target.id === "phone") $("phone").hidden = true; };
