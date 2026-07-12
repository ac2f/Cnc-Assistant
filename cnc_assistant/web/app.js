"use strict";
// CNC-Assistant — tarayici mantigi (bagimliliksiz vanilla JS)

const SVGNS = "http://www.w3.org/2000/svg";
const IK_KLASOR = '<svg class="ik" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';
const IK_DOSYA = '<svg class="ik" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M6 2h8l6 6v14a0 0 0 0 1 0 0H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><path d="M14 2v6h6"/></svg>';

async function api(uc, veri) {
  const r = await fetch(uc, { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(veri || {}) });
  return r.json();
}
const $ = id => document.getElementById(id);

// ===================== ayar saklama (localStorage) =====================
const AYAR = {
  al(k, v) { try { const s = localStorage.getItem("cnc_" + k);
    return s === null ? v : JSON.parse(s); } catch (e) { return v; } },
  yaz(k, v) { try { localStorage.setItem("cnc_" + k, JSON.stringify(v)); } catch (e) {} },
};

// Onizleme gorsel ayarlari (kalici; bir sonraki optimizasyonda da ayni kalir).
const ONIZ_VARSAYILAN = { cizgi_kalinlik: 0.9, vektor_renk: "#1f77b4",
  riskli_renk: "#d62728", bas_renk: "#2ca02c", bas_boyut: 5, numara: false,
  numara_boyut: 6, izgara: true, format: "pdf" };
const onizAyarAl = () => Object.assign({}, ONIZ_VARSAYILAN, AYAR.al("onizAyar", {}));
const onizAyarYaz = o => AYAR.yaz("onizAyar", o);

// ===================== tema =====================
function temaUygula(t) { document.documentElement.setAttribute("data-tema", t); AYAR.yaz("tema", t); }
$("temaBtn").onclick = () => {
  const su = document.documentElement.getAttribute("data-tema")
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  temaUygula(su === "dark" ? "light" : "dark");
};
{ const t = AYAR.al("tema", null); if (t) temaUygula(t); }

// ===================== dosya gezgini =====================
let GZ = { yol: null, ev: null, cwd: null };
let SON_TARAMA = null;      // filtre icin son gozat sonucu
let ZIYARET = AYAR.al("ziyaret", []);   // ziyaret gecmisi (yeni -> eski)

async function gozat(yol) {
  const s = await api("/api/gozat", { yol });
  const g = $("gezgin");
  if (s.hata) { g.innerHTML = `<div class="oge">${s.hata}</div>`; return; }
  GZ = { yol: s.yol, ev: s.ev, cwd: s.cwd };
  SON_TARAMA = s;
  AYAR.yaz("sonKlasor", s.yol);
  // ziyaret gecmisine ekle (en son girilen klasoru izlemek icin)
  ZIYARET = [s.yol, ...ZIYARET.filter(z => z !== s.yol)].slice(0, 80);
  AYAR.yaz("ziyaret", ZIYARET);
  $("pKlasor").value = s.yol;
  $("ara").value = "";
  // yol cubugu (breadcrumb)
  const yc = $("yolCubugu"); yc.innerHTML = "";
  const parcalar = s.yol.split("/").filter(Boolean);
  let birik = s.yol.startsWith("/") ? "" : ".";
  const kokP = document.createElement("span"); kokP.className = "p";
  kokP.textContent = "/"; kokP.onclick = () => gozat("/"); yc.appendChild(kokP);
  parcalar.forEach(p => {
    birik += "/" + p;
    const yolu = birik;
    const e = document.createElement("span"); e.className = "p"; e.textContent = p;
    e.onclick = () => gozat(yolu); yc.appendChild(e);
    yc.appendChild(document.createTextNode("›"));
  });
  gezginCiz(s, "");
}

// Siralama karsilastiricisi
function siralayici(mod) {
  const ad = (a, b) => a.ad.toLowerCase().localeCompare(b.ad.toLowerCase());
  switch (mod) {
    case "eski": return (a, b) => (a.mtime || 0) - (b.mtime || 0);
    case "ad": return ad;
    case "ad_ters": return (a, b) => ad(b, a);
    case "tur": return (a, b) => ((a.tur || "") + a.ad).localeCompare((b.tur || "") + b.ad);
    case "boyut": return (a, b) => (b.bayt || 0) - (a.bayt || 0);
    default: return (a, b) => (b.mtime || 0) - (a.mtime || 0);   // yeni
  }
}
// "en son girilen" klasoru bul (ziyaret gecmisinde en yeni, mevcut disi, gorunur)
function sonZiyaretYolu(klasorler) {
  const yollar = new Set(klasorler.map(k => k.yol));
  for (const z of ZIYARET) if (z !== GZ.yol && yollar.has(z)) return z;
  return null;
}

// Filtrelenebilir + siralanabilir gezgin listesi (NOT: her zaman appendChild kullan;
// innerHTML += tiklama olaylarini siler ve boş klasorde ".." tiklanamaz hale gelirdi)
function gezginCiz(s, filtre) {
  const g = $("gezgin"); g.innerHTML = "";
  const f = (filtre || "").toLowerCase();
  const uyar = a => !f || a.toLowerCase().includes(f);
  const cmp = siralayici($("sirala").value);
  const sonZ = sonZiyaretYolu(s.klasorler);

  if (s.ust && !f) {
    const u = oge(IK_KLASOR, "..", "", "klasor ust"); u.onclick = () => gozat(s.ust);
    g.appendChild(u);
  }
  s.klasorler.filter(k => uyar(k.ad)).sort(cmp).forEach(k => {
    const sinif = "klasor" + (k.yol === sonZ ? " son-ziyaret" : "");
    const e = oge(IK_KLASOR, k.ad, sayimRozet(k), sinif);
    // yeniden adlandir / sil eylemleri
    const islem = document.createElement("span"); islem.className = "islem";
    islem.innerHTML = `<button title="Yeniden adlandir">✎</button>
      <button class="sil" title="Sil">🗑</button>`;
    islem.children[0].onclick = ev => { ev.stopPropagation(); klasorYenidenAdlandir(k); };
    islem.children[1].onclick = ev => { ev.stopPropagation(); klasorSil(k); };
    e.appendChild(islem);
    e.onclick = () => gozat(k.yol);
    g.appendChild(e);
  });
  s.dosyalar.filter(x => uyar(x.ad)).sort(cmp).forEach(x => {
    const e = oge(IK_DOSYA, x.ad, `<span class="rozet">${x.tur}</span>`);
    e.onclick = () => dosyaAc(x); g.appendChild(e);
  });
  if (!g.children.length) {
    const bos = document.createElement("div");
    bos.className = "oge"; bos.style.color = "var(--metin2)";
    bos.style.cursor = "default";
    bos.textContent = f ? "Eslesme yok" : "Bu klasorde DXF/G-Code yok";
    g.appendChild(bos);
  }
}
$("ara").oninput = e => { if (SON_TARAMA) gezginCiz(SON_TARAMA, e.target.value); };
$("sirala").value = AYAR.al("siralama", "yeni");
$("sirala").onchange = e => { AYAR.yaz("siralama", e.target.value);
  if (SON_TARAMA) gezginCiz(SON_TARAMA, $("ara").value); };
// Alt klasor icerik sayaci: magenta T{gcode} (toolpath), sari V{dxf} (vektor).
// Icinde yoksa bos birakilir.
function sayimRozet(k) {
  if (k.gcode == null && k.dxf == null) return "";  // sayim yapilmadi (limit)
  let s = "";
  if (k.gcode) s += `<span class="say t">T${k.gcode}</span>`;
  if (k.dxf)   s += `<span class="say v">V${k.dxf}</span>`;
  return s ? `<span class="saylar">${s}</span>` : "";
}
function oge(ik, isim, sag, sinif) {
  const d = document.createElement("div");
  d.className = "oge" + (sinif ? " " + sinif : "");
  d.innerHTML = ik + `<span class="isim">${isim}</span>` + (sag || "");
  return d;
}
document.querySelectorAll(".mini[data-git]").forEach(b => b.onclick = () =>
  gozat(b.dataset.git === "ev" ? GZ.ev : GZ.cwd));

