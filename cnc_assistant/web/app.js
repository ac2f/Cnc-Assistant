"use strict";
// CNC-Assistant tarayici mantigi (bagimliliksiz vanilla JS)

const SVGNS = "http://www.w3.org/2000/svg";

async function api(uc, veri) {
  const r = await fetch(uc, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(veri || {}),
  });
  return r.json();
}

// ---- sekme gecisi ----
document.querySelectorAll(".tab").forEach(t => {
  t.onclick = () => {
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("aktif"));
    t.classList.add("aktif");
    ["dxf", "gcode", "proje"].forEach(id =>
      document.getElementById("tab-" + id).classList.toggle("gizli",
        id !== t.dataset.tab));
  };
});

// =====================================================================
// SVG cizim yardimcilari
// =====================================================================
function svgKur(svg) { while (svg.firstChild) svg.removeChild(svg.firstChild); }

function fitDonusum(bbox, W, H, pad) {
  const [x0, y0, x1, y1] = bbox;
  const w = Math.max(x1 - x0, 1e-6), h = Math.max(y1 - y0, 1e-6);
  const s = Math.min((W - 2 * pad) / w, (H - 2 * pad) / h);
  const ox = (W - s * w) / 2, oy = (H - s * h) / 2;
  // Y'yi ters cevir (CNC'de yukari +)
  return (x, y) => [ox + (x - x0) * s, H - (oy + (y - y0) * s)];
}

function tumBbox(konturListesi) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  konturListesi.forEach(pts => pts.forEach(p => {
    x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]);
    x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]);
  }));
  if (!isFinite(x0)) return [0, 0, 1, 1];
  return [x0, y0, x1, y1];
}

function ekle(svg, tip, attrs) {
  const e = document.createElementNS(SVGNS, tip);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  svg.appendChild(e);
  return e;
}

// DXF panellerini ciz
function cizDxf(svgId, varliklar, riskliHandlelar, baslangicGoster) {
  const svg = document.getElementById(svgId);
  svgKur(svg);
  const W = svg.clientWidth || 600, H = svg.clientHeight || 420;
  const bbox = tumBbox(varliklar.map(v => v.kontur));
  const T = fitDonusum(bbox, W, H, 24);
  const riskliSet = new Set(riskliHandlelar || []);
  varliklar.forEach(v => {
    const riskli = riskliSet.has(v.handle);
    const d = v.kontur.map((p, i) => {
      const [px, py] = T(p[0], p[1]);
      return (i ? "L" : "M") + px.toFixed(1) + " " + py.toFixed(1);
    }).join(" ");
    ekle(svg, "path", { d, fill: "none",
      stroke: riskli ? "#ef4444" : "#5b8def",
      "stroke-width": riskli ? 2 : 1.2 });
    if (baslangicGoster && v.baslangic) {
      const [px, py] = T(v.baslangic[0], v.baslangic[1]);
      ekle(svg, "circle", { cx: px, cy: py, r: 5, fill: "#22c55e",
        stroke: "#0b0f18", "stroke-width": 1 });
    } else if (v.baslangic) {
      const [px, py] = T(v.baslangic[0], v.baslangic[1]);
      ekle(svg, "circle", { cx: px, cy: py, r: 4, fill: "#8b97b3" });
    }
  });
}

// =====================================================================
// DXF sekmesi
// =====================================================================
async function dxfOnizle() {
  const yol = document.getElementById("dxfYol").value.trim();
  if (!yol) return;
  const durum = document.getElementById("dxfDurum");
  durum.textContent = "Isleniyor...";
  const veri = {
    yol,
    node_temizle: document.getElementById("nodeTemiz").checked,
    node_tol: parseFloat(document.getElementById("nodeTol").value) || 1e-6,
    bas_x_orani: parseFloat(document.getElementById("basX").value),
    serit_y_orani: parseFloat(document.getElementById("seritY").value),
  };
  const s = await api("/api/dxf/onizle", veri);
  if (s.hata) { durum.innerHTML = "<span class='hata'>" + s.hata + "</span>"; return; }
  cizDxf("svgOncesi", s.oncesi, [], true);
  cizDxf("svgSonrasi", s.sonrasi, s.riskli_handlelar, true);
  durum.innerHTML =
    `<span class='ok'>Kaydedildi:</span> ${s.cikti}\n` +
    `Baslangici tasinan: <b>${s.kaydirilan}</b> · ` +
    `Kaldirilan gereksiz node: <b>${s.silinen_node}</b> · ` +
    `Cember→polyline: <b>${s.cember}</b> · ` +
    `Riskli parca: <b>${s.riskli.length}</b> · ` +
    `Butunluk: ${s.dogrulama ? "<span class='ok'>birebir korundu</span>"
      : "<span class='hata'>UYARI</span>"}`;
}

// =====================================================================
// G-Code sekmesi
// =====================================================================
let GC = { yol: null, bloklar: [], sira: [], gecmis: [], ileri: [] };