// --- klasor islemleri ---
$("yeniKlasorBtn").onclick = async () => {
  const ad = prompt("Yeni klasor adi:", "yeni_klasor");
  if (!ad) return;
  const r = await api("/api/klasor/olustur", { yol: GZ.yol, ad });
  if (r.hata) { bildir(r.hata, true); return; }
  bildir("Klasor olusturuldu"); gozat(GZ.yol);
};
async function klasorYenidenAdlandir(k) {
  const yeni = prompt("Yeni ad:", k.ad);
  if (!yeni || yeni === k.ad) return;
  const r = await api("/api/yeniden_adlandir", { yol: k.yol, yeni_ad: yeni });
  if (r.hata) { bildir(r.hata, true); return; }
  bildir("Yeniden adlandirildi"); gozat(GZ.yol);
}
async function klasorSil(k) {
  const say = (k.dxf || 0) + (k.gcode || 0);
  const msg = say ? `"${k.ad}" ve icindeki ${say}+ dosya SILINSIN mi? Geri alinamaz!`
                  : `"${k.ad}" klasoru silinsin mi?`;
  if (!confirm(msg)) return;
  const r = await api("/api/klasor/sil", { yol: k.yol });
  if (r.hata) { bildir(r.hata, true); return; }
  bildir("Silindi"); gozat(GZ.yol);
}
$("tumDxfBtn").onclick = async () => {
  const s = await api("/api/gozat", { yol: GZ.yol });
  (s.dosyalar || []).filter(f => f.tur === "dxf").forEach(dosyaAc);
};

// ===================== belge (sekme) yonetimi =====================
let DOCS = [];      // {id, yol, ad, tur, durum, ...}
let AKTIF = null;
let sayac = 0;

function dosyaAc(f) {
  const varsa = DOCS.find(d => d.yol === f.yol);
  if (varsa) { AKTIF = varsa.id; render(); return; }
  const doc = { id: ++sayac, yol: f.yol, ad: f.ad, tur: f.tur, durum: "yeni" };
  if (f.tur === "dxf") {
    doc.params = Object.assign(
      { destek: "sol-ust", node_tol: 1e-6, node_temiz: true },
      AYAR.al("dxfParams", {}));
    doc.onizGecmis = []; doc.onizAktif = -1;
  }
  DOCS.push(doc); AKTIF = doc.id; render();
  yukle(doc);
}
function docKapat(id, ev) {
  ev.stopPropagation();
  const i = DOCS.findIndex(d => d.id === id);
  DOCS.splice(i, 1);
  if (AKTIF === id) AKTIF = DOCS.length ? DOCS[Math.max(0, i - 1)].id : null;
  render();
}
function aktifDoc() { return DOCS.find(d => d.id === AKTIF); }

async function yukle(doc) {
  doc.durum = "yukleniyor"; render();
  if (doc.tur === "dxf") {
    const p = doc.params;
    doc.veri = await api("/api/dxf/onizle", { yol: doc.yol,
      destek_yonu: p.destek, node_tol: p.node_tol, node_temizle: p.node_temiz });
    if (!doc.veri.hata)
      onizEkle(doc, `${p.destek} · ${p.node_temiz ? "temiz" : "ham"}`);
  } else {
    const g = await api("/api/gcode/yukle", { yol: doc.yol });
    doc.veri = g;
    if (g.guvenli) doc.gc = { bloklar: g.bloklar, sira: g.onerilen_sira.slice(),
      tarih: [{ sira: g.onerilen_sira.slice(), etiket: "auto" }], aktif: 0,
      canli: true,
      tabAcik: AYAR.al("tabAcik", false), tabAdet: AYAR.al("tabAdet", 4),
      tablar: null };
  }
  doc.durum = "hazir";
  if (AKTIF === doc.id) render();
}

// ===================== render =====================
function render() {
  // sekmeler
  const sk = $("sekmeler"); sk.innerHTML = "";
  DOCS.forEach(d => {
    const t = document.createElement("div");
    t.className = "sekme" + (d.id === AKTIF ? " aktif" : "");
    t.onclick = () => { AKTIF = d.id; render(); };
    t.innerHTML = `<span class="nokta ${d.tur}"></span>` +
      `<span class="isim">${d.ad}</span>` +
      `<span class="kapat">×</span>`;
    t.querySelector(".kapat").onclick = e => docKapat(d.id, e);
    sk.appendChild(t);
  });
  // icerik
  const ic = $("icerik");
  const doc = aktifDoc();
  if (!doc) { ic.innerHTML = ""; ic.appendChild(bosDurum()); return; }
  if (doc.durum !== "hazir") {
    ic.innerHTML = `<div class="bos"><div class="yukleniyor"></div>
      <p style="margin-top:14px">${doc.ad} isleniyor…</p></div>`;
    return;
  }
  ic.innerHTML = "";
  ic.appendChild(doc.tur === "dxf" ? dxfIcerik(doc) : gcodeIcerik(doc));
  if (doc.tur === "dxf") dxfCiz(doc);
  else if (doc.gc) gcCiz(doc);
}
function bosDurum() {
  const d = document.createElement("div"); d.className = "bos";
  d.innerHTML = `<div class="bos-ikon">◇</div><h2>Bir dosya secin</h2>
    <p>Soldaki gezginden bir <b>.dxf</b> veya <b>G-Code</b> dosyasina tiklayin.</p>`;
  return d;
}

// ===================== DXF gorunumu =====================
function dxfIcerik(doc) {
  const v = doc.veri, p = doc.params;
  const el = document.createElement("div");
  if (v.hata) { el.innerHTML = `<div class="kart"><span class="uyari">${v.hata}</span></div>`; return el; }
  el.innerHTML = `
    <div class="kart">
      <div class="arac">
        <div class="grup"><label>Baslangic (kopma) destek yonu</label>
          <select class="alan" id="d_destek" style="width:170px">
            <option value="sol-ust">Sol-ust (onerilen)</option>
            <option value="ust">Orta-ust</option>
            <option value="sag-ust">Sag-ust</option>
          </select></div>
        <div class="grup"><label>Node toleransi</label>
          <input type="text" class="alan kk" id="d_tol" value="${p.node_tol}"></div>
        <label class="anahtar"><input type="checkbox" id="d_temiz" ${p.node_temiz?"checked":""}>
          <span class="kutu"></span> Node temizligi</label>
        <div style="flex:1"></div>
        <button class="dugme hayalet" id="d_ayarAc">Onizleme ayarlari ▾</button>
        <button class="dugme hayalet" id="d_yeniden">Yeniden Isle</button>
        <button class="dugme" id="d_kaydet">Optimize DXF'i Kaydet</button>
      </div>
      <div class="arac" id="d_onizAyar" style="margin-top:10px;flex-wrap:wrap;gap:14px;display:none">
        <div class="grup"><label>Vektor cizgi genisligi</label>
          <input type="number" step="0.1" min="0.1" class="alan kk" id="oz_cizgi"></div>
        <div class="grup"><label>Vektor rengi</label>
          <input type="color" class="alan kk" id="oz_vrenk" style="width:52px;padding:2px"></div>
        <div class="grup"><label>Riskli vektor rengi</label>
          <input type="color" class="alan kk" id="oz_rrenk" style="width:52px;padding:2px"></div>
        <div class="grup"><label>Baslangic noktasi rengi</label>
          <input type="color" class="alan kk" id="oz_brenk" style="width:52px;padding:2px"></div>
        <div class="grup"><label>Baslangic noktasi boyutu</label>
          <input type="number" step="0.5" min="1" class="alan kk" id="oz_bboyut"></div>
        <label class="anahtar"><input type="checkbox" id="oz_numara">
          <span class="kutu"></span> Parca numaralari</label>
        <div class="grup"><label>Numara boyutu</label>
          <input type="number" step="0.5" min="2" class="alan kk" id="oz_nboyut"></div>
        <label class="anahtar"><input type="checkbox" id="oz_izgara">
          <span class="kutu"></span> Izgara</label>
      </div>
      <div class="arac" id="d_indirSatir" style="margin-top:8px;align-items:center;gap:10px">
        <div class="grup"><label>Indirme formati</label>
          <select class="alan kk" id="oz_format" style="width:90px">
            <option value="pdf">PDF</option><option value="png">PNG</option>
            <option value="svg">SVG</option></select></div>
        <span style="opacity:.7;font-size:13px">Indir:</span>
        <button class="dugme hayalet" id="d_ind_once">Oncesi</button>
        <button class="dugme hayalet" id="d_ind_sonra">Sonrasi</button>
        <button class="dugme" id="d_ind_birlikte">Birlikte</button>
        <div style="flex:1"></div>
      </div>
      <div class="arac" style="margin-top:12px;align-items:center">
        <div class="grup"><label>Nesting tabaka genisligi (0 = otomatik)</label>
          <input type="text" class="alan kk" id="d_tabaka" value="0"></div>
        <div class="grup"><label>Parca araligi</label>
          <input type="text" class="alan kk" id="d_bosluk" value="5"></div>
        <button class="dugme hayalet" id="d_nest">Yerlestir (Nesting)</button>
        <div class="birim-cip" id="d_nestbilgi" style="display:none"></div>
      </div>
      <div class="cipler">
        <div class="cip">Tasinan baslangic<b>${v.kaydirilan}</b></div>
        <div class="cip">Kaldirilan gereksiz node<b>${v.silinen_node}</b></div>
        <div class="cip">Cember→polyline<b>${v.cember}</b></div>
        <div class="cip">Riskli parca<b>${v.riskli.length}</b></div>
        <div class="cip ${v.dogrulama?'ok':'uyari'}">Butunluk<b>${v.dogrulama?'birebir':'UYARI'}</b></div>
      </div>
      <div class="durum" id="d_durum"></div>
    </div>
    <div class="kart">
      <div class="paneller">
        <div class="panel"><div class="pbaslik"><span>ONCESI — orijinal baslangic</span></div>
          <svg class="tuval" id="svgOnce"></svg></div>
        <div class="panel"><div class="pbaslik"><span>SONRASI — optimize</span></div>
          <svg class="tuval" id="svgSonra"></svg>
          <div class="aciklama"><span><i style="background:#34c759"></i>Yeni baslangic</span>
            <span><i style="background:#ff3b30"></i>Riskli parca (hold-down)</span></div></div>
      </div>
      <div class="zoom-ipuc">Tekerlek: yaklas/uzaklas · surukle: kaydir · cift tik: sifirla</div>
      <div class="gecmis-serit" id="d_gecmis"></div>
    </div>`;
  // olaylar
  const kaydetP = () => AYAR.yaz("dxfParams", p);
  setTimeout(() => {
    $("d_destek").value = p.destek || "sol-ust";
    $("d_destek").onchange = e => { p.destek = e.target.value; kaydetP(); yukle(doc); };
    $("d_tol").onchange = e => { p.node_tol = parseFloat(e.target.value) || 1e-6; kaydetP(); };
    $("d_temiz").onchange = e => { p.node_temiz = e.target.checked; kaydetP(); };
    $("d_yeniden").onclick = () => yukle(doc);
    // --- Onizleme ayarlari (kalici: localStorage 'onizAyar') ---
    const oz = onizAyarAl();
    $("oz_cizgi").value = oz.cizgi_kalinlik; $("oz_vrenk").value = oz.vektor_renk;
    $("oz_rrenk").value = oz.riskli_renk;    $("oz_brenk").value = oz.bas_renk;
    $("oz_bboyut").value = oz.bas_boyut;     $("oz_numara").checked = oz.numara;
    $("oz_nboyut").value = oz.numara_boyut;  $("oz_izgara").checked = oz.izgara;
    $("oz_format").value = oz.format;
    const ozKaydet = () => onizAyarYaz({
      cizgi_kalinlik: parseFloat($("oz_cizgi").value) || 0.9,
      vektor_renk: $("oz_vrenk").value, riskli_renk: $("oz_rrenk").value,
      bas_renk: $("oz_brenk").value, bas_boyut: parseFloat($("oz_bboyut").value) || 5,
      numara: $("oz_numara").checked, numara_boyut: parseFloat($("oz_nboyut").value) || 6,
      izgara: $("oz_izgara").checked, format: $("oz_format").value });
    ["oz_cizgi","oz_vrenk","oz_rrenk","oz_brenk","oz_bboyut","oz_numara",
     "oz_nboyut","oz_izgara","oz_format"].forEach(id =>
      $(id).addEventListener("change", ozKaydet));
    $("d_ayarAc").onclick = () => {
      const g = $("d_onizAyar"); const acik = g.style.display !== "none";
      g.style.display = acik ? "none" : "flex";
      $("d_ayarAc").textContent = acik ? "Onizleme ayarlari ▾" : "Onizleme ayarlari ▴";
    };
    const onizIndir = async (panel) => {
      const o = onizAyarAl();
      $("d_durum").innerHTML = `<span class="yukleniyor"></span> Onizleme uretiliyor…`;
      const r = await api("/api/dxf/onizleme", { yol: doc.yol, destek_yonu: p.destek,
        node_tol: p.node_tol, node_temizle: p.node_temiz, paneller: panel, format: o.format,
        stil: { cizgi_kalinlik: o.cizgi_kalinlik, vektor_renk: o.vektor_renk,
          riskli_renk: o.riskli_renk, bas_renk: o.bas_renk, bas_boyut: o.bas_boyut,
          numara: o.numara, numara_boyut: o.numara_boyut, izgara: o.izgara } });
      if (r.hata) { $("d_durum").innerHTML = `<span class="uyari">${r.hata}</span>`; return; }
      $("d_durum").innerHTML = `<span class="ok">Hazir:</span> ${r.dosya} — indiriliyor…`;
      window.location.href = r.indir;
    };
    $("d_ind_once").onclick = () => onizIndir("oncesi");
    $("d_ind_sonra").onclick = () => onizIndir("sonrasi");
    $("d_ind_birlikte").onclick = () => onizIndir("birlikte");
    $("d_kaydet").onclick = async () => {
      const r = await api("/api/dxf/kaydet", { yol: doc.yol });
      $("d_durum").innerHTML = r.hata ? `<span class="uyari">${r.hata}</span>`
        : `<span class="ok">Kaydedildi:</span> ${r.cikti}`;
    };
    $("d_nest").onclick = async () => {
      $("d_durum").innerHTML = `<span class="yukleniyor"></span> Yerlestiriliyor…`;
      const r = await api("/api/dxf/nest", { yol: doc.yol,
        tabaka_genislik: parseFloat($("d_tabaka").value) || 0,
        bosluk: parseFloat($("d_bosluk").value) || 5 });
      if (r.hata) { $("d_durum").innerHTML = `<span class="uyari">${r.hata}</span>`; return; }
      doc.veri = Object.assign({}, doc.veri,
        { oncesi: r.oncesi, sonrasi: r.sonrasi, riskli_handlelar: [] });
      onizEkle(doc, `nesting (${r.parca_sayisi})`);
      dxfCiz(doc);
      $("d_nestbilgi").style.display = "inline-block";
      $("d_nestbilgi").textContent =
        `${r.parca_sayisi} parca · tabaka ${r.tabaka[0].toFixed(0)}×${r.tabaka[1].toFixed(0)} · cevre ${r.cevre_korundu?'korundu':'UYARI'}`;
      $("d_durum").innerHTML = `<span class="ok">Yerlestirildi:</span> ${r.cikti}`;
    };
  }, 0);
  return el;
}