async function gcYukle() {
  const yol = document.getElementById("gcYol").value.trim();
  if (!yol) return;
  const durum = document.getElementById("gcDurum");
  durum.textContent = "Yukleniyor...";
  const s = await api("/api/gcode/yukle", { yol });
  if (s.hata) { durum.innerHTML = "<span class='hata'>" + s.hata + "</span>"; return; }
  if (!s.guvenli) {
    durum.innerHTML = "<span class='hata'>" + s.uyarilar.join(" ") + "</span>";
    document.getElementById("gcAlan").style.display = "none";
    return;
  }
  GC = { yol, bloklar: s.bloklar, sira: s.onerilen_sira.slice(),
         gecmis: [], ileri: [] };
  document.getElementById("gcAlan").style.display = "block";
  let msg = `${s.bloklar.length} kesim blogu yuklendi. ` +
            `Icerme-oncelikli (en icteki once) auto-sira uygulandi.`;
  if (s.uyarilar.length) msg += "\n[Guvenlik] " + s.uyarilar.join(" ");
  durum.textContent = msg;
  await ciz(true);
}

function anlikKaydet() { GC.gecmis.push(GC.sira.slice()); GC.ileri = []; }

async function gcSirala(mod) {
  const s = await api("/api/gcode/sirala", { yol: GC.yol, mod });
  if (s.hata) return;
  anlikKaydet();
  GC.sira = s.sira;
  await ciz();
}

function swapUygula() {
  const g = document.getElementById("swapGiris").value.trim().split(/\s+/);
  if (g.length < 2) return;
  const i = parseInt(g[0]) - 1, j = parseInt(g[1]) - 1;
  if (isNaN(i) || isNaN(j) || i < 0 || j < 0 ||
      i >= GC.sira.length || j >= GC.sira.length) return;
  anlikKaydet();
  [GC.sira[i], GC.sira[j]] = [GC.sira[j], GC.sira[i]];
  document.getElementById("swapGiris").value = "";
  ciz();
}

function tasi(kaynak, hedef) {
  anlikKaydet();
  const [b] = GC.sira.splice(kaynak, 1);
  GC.sira.splice(hedef, 0, b);
  ciz();
}

function geriAl() { if (GC.gecmis.length) { GC.ileri.push(GC.sira.slice());
  GC.sira = GC.gecmis.pop(); ciz(); } }
function ileriAl() { if (GC.ileri.length) { GC.gecmis.push(GC.sira.slice());
  GC.sira = GC.ileri.pop(); ciz(); } }

async function gcKaydet() {
  const s = await api("/api/gcode/kaydet", { yol: GC.yol, sira: GC.sira });
  const info = document.getElementById("gcInfo");
  if (s.hata) { info.innerHTML = "<span class='hata'>" + s.hata + "</span>"; return; }
  let m = `<span class='ok'>Kaydedildi:</span> ${s.cikti} · ` +
          `bosta yol: <b>${s.bosta_yol.toFixed(1)}</b>`;
  if (s.ihlaller && s.ihlaller.length)
    m += `<br><span class='hata'>UYARI: ${s.ihlaller.length} icerme ihlali ` +
         `(bir ic parca kendini iceren parcadan sonra kesiliyor).</span>`;
  info.innerHTML = m;
}

// blok listesi + SVG cizimi + ihlal denetimi
async function ciz(zorla) {
  if (!zorla && !document.getElementById("canli").checked) return;
  const dv = await api("/api/gcode/dogrula", { yol: GC.yol, sira: GC.sira });
  const ihlalPoz = new Set();
  (dv.ihlaller || []).forEach(([a, b]) => { ihlalPoz.add(a); ihlalPoz.add(b); });
  cizListe(ihlalPoz);
  cizSvg();
  const info = document.getElementById("gcInfo");
  if (dv.ihlaller && dv.ihlaller.length)
    info.innerHTML = `<span class='hata'>${dv.ihlaller.length} icerme ihlali` +
      ` — kirmizi bloklar: ic parca disindan sonra kesiliyor. 'Auto' ile ` +
      `duzeltebilirsiniz.</span>`;
  else
    info.innerHTML = "<span class='ok'>Icerme kurali saglaniyor: " +
      "en icteki parcalar once kesiliyor.</span>";
}

function blokById(id) { return GC.bloklar.find(b => b.id === id); }

function cizListe(ihlalPoz) {
  const kap = document.getElementById("blokListe");
  kap.innerHTML = "";
  GC.sira.forEach((id, poz) => {
    const b = blokById(id);
    const d = document.createElement("div");
    d.className = "blok" + (ihlalPoz.has(poz + 1) ? " ihlal" : "");
    d.draggable = true;
    d.dataset.poz = poz;
    d.innerHTML =
      `<div class="no">${poz + 1}</div>` +
      `<div><div>X ${b.x.toFixed(1)} &nbsp; Y ${b.y.toFixed(1)}</div>` +
      `<div class="xy">derinlik ${b.derinlik} · ${b.satir} satir</div></div>` +
      `<div style="margin-left:auto" class="rozet">` +
      (b.derinlik > 0 ? "ic (" + b.derinlik + ")" : "dis") + `</div>`;
    // surukle-birak
    d.ondragstart = e => e.dataTransfer.setData("poz", poz);
    d.ondragover = e => e.preventDefault();
    d.ondrop = e => { e.preventDefault();
      const k = parseInt(e.dataTransfer.getData("poz"));
      if (!isNaN(k) && k !== poz) tasi(k, poz); };
    kap.appendChild(d);
  });
}