function dxfCiz(doc) {
  const v = doc.veri; if (v.hata) return;
  cizVarliklar("svgOnce", v.oncesi, [], true);
  cizVarliklar("svgSonra", v.sonrasi, v.riskli_handlelar, true);
  dxfGecmisCiz(doc);
}

// DXF onizleme gecmisi (her "Yeniden Isle" / "Nesting" bir adim ekler)
function onizEkle(doc, etiket) {
  doc.onizGecmis = (doc.onizGecmis || []).slice(0, (doc.onizAktif ?? -1) + 1);
  doc.onizGecmis.push({ etiket, veri: doc.veri });
  if (doc.onizGecmis.length > 14) doc.onizGecmis.shift();
  doc.onizAktif = doc.onizGecmis.length - 1;
}
function dxfGecmiseGit(doc, i) {
  if (i < 0 || i >= doc.onizGecmis.length) return;
  doc.onizAktif = i; doc.veri = doc.onizGecmis[i].veri;
  render();     // icerigi (istatistik cipleri dahil) yeniden kur + ciz
}
function dxfGecmisCiz(doc) {
  const kap = $("d_gecmis"); if (!kap || !doc.onizGecmis) return;
  kap.innerHTML = `<span class="baslik">Onizleme gecmisi</span>`;
  doc.onizGecmis.forEach((t, i) => {
    const d = document.createElement("div");
    d.className = "gadim" + (i === doc.onizAktif ? " aktif" : "");
    d.innerHTML = `${i + 1}<span class="kk2">${t.etiket}</span>`;
    d.onclick = () => dxfGecmiseGit(doc, i);
    kap.appendChild(d);
  });
}

// ===================== G-Code gorunumu =====================
function gcodeIcerik(doc) {
  const el = document.createElement("div");
  const g = doc.veri;
  if (g.hata) { el.innerHTML = `<div class="kart"><span class="uyari">${g.hata}</span></div>`; return el; }
  if (!g.guvenli) {
    el.innerHTML = `<div class="kart"><span class="uyari">${(g.uyarilar||[]).join(" ")}</span></div>`;
    return el;
  }
  el.innerHTML = `
    <div class="kart">
      <div class="gc-arac">
        <button class="dugme hayalet kucuk" data-mod="sol-alt">Auto (sol-alt→sag-ust)</button>
        <button class="dugme hayalet kucuk" data-mod="serpantin">Serpantin</button>
        <button class="dugme hayalet kucuk" data-mod="engel">Engel-farkindalik</button>
        <span class="ayrac"></span>
        <input type="text" class="alan kk" id="g_swap" placeholder="59 60">
        <button class="dugme hayalet kucuk" id="g_swapb">Yer degistir</button>
        <button class="dugme hayalet kucuk" id="g_geri">↶</button>
        <button class="dugme hayalet kucuk" id="g_ileri">↷</button>
        <span class="ayrac"></span>
        <label class="anahtar"><input type="checkbox" id="g_canli" ${doc.gc.canli?"checked":""}>
          <span class="kutu"></span> Canli onizleme</label>
        <span class="ayrac"></span>
        <label class="anahtar"><input type="checkbox" id="g_tab" ${doc.gc.tabAcik?"checked":""}>
          <span class="kutu"></span> Koprü</label>
        <input type="text" class="alan kk" id="g_tabadet" value="${doc.gc.tabAdet||4}"
               title="Kontur basina koprü sayisi" style="width:52px">
        <button class="dugme hayalet kucuk" id="g_goster">Goster</button>
        <div style="flex:1"></div>
        <span class="birim-cip">${g.birim ? g.birim : "birim?"}</span>
        <button class="dugme" id="g_kaydet">Kaydet (.tap)</button>
      </div>
      <div class="cipler" id="g_karsilastir"></div>
      <div class="gc-govde">
        <div>
          <div class="pbaslik" style="margin-bottom:8px">Kesim sirasi — surukleyerek tasi</div>
          <div class="liste" id="g_liste"></div>
        </div>
        <div>
          <div class="pbaslik" style="margin-bottom:8px">Sira onizleme — numara=sira, ok=tasima</div>
          <svg class="tuval" id="svgGc"></svg>
          <div class="zoom-ipuc">Tekerlek: yaklas/uzaklas · surukle: kaydir · cift tik: sifirla</div>
          <div class="durum" id="g_durum"></div>
          <div class="gecmis-serit" id="g_gecmis"></div>
        </div>
      </div>
    </div>`;
  setTimeout(() => {
    el.querySelectorAll("[data-mod]").forEach(b =>
      b.onclick = () => gcSirala(doc, b.dataset.mod));
    $("g_swapb").onclick = () => gcSwap(doc);
    $("g_swap").onkeydown = e => { if (e.key === "Enter") gcSwap(doc); };
    $("g_geri").onclick = () => { gcGeri(doc); };
    $("g_ileri").onclick = () => { gcIleri(doc); };
    $("g_canli").onchange = e => { doc.gc.canli = e.target.checked; if (e.target.checked) gcCiz(doc); };
    $("g_tab").onchange = async e => { doc.gc.tabAcik = e.target.checked;
      AYAR.yaz("tabAcik", e.target.checked); await gcTablariGetir(doc); gcCiz(doc, true); };
    $("g_tabadet").onchange = async e => { doc.gc.tabAdet = parseInt(e.target.value) || 4;
      AYAR.yaz("tabAdet", doc.gc.tabAdet); if (doc.gc.tabAcik) { await gcTablariGetir(doc); gcCiz(doc, true); } };
    $("g_goster").onclick = () => gcCiz(doc, true);
    $("g_kaydet").onclick = () => gcKaydet(doc);
    gcKarsilastirCiz(doc);
    gcGecmisCiz(doc);
  }, 0);
  return el;
}

// boşta-yol karsilastirma cipleri (en iyi vurgulanir, tiklayinca uygular)
function gcKarsilastirCiz(doc) {
  const kap = $("g_karsilastir"); if (!kap) return;
  const k = doc.veri.karsilastir; if (!k || !k.modlar) { kap.innerHTML = ""; return; }
  const adlar = { "sol-alt": "Sol-alt→sağ-üst", "serpantin": "Serpantin", "engel": "Engel" };
  const birim = k.birim || "";
  kap.innerHTML = `<div class="cip">Boşta yol (kısa = iyi)</div>` +
    Object.keys(k.modlar).map(m =>
      `<div class="cip mod-cip ${m===k.en_iyi?'eniyi':''}" data-mod="${m}">${adlar[m]}
        <b>${k.modlar[m].toFixed(1)} ${birim}</b></div>`).join("");
  kap.querySelectorAll(".mod-cip").forEach(c =>
    c.onclick = () => gcSirala(doc, c.dataset.mod));
}

async function gcTablariGetir(doc) {
  if (!doc.gc.tabAcik) { doc.gc.tablar = null; return; }
  const r = await api("/api/gcode/tablar", { yol: doc.yol, sira: doc.gc.sira,
    adet: doc.gc.tabAdet || 4 });
  doc.gc.tablar = r.tablar || null;
}