function cizSvg() {
  const svg = document.getElementById("svgGcode");
  svgKur(svg);
  const W = svg.clientWidth || 600, H = svg.clientHeight || 420;
  const polys = GC.sira.map(id => blokById(id).poligon).filter(p => p.length);
  const bbox = tumBbox(polys);
  const T = fitDonusum(bbox, W, H, 30);
  // konturlar
  GC.sira.forEach(id => {
    const b = blokById(id);
    if (b.poligon.length < 2) return;
    const d = b.poligon.map((p, i) => {
      const [px, py] = T(p[0], p[1]);
      return (i ? "L" : "M") + px.toFixed(1) + " " + py.toFixed(1);
    }).join(" ");
    ekle(svg, "path", { d, fill: "none", stroke: "#3a4560",
      "stroke-width": 1 });
  });
  // ok tanimlari
  const defs = ekle(svg, "defs", {});
  defs.innerHTML = `<marker id="ok" markerWidth="8" markerHeight="8" refX="6"
    refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#5b8def"/></marker>`;
  // merkezler
  const merkez = id => {
    const b = blokById(id);
    if (b.poligon.length) {
      let sx = 0, sy = 0; b.poligon.forEach(p => { sx += p[0]; sy += p[1]; });
      return T(sx / b.poligon.length, sy / b.poligon.length);
    }
    return T(b.x, b.y);
  };
  // tasima oklari
  for (let i = 0; i < GC.sira.length - 1; i++) {
    const [x1, y1] = merkez(GC.sira[i]), [x2, y2] = merkez(GC.sira[i + 1]);
    ekle(svg, "line", { x1, y1, x2, y2, stroke: "#5b8def",
      "stroke-width": 1, opacity: .55, "marker-end": "url(#ok)" });
  }
  // numaralar
  GC.sira.forEach((id, poz) => {
    const [cx, cy] = merkez(id);
    ekle(svg, "circle", { cx, cy, r: 11, fill: "#171d2b",
      stroke: poz === 0 ? "#22c55e" : (poz === GC.sira.length - 1 ? "#a855f7"
        : "#ef4444"), "stroke-width": 2 });
    const t = ekle(svg, "text", { x: cx, y: cy + 4, "text-anchor": "middle",
      "font-size": 11, fill: "#e6ebf5", "font-weight": 700 });
    t.textContent = poz + 1;
  });
}

// =====================================================================
// Klasor tarama + proje
// =====================================================================
async function tara() {
  const klasor = document.getElementById("klasor").value.trim() || ".";
  const s = await api("/api/scan", { klasor });
  const kap = document.getElementById("dosyaListe");
  kap.classList.remove("gizli");
  if (s.hata) { kap.innerHTML = "<div class='d hata'>" + s.hata + "</div>"; return; }
  if (!s.dosyalar.length) { kap.innerHTML = "<div class='d'>Dosya yok</div>"; return; }
  kap.innerHTML = "";
  s.dosyalar.forEach(f => {
    const d = document.createElement("div");
    d.className = "d";
    d.innerHTML = `<span class="rozet">${f.tur}</span> ${f.ad}`;
    d.onclick = () => {
      if (f.tur === "dxf") {
        document.getElementById("dxfYol").value = f.yol;
        document.querySelector('.tab[data-tab="dxf"]').click();
      } else {
        document.getElementById("gcYol").value = f.yol;
        document.querySelector('.tab[data-tab="gcode"]').click();
      }
    };
    kap.appendChild(d);
  });
  document.getElementById("pKlasor").value = s.klasor;
}

async function klasorIsle() {
  const durum = document.getElementById("pDurum");
  durum.textContent = "Isleniyor... (bu islem biraz surebilir)";
  const s = await api("/api/proje/klasor", {
    klasor: document.getElementById("pKlasor").value.trim(),
    proje_ad: document.getElementById("pAd").value.trim() || "proje",
    proje_kok: document.getElementById("pKok").value.trim() || null,
    onizleme: document.getElementById("pOnizleme").checked,
    opts: { gcode_mod: document.getElementById("pMod").value },
  });
  if (s.hata) { durum.innerHTML = "<span class='hata'>" + s.hata + "</span>"; return; }
  let m = `<span class='ok'>${s.sayi} dosya islendi.</span> Cikti: ${s.dizin}\n`;
  s.gunluk.forEach(g => {
    if (g.tur === "dxf")
      m += `\nDXF ${g.giris} → node -${g.silinen_node}, ` +
           `tasinan ${g.kaydirilan}, butunluk ${g.dogrulama ? "OK" : "UYARI"}`;
    else if (g.hata) m += `\nG-Code ${g.giris} → ${g.hata}`;
    else m += `\nG-Code ${g.giris} → ${g.blok} blok (${g.mod})`;
  });
  durum.textContent = "";
  durum.innerHTML = m.replace(/\n/g, "<br>");
}