// Lineer, tiklanabilir gecmis: her adim tarih dizisine yazilir; aktif indeks
// gezinir (geri/ileri veya serit uzerinde tiklayarak).
function gcAdimEkle(doc, yeniSira, etiket) {
  doc.gc.sira = yeniSira.slice();
  doc.gc.tarih = doc.gc.tarih.slice(0, doc.gc.aktif + 1);
  doc.gc.tarih.push({ sira: yeniSira.slice(), etiket });
  doc.gc.aktif = doc.gc.tarih.length - 1;
  gcCiz(doc); gcGecmisCiz(doc);
}
function gcGit(doc, i) {
  if (i < 0 || i >= doc.gc.tarih.length) return;
  doc.gc.aktif = i; doc.gc.sira = doc.gc.tarih[i].sira.slice();
  gcCiz(doc); gcGecmisCiz(doc);
}
async function gcSirala(doc, mod) {
  const s = await api("/api/gcode/sirala", { yol: doc.yol, mod });
  if (s.hata) return;
  const ad = { "sol-alt": "auto", "serpantin": "serpantin", "engel": "engel" }[mod] || mod;
  gcAdimEkle(doc, s.sira, ad);
}
function gcSwap(doc) {
  const g = $("g_swap").value.trim().split(/\s+/);
  const i = parseInt(g[0]) - 1, j = parseInt(g[1]) - 1, n = doc.gc.sira.length;
  if (isNaN(i) || isNaN(j) || i < 0 || j < 0 || i >= n || j >= n) return;
  const a = doc.gc.sira.slice(); [a[i], a[j]] = [a[j], a[i]];
  $("g_swap").value = ""; gcAdimEkle(doc, a, `${i + 1}↔${j + 1}`);
}
function gcTasi(doc, k, h) {
  const a = doc.gc.sira.slice(); const [b] = a.splice(k, 1); a.splice(h, 0, b);
  gcAdimEkle(doc, a, `taşı ${k + 1}→${h + 1}`);
}
function gcGeri(doc) { if (doc.gc.aktif > 0) gcGit(doc, doc.gc.aktif - 1); }
function gcIleri(doc) { if (doc.gc.aktif < doc.gc.tarih.length - 1) gcGit(doc, doc.gc.aktif + 1); }

// gecmis seridi
function gcGecmisCiz(doc) {
  const kap = $("g_gecmis"); if (!kap) return;
  kap.innerHTML = `<span class="baslik">Onizleme gecmisi</span>`;
  doc.gc.tarih.forEach((t, i) => {
    const d = document.createElement("div");
    d.className = "gadim" + (i === doc.gc.aktif ? " aktif" : "");
    d.innerHTML = `${i + 1}<span class="kk2">${t.etiket}</span>`;
    d.onclick = () => gcGit(doc, i);
    kap.appendChild(d);
  });
}

async function gcKaydet(doc) {
  const s = await api("/api/gcode/kaydet", { yol: doc.yol, sira: doc.gc.sira });
  const d = $("g_durum");
  if (s.hata) { d.innerHTML = `<span class="uyari">${s.hata}</span>`; return; }
  let m = `<span class="ok">Kaydedildi:</span> ${s.cikti} · bosta yol: <b>${s.bosta_yol.toFixed(1)}</b>`;
  if (s.ihlaller && s.ihlaller.length)
    m += `<br><span class="uyari">UYARI: ${s.ihlaller.length} icerme ihlali.</span>`;
  d.innerHTML = m;
}

async function gcCiz(doc, zorla) {
  if (!zorla && !doc.gc.canli) return;
  if (doc.gc.tabAcik) await gcTablariGetir(doc);   // sira ile hizali tut
  const dv = await api("/api/gcode/dogrula", { yol: doc.yol, sira: doc.gc.sira });
  const ihl = new Set(); (dv.ihlaller || []).forEach(([a, b]) => { ihl.add(a); ihl.add(b); });
  gcListe(doc, ihl); gcSvg(doc);
  const d = $("g_durum"); if (!d) return;
  d.innerHTML = (dv.ihlaller && dv.ihlaller.length)
    ? `<span class="uyari">${dv.ihlaller.length} icerme ihlali — kirmizi bloklar ic parca disindan sonra kesiliyor. 'Auto' ile duzeltin.</span>`
    : `<span class="ok">Icerme kurali saglaniyor: en icteki once kesiliyor.</span>`;
}
const blokById = (doc, id) => doc.gc.bloklar.find(b => b.id === id);
function gcListe(doc, ihl) {
  const kap = $("g_liste"); if (!kap) return; kap.innerHTML = "";
  doc.gc.sira.forEach((id, poz) => {
    const b = blokById(doc, id);
    const d = document.createElement("div");
    d.className = "blok" + (ihl.has(poz + 1) ? " ihlal" : "");
    d.draggable = true;
    d.innerHTML = `<div class="no">${poz + 1}</div>
      <div><div class="bx">X ${b.x.toFixed(1)}  Y ${b.y.toFixed(1)}</div>
      <div class="by">derinlik ${b.derinlik} · ${b.satir} satir</div></div>
      <div class="etk ${b.derinlik>0?'ic':''}">${b.derinlik>0?'ic ('+b.derinlik+')':'dis'}</div>`;
    d.ondragstart = e => { e.dataTransfer.setData("k", poz); d.classList.add("suru"); };
    d.ondragend = () => d.classList.remove("suru");
    d.ondragover = e => e.preventDefault();
    d.ondrop = e => { e.preventDefault(); const k = +e.dataTransfer.getData("k");
      if (!isNaN(k) && k !== poz) gcTasi(doc, k, poz); };
    kap.appendChild(d);
  });
}
function gcSvg(doc) {
  const svg = $("svgGc"); if (!svg) return; svgKur(svg);
  const W = svg.clientWidth || 600, H = svg.clientHeight || 440;
  const tum = [];
  doc.gc.sira.forEach(id => komutKoords(blokById(doc, id).komut || []).forEach(p => tum.push(p)));
  const T = fitDonusum(tumBbox([tum]), W, H, 34);
  izgara(svg, W, H);
  // kontur yollari (vektorel; yaylar egri, non-scaling-stroke)
  doc.gc.sira.forEach(id => {
    const b = blokById(doc, id); if (!b.komut || b.komut.length < 2) return;
    ekle(svg, "path", { d: komutYol(b.komut, T), fill: "none",
      stroke: "var(--cizgi)", "stroke-width": 1.4, "vector-effect": "non-scaling-stroke" });
  });
  const defs = ekle(svg, "defs", {});
  defs.innerHTML = `<marker id="ok" markerWidth="7" markerHeight="7" refX="5" refY="3"
    orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L6,3 L0,6 Z" fill="var(--acc)"/></marker>`;
  const merkez = id => { const b = blokById(doc, id);
    return b.merkez ? T(b.merkez[0], b.merkez[1]) : T(b.x, b.y); };
  for (let i = 0; i < doc.gc.sira.length - 1; i++) {
    const [x1, y1] = merkez(doc.gc.sira[i]), [x2, y2] = merkez(doc.gc.sira[i + 1]);
    ekle(svg, "line", { x1, y1, x2, y2, stroke: "var(--acc)", "stroke-width": 1.3,
      opacity: .5, "vector-effect": "non-scaling-stroke", "marker-end": "url(#ok)" });
  }
  // koprü (tab) isaretleri
  if (doc.gc.tabAcik && doc.gc.tablar) {
    doc.gc.tablar.forEach(liste => (liste || []).forEach(([x, y]) => {
      const [px, py] = T(x, y);
      ekle(svg, "circle", { cx: px, cy: py, r: 4, "data-baser": 4, class: "tab-nokta" });
    }));
  }
  doc.gc.sira.forEach((id, poz) => {
    const [cx, cy] = merkez(id);
    const renk = poz === 0 ? "#34c759" : (poz === doc.gc.sira.length - 1 ? "#af52de" : "#ff3b30");
    ekle(svg, "circle", { cx, cy, r: 12, "data-baser": 12, fill: "var(--yuzey)",
      stroke: renk, "stroke-width": 2.2, "vector-effect": "non-scaling-stroke" });
    const t = ekle(svg, "text", { x: cx, y: cy + 4, "text-anchor": "middle",
      "font-size": 11, "data-basefs": 11, fill: "var(--metin)", "font-weight": 700 });
    t.textContent = poz + 1;
  });
  zoomEtkinlestir(svg);
}

// ===================== SVG yardimcilari =====================
function svgKur(svg){ while (svg.firstChild) svg.removeChild(svg.firstChild); }

// Tekerlekle yaklastir/uzaklastir + surukleyerek kaydir + cift tik sifirla.
// Icerik piksel uzayinda (0..W, 0..H) cizilir; viewBox degistirilerek zoom yapilir.
function zoomEtkinlestir(svg) {
  const W = svg.clientWidth || 600, H = svg.clientHeight || 440;
  if (!svg._vb) svg._vb = [0, 0, W, H];
  const uygula = () => {
    svg.setAttribute("viewBox", svg._vb.join(" "));
    // Nokta/yazi isaretlerini ekran-sabit boyutta tut (cizgiler zaten
    // vector-effect:non-scaling-stroke ile sabit). s = veri-birim / ekran-piksel
    const s = svg._vb[2] / W;
    svg.querySelectorAll("[data-baser]").forEach(el =>
      el.setAttribute("r", (parseFloat(el.dataset.baser) * s).toFixed(3)));
    svg.querySelectorAll("[data-basefs]").forEach(el =>
      el.setAttribute("font-size", (parseFloat(el.dataset.basefs) * s).toFixed(2)));
  };
  svg._uygula = uygula;
  uygula();
  if (svg._zoom) return;      // olaylar bir kez baglanir
  svg._zoom = true;
  svg.addEventListener("wheel", e => {
    e.preventDefault();
    const [x, y, w, h] = svg._vb;
    const r = svg.getBoundingClientRect();
    const cx = x + (e.clientX - r.left) / r.width * w;
    const cy = y + (e.clientY - r.top) / r.height * h;
    const f = e.deltaY < 0 ? 0.84 : 1.19;
    let nw = Math.min(Math.max(w * f, W * 0.04), W * 12);
    const nh = nw * (H / W);
    svg._vb = [cx - (cx - x) * (nw / w), cy - (cy - y) * (nh / h), nw, nh];
    uygula();
  }, { passive: false });
  let sur = null;
  svg.addEventListener("pointerdown", e => {
    sur = [e.clientX, e.clientY]; svg.setPointerCapture(e.pointerId); });
  svg.addEventListener("pointermove", e => {
    if (!sur) return;
    const [x, y, w, h] = svg._vb, r = svg.getBoundingClientRect();
    svg._vb = [x - (e.clientX - sur[0]) / r.width * w,
               y - (e.clientY - sur[1]) / r.height * h, w, h];
    sur = [e.clientX, e.clientY]; uygula();
  });
  svg.addEventListener("pointerup", () => { sur = null; });
  svg.addEventListener("dblclick", () => { svg._vb = [0, 0, W, H]; uygula(); });
}
function ekle(svg, tip, attrs){ const e = document.createElementNS(SVGNS, tip);
  for (const k in attrs) e.setAttribute(k, attrs[k]); svg.appendChild(e); return e; }
function tumBbox(liste){ let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
  liste.forEach(pts => pts.forEach(p => { x0=Math.min(x0,p[0]);y0=Math.min(y0,p[1]);
    x1=Math.max(x1,p[0]);y1=Math.max(y1,p[1]); }));
  return isFinite(x0) ? [x0,y0,x1,y1] : [0,0,1,1]; }
function fitDonusum(b, W, H, pad){ const w=Math.max(b[2]-b[0],1e-6),h=Math.max(b[3]-b[1],1e-6);
  const s=Math.min((W-2*pad)/w,(H-2*pad)/h); const ox=(W-s*w)/2,oy=(H-s*h)/2;
  return (x,y)=>[ox+(x-b[0])*s, H-(oy+(y-b[1])*s)]; }
function yolStr(pts, T){ return pts.map((p,i)=>{ const [x,y]=T(p[0],p[1]);
  return (i?"L":"M")+x.toFixed(1)+" "+y.toFixed(1); }).join(" "); }
// SVG komut listesini (M/L/Q/C) T ile piksel uzayina cevirip 'd' string uretir.
// Egriler (Q/C) affine donusum altinda bozulmaz -> vektorel, sonsuz zoom net.
function komutYol(cmds, T, kapali){
  let s = "";
  for (const c of cmds){
    const k = c[0];
    if (k==="M"||k==="L"){ const [x,y]=T(c[1],c[2]); s+=k+x.toFixed(2)+" "+y.toFixed(2); }
    else if (k==="Q"){ const [a,b]=T(c[1],c[2]),[x,y]=T(c[3],c[4]);
      s+="Q"+a.toFixed(2)+" "+b.toFixed(2)+" "+x.toFixed(2)+" "+y.toFixed(2); }
    else if (k==="C"){ const [a,b]=T(c[1],c[2]),[d,e]=T(c[3],c[4]),[x,y]=T(c[5],c[6]);
      s+="C"+a.toFixed(2)+" "+b.toFixed(2)+" "+d.toFixed(2)+" "+e.toFixed(2)
        +" "+x.toFixed(2)+" "+y.toFixed(2); }
  }
  if (kapali) s+="Z";
  return s;
}
// Komutlardaki tum kontrol noktalari (bbox/fit icin)
function komutKoords(cmds){
  const pts=[];
  for (const c of cmds){
    if (c[0]==="M"||c[0]==="L") pts.push([c[1],c[2]]);
    else if (c[0]==="Q") pts.push([c[1],c[2]],[c[3],c[4]]);
    else if (c[0]==="C") pts.push([c[1],c[2]],[c[3],c[4]],[c[5],c[6]]);
  }
  return pts;
}
function izgara(svg, W, H){ const ad = 40;
  for (let x=0;x<=W;x+=ad) ekle(svg,"line",{x1:x,y1:0,x2:x,y2:H,stroke:"var(--cizgi)","stroke-width":.5,opacity:.4});
  for (let y=0;y<=H;y+=ad) ekle(svg,"line",{x1:0,y1:y,x2:W,y2:y,stroke:"var(--cizgi)","stroke-width":.5,opacity:.4}); }
function cizVarliklar(svgId, varliklar, riskliHandlelar, basGoster){
  const svg = $(svgId); if (!svg) return; svgKur(svg);
  const W = svg.clientWidth || 600, H = svg.clientHeight || 440;
  const tum = []; varliklar.forEach(v => komutKoords(v.d).forEach(p => tum.push(p)));
  const T = fitDonusum(tumBbox([tum]), W, H, 26);
  izgara(svg, W, H);
  const rs = new Set(riskliHandlelar || []);
  varliklar.forEach(v => {
    const riskli = rs.has(v.handle);
    ekle(svg, "path", { d: komutYol(v.d, T, v.kapali), fill:"none",
      stroke: riskli ? "#ff3b30" : "var(--acc)", "stroke-width": riskli?2:1.3,
      "vector-effect": "non-scaling-stroke", opacity: riskli?.95:.85 });
    if (v.baslangic) { const [px,py]=T(v.baslangic[0],v.baslangic[1]);
      ekle(svg,"circle",{cx:px,cy:py,r:basGoster?5:4,"data-baser":basGoster?5:4,
        fill:basGoster?"#34c759":"var(--metin2)",stroke:"var(--yuzey)",
        "stroke-width":1.5,"vector-effect":"non-scaling-stroke"}); }
  });
  zoomEtkinlestir(svg);
}

// ===================== toplu isle =====================
$("topluBtn").onclick = () => { $("pKlasor").value = GZ.yol || ""; $("perde").classList.remove("gizli"); };
function perdeKapat(){ $("perde").classList.add("gizli"); }
$("perde").onclick = e => { if (e.target === $("perde")) perdeKapat(); };
async function topluIsle() {
  const d = $("pDurum"); d.innerHTML = `<span class="yukleniyor"></span> Isleniyor…`;
  const s = await api("/api/proje/klasor", {
    klasor: $("pKlasor").value.trim(), proje_ad: $("pAd").value.trim() || "proje",
    onizleme: $("pOnizleme").checked, opts: { gcode_mod: $("pMod").value } });
  if (s.hata) { d.innerHTML = `<span class="uyari">${s.hata}</span>`; return; }
  // birlesik sonuc tablosu
  let t = `<div class="ok" style="margin-bottom:6px">${s.sayi} dosya islendi · Cikti: ${s.dizin}</div>`;
  t += `<table class="ozet-tablo"><tr><th>Dosya</th><th>Tur</th><th>Sonuc</th></tr>`;
  (s.gunluk || []).forEach(g => {
    const ad = (g.giris || "").split("/").pop();
    let sonuc;
    if (g.hata) sonuc = `<span class="uyari">${g.hata}</span>`;
    else if (g.tur === "dxf") sonuc = `node -${g.silinen_node}, tasinan ${g.kaydirilan}, ` +
      `butunluk ${g.dogrulama ? "<span class='ok'>OK</span>" : "<span class='uyari'>UYARI</span>"}`;
    else sonuc = `${g.blok} blok (${g.mod})`;
    t += `<tr><td>${ad}</td><td>${g.tur}</td><td>${sonuc}</td></tr>`;
  });
  t += `</table>`;
  d.innerHTML = t;
}

// ===================== toplu kaydet =====================
async function tumKaydet() {
  let n = 0;
  for (const d of DOCS) {
    if (d.durum !== "hazir") continue;
    if (d.tur === "dxf") { const r = await api("/api/dxf/kaydet", { yol: d.yol });
      if (!r.hata) n++; }
    else if (d.gc) { const r = await api("/api/gcode/kaydet", { yol: d.yol, sira: d.gc.sira });
      if (!r.hata) n++; }
  }
  bildir(n ? `${n} dosya kaydedildi` : "Kaydedilecek acik dosya yok");
}
$("tumKaydetBtn").onclick = tumKaydet;

// ===================== bildirim (toast) =====================
function bildir(msg, hata) {
  let t = document.getElementById("toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; document.body.appendChild(t); }
  t.textContent = msg; t.className = "toast" + (hata ? " hata" : ""); t.style.opacity = "1";
  clearTimeout(t._t); t._t = setTimeout(() => { t.style.opacity = "0"; }, 2600);
}

// ===================== klavye kisayollari =====================
document.addEventListener("keydown", e => {
  const meta = e.ctrlKey || e.metaKey;
  if (!meta) return;
  const doc = aktifDoc();
  const k = e.key.toLowerCase();
  if (k === "s" && e.shiftKey) { e.preventDefault(); tumKaydet(); return; }
  if (k === "s") { e.preventDefault();
    if (doc && doc.tur === "dxf") api("/api/dxf/kaydet", { yol: doc.yol })
      .then(r => bildir(r.hata || "Kaydedildi: " + r.cikti, !!r.hata));
    else if (doc && doc.gc) gcKaydet(doc);
    return; }
  if (k === "w" && AKTIF != null) { e.preventDefault(); docKapat(AKTIF, { stopPropagation() {} }); return; }
  if (doc && doc.tur === "gcode" && doc.gc) {
    if (k === "z") { e.preventDefault(); gcGeri(doc); return; }
    if (k === "y") { e.preventDefault(); gcIleri(doc); return; }
  }
  if (/^[1-9]$/.test(e.key)) { const i = +e.key - 1;
    if (DOCS[i]) { e.preventDefault(); AKTIF = DOCS[i].id; render(); } }
});

// ===================== surukle-birak yukleme =====================
(function () {
  const birak = $("birak");
  let sayi = 0;
  const dosyaVar = e => e.dataTransfer &&
    Array.from(e.dataTransfer.types || []).includes("Files");
  window.addEventListener("dragenter", e => {
    if (dosyaVar(e)) { sayi++; birak.classList.remove("gizli"); } });
  window.addEventListener("dragover", e => { if (dosyaVar(e)) e.preventDefault(); });
  window.addEventListener("dragleave", () => { sayi--; if (sayi <= 0) birak.classList.add("gizli"); });
  window.addEventListener("drop", async e => {
    e.preventDefault(); sayi = 0; birak.classList.add("gizli");
    for (const file of Array.from(e.dataTransfer.files || [])) {
      const b64 = await new Promise(res => { const fr = new FileReader();
        fr.onload = () => res(fr.result.split(",")[1]); fr.readAsDataURL(file); });
      const r = await api("/api/yukle", { ad: file.name, b64 });
      if (r.hata) bildir(r.hata, true); else dosyaAc(r);
    }
  });
})();

// ===================== NESTING =====================
let NEST = { parcalar: [], tabakalar: [], sonuc: null, aktif: 0 };

$("nestBtn").onclick = () => { $("nestPanel").classList.remove("gizli");
  nestParcaCiz(); nestTabakaCiz(); };

// motor secici (raster / nfp) — ilgili ayar gruplarini goster/gizle
let NEST_MOTOR = "raster";
document.querySelectorAll("#nMotor button").forEach(b => b.onclick = () => {
  NEST_MOTOR = b.dataset.motor;
  document.querySelectorAll("#nMotor button").forEach(x =>
    x.classList.toggle("aktif", x === b));
  document.querySelectorAll("[data-motor-goster]").forEach(g =>
    g.classList.toggle("gizli", g.dataset.motorGoster !== NEST_MOTOR));
});
function nestKapat(){ $("nestPanel").classList.add("gizli"); }
function nestYardim(){ $("nestYardimPerde").classList.remove("gizli"); }
function nestYardimKapat(){ $("nestYardimPerde").classList.add("gizli"); }

function dikdortgenPoly(w, h){ return [[0,0],[w,0],[w,h],[0,h]]; }
function dairePoly(r, n){ n=n||64; const p=[]; for(let i=0;i<n;i++){
  const a=2*Math.PI*i/n; p.push([r+r*Math.cos(a), r+r*Math.sin(a)]); } return p; }

// --- parca ekleme ---
function nestDikdortgenParca(){
  const s=prompt("Dikdortgen parca — en x boy x adet (mm), orn: 100 50 4","100 50 1");
  if(!s) return; const [w,h,n]=s.split(/[x ,]+/).map(Number);
  if(!w||!h) return;
  NEST.parcalar.push({id:"dik"+(++sayac), ad:`Dikdortgen ${w}×${h}`,
    poly:dikdortgenPoly(w,h), adet:n||1, w, h}); nestParcaCiz();
}
function nestDaireParca(){
  const s=prompt("Daire parca — cap x adet (mm), orn: 40 6","40 1");
  if(!s) return; const [d,n]=s.split(/[x ,]+/).map(Number); if(!d) return;
  NEST.parcalar.push({id:"dai"+(++sayac), ad:`Daire Ø${d}`,
    poly:dairePoly(d/2), adet:n||1, w:d, h:d}); nestParcaCiz();
}
$("nestParcaDosya").onchange = async e => {
  const f=e.target.files[0]; if(!f) return;
  const b64=await dosyaB64(f); const u=await api("/api/yukle",{ad:f.name,b64});
  if(u.hata){ bildir(u.hata,true); return; }
  const r=await api("/api/nest/parcalar_dxf",{yol:u.yol});
  if(r.hata){ bildir(r.hata,true); return; }
  (r.parcalar||[]).forEach(p=>NEST.parcalar.push({...p}));
  bildir(`${(r.parcalar||[]).length} parca eklendi`); nestParcaCiz();
  e.target.value="";
};
function dosyaB64(f){ return new Promise(res=>{ const fr=new FileReader();
  fr.onload=()=>res(fr.result.split(",")[1]); fr.readAsDataURL(f); }); }

function nestParcaCiz(){
  const k=$("nestParcaListe"); k.innerHTML="";
  if(!NEST.parcalar.length){ k.innerHTML='<div class="nest-oge">Henuz parca yok</div>'; return; }
  NEST.parcalar.forEach((p,i)=>{
    const d=document.createElement("div"); d.className="nest-oge";
    d.innerHTML=`<span class="isim">${p.ad||p.id}</span>
      <span style="color:var(--metin2);font-size:11px">adet</span>
      <input type="number" min="1" value="${p.adet}">
      <span class="sil">×</span>`;
    d.querySelector("input").onchange=e=>p.adet=parseInt(e.target.value)||1;
    d.querySelector(".sil").onclick=()=>{ NEST.parcalar.splice(i,1); nestParcaCiz(); };
    k.appendChild(d);
  });
}

// --- tabaka ekleme ---
function nestDikdortgenTabaka(){
  const s=prompt("Dikdortgen tabaka — en x boy (mm), orn: 1500 3000","1220 2440");
  if(!s) return; const [w,h]=s.split(/[x ,]+/).map(Number); if(!w||!h) return;
  NEST.tabakalar.push({ad:`Tabaka ${w}×${h}`, poly:dikdortgenPoly(w,h)}); nestTabakaCiz();
}
function nestDaireTabaka(){
  const s=prompt("Daire tabaka — cap (mm)","600");
  if(!s) return; const d=Number(s); if(!d) return;
  NEST.tabakalar.push({ad:`Daire tabaka Ø${d}`, poly:dairePoly(d/2)}); nestTabakaCiz();
}
$("nestTabakaDosya").onchange = async e => {
  const f=e.target.files[0]; if(!f) return;
  const b64=await dosyaB64(f); const u=await api("/api/yukle",{ad:f.name,b64});
  if(u.hata){ bildir(u.hata,true); return; }
  const r=await api("/api/nest/parcalar_dxf",{yol:u.yol});
  if(r.hata||!(r.parcalar||[]).length){ bildir("Sekil bulunamadi",true); return; }
  // en buyuk alanli konturu tabaka (konteyner) al
  let big=r.parcalar[0], ba=big.w*big.h;
  r.parcalar.forEach(p=>{ if(p.w*p.h>ba){ba=p.w*p.h;big=p;} });
  NEST.tabakalar.push({ad:`DXF sekil (${f.name})`, poly:big.poly}); nestTabakaCiz();
  e.target.value="";
};
function nestTabakaCiz(){
  const k=$("nestTabakaListe"); k.innerHTML="";
  if(!NEST.tabakalar.length){ k.innerHTML='<div class="nest-oge">Henuz tabaka yok</div>'; return; }
  NEST.tabakalar.forEach((t,i)=>{
    const d=document.createElement("div"); d.className="nest-oge";
    d.innerHTML=`<span class="isim">${i+1}. ${t.ad}</span><span class="sil">×</span>`;
    d.querySelector(".sil").onclick=()=>{ NEST.tabakalar.splice(i,1); nestTabakaCiz(); };
    k.appendChild(d);
  });
}

// --- calistir ---
async function nestCalistir(){
  if(!NEST.parcalar.length || !NEST.tabakalar.length){
    bildir("Parca ve tabaka ekleyin",true); return; }
  const rot=$("nRot").value;
  let rotasyonlar;
  if(rot==="45") rotasyonlar=[0,45,90,135,180,225,270,315];
  else if(rot==="15"){ rotasyonlar=[]; for(let a=0;a<360;a+=15) rotasyonlar.push(a); }
  else rotasyonlar=rot.split(",").map(Number);
  const ayar={ kerf:+$("nKerf").value, bosluk:+$("nBosluk").value,
    kenar:+$("nKenar").value, cozunurluk:+$("nCoz").value, rotasyonlar,
    motor:NEST_MOTOR, optimizasyon:+$("nKalite").value,
    populasyon:+$("nPop").value, nesil:+$("nNesil").value };
  $("nestDurum").innerHTML=`<span class="yukleniyor"></span> Yerlestiriliyor…`;
  const r=await api("/api/nest/calistir",{parcalar:NEST.parcalar,
    tabakalar:NEST.tabakalar.map(t=>({poly:t.poly})), ayar});
  if(r.hata){ $("nestDurum").innerHTML=`<span class="uyari">${r.hata}</span>`; return; }
  NEST.sonuc=r; NEST.aktif=0;
  nestSekmeCiz(); nestCiz();
  const ym=(r.yerlesmeyen||[]).reduce((a,b)=>a+b.adet,0);
  $("nestDurum").innerHTML=`<span class="ok">Yerlesti:</span> ${r.yerlesim.length} parca · `+
    `${NEST_MOTOR==="nfp"?"NFP+Genetik":"Raster"} · `+
    `doluluk: ${r.doluluk.map((d,i)=>`T${i+1} %${d}`).join(" · ")}`+
    (ym?` · <span class="uyari">${ym} parca sigmadi</span>`:"")+
    (r.uyari?`<br><span class="uyari">${r.uyari}</span>`:"");
}
function nestSekmeCiz(){
  const k=$("nestTabSekme"); k.innerHTML="";
  NEST.tabakalar.forEach((t,i)=>{
    const d=document.createElement("div");
    d.className="nest-tab"+(i===NEST.aktif?" aktif":"");
    const dol=NEST.sonuc?NEST.sonuc.doluluk[i]:0;
    d.textContent=`Tabaka ${i+1} · %${dol}`;
    d.onclick=()=>{ NEST.aktif=i; nestSekmeCiz(); nestCiz(); };
    k.appendChild(d);
  });
}
function nestCiz(){
  const svg=$("nestSvg"); if(!svg) return; svgKur(svg);
  const W=svg.clientWidth||700, H=svg.clientHeight||440;
  const tab=NEST.tabakalar[NEST.aktif]; if(!tab) return;
  const T=fitDonusum(tumBbox([tab.poly]), W, H, 20);
  izgara(svg,W,H);
  // tabaka konturu
  ekle(svg,"path",{d:yolStr(tab.poly,T)+"Z", fill:"none", stroke:"var(--uyari)",
    "stroke-width":1.6, "vector-effect":"non-scaling-stroke"});
  // yerlesmis parcalar (bu tabaka)
  if(NEST.sonuc){
    NEST.sonuc.yerlesim.filter(y=>y.tabaka===NEST.aktif).forEach(y=>{
      ekle(svg,"path",{d:yolStr(y.poly,T)+"Z", fill:"color-mix(in srgb,var(--acc) 22%,transparent)",
        stroke:"var(--acc)","stroke-width":1.1,"vector-effect":"non-scaling-stroke"});
    });
  }
  zoomEtkinlestir(svg);
}
async function nestAktar(tur){
  if(!NEST.sonuc){ bildir("Once yerlestirin",true); return; }
  const r=await api("/api/nest/disari_aktar",{yerlesim:NEST.sonuc.yerlesim,
    tabakalar:NEST.tabakalar.map(t=>({poly:t.poly})), ad:"nesting_"+Date.now()});
  if(r.hata){ bildir(r.hata,true); return; }
  const link=tur==="pdf"?r.indir_pdf:r.indir_dxf;
  if(!link){ bildir("Cikti uretilemedi",true); return; }
  window.location.href=link;
}
$("nestYardimPerde").onclick=e=>{ if(e.target===$("nestYardimPerde")) nestYardimKapat(); };

// ===================== baslangic =====================
gozat(AYAR.al("sonKlasor", null));
