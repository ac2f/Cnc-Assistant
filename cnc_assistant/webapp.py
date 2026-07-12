#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web arayuzu (bagimliliksiz - Python standart kutuphanesi)
=========================================================
Flask vb. gerektirmez; sadece http.server kullanir. Boylece "kutuphane yok"
turu sorunlar olmadan her yerde calisir.

Baslatma:
    python main.py --web
    python main.py --web --port 8000
    cnc-assistant --web

Tarayicida http://127.0.0.1:8000 acilir. Arayuz:
  * DXF: parametreleri ayarla, ONCESI/SONRASI baslangic noktalarini ANLIK gor.
  * G-Code: bloklari listele, siralama onizlemesini (numarali + tasima okli)
    gor, elle yeniden sirala (surukle veya "59 60"), geri al/yinele, kaydet.
    Icerme (nesting) her zaman korunur: en icteki once kesilir; ihlaller
    kirmizi vurgulanir.
  * Proje: bir klasor verip icindeki her seyi otomatik, ayri dizinlere isle.
"""

import base64
import json
import os
import tempfile
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ezdxf

from . import dxf_processor as D
from . import gcode as GC
from . import geometry as GEO
from . import nesting as NEST
from . import nesting_nfp as NEST_NFP
from . import preview as PV
from . import project as P

_YUKLEME_DIZIN = os.path.join(tempfile.gettempdir(), "cnc_assistant_yukleme")
_DXF_ONIZLE = {}          # yol -> {oncesi, sonrasi, riskli} (PDF/yeniden kullanim)
_INDIRILEBILIR = set()    # /indir ile sunulabilecek (bizim urettigimiz) dosyalar

WEB_DIZIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

# Yuklenen G-Code programlari ve optimize DXF dokumanlari (bellek ici durum)
_DURUM = {}
_DXF_DOC = {}


def _boyut_str(n):
    for birim in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {birim}" if birim == "B" else f"{n:.1f} {birim}"
        n /= 1024
    return f"{n:.1f} TB"


# ----------------------------------------------------------------------
# Yardimcilar
# ----------------------------------------------------------------------

def _varlik_json(v):
    return {"tip": v["tip"], "handle": v["handle"],
            "d": v["d"], "baslangic": v["baslangic"], "kapali": v.get("kapali")}


def _gcode_yukle(yol):
    prog = GC.GCodeProgram(yol)
    orijinal = list(prog.bloklar)
    id_map = {id(b): i for i, b in enumerate(orijinal)}
    _DURUM[yol] = {"prog": prog, "orijinal": orijinal, "id_map": id_map}
    return prog, orijinal, id_map


def _ozet_bloklar(orijinal):
    derinlik = GC.containment_derinlik(orijinal)
    out = []
    for i, blok in enumerate(orijinal):
        bx, by = GC.blok_bas_xy(blok)
        poly = GC.blok_polygon(blok)
        merkez = (sum(p[0] for p in poly) / len(poly),
                  sum(p[1] for p in poly) / len(poly)) if poly else (bx, by)
        out.append({"id": i, "x": bx, "y": by, "bbox": GC.blok_bbox(blok),
                    "komut": GC.blok_svg_komut(blok), "merkez": merkez,
                    "derinlik": derinlik[i], "satir": len(blok)})
    return out


def _sirala_idler(yol, mod):
    d = _DURUM[yol]
    sirali = GC.sirala(d["orijinal"], mod)
    return [d["id_map"][id(b)] for b in sirali]


def _ihlaller(yol, sira):
    """Verilen sira (id listesi) icin icerme ihlallerini pozisyon ciftleri
    olarak doner."""
    d = _DURUM[yol]
    d["prog"].bloklar = [d["orijinal"][i] for i in sira]
    return d["prog"].icerme_ihlalleri()


# ----------------------------------------------------------------------
# API islemleri
# ----------------------------------------------------------------------

def api_scan(veri):
    klasor = veri.get("klasor", ".")
    if not os.path.isdir(klasor):
        return {"hata": f"Klasor bulunamadi: {klasor}"}
    dosyalar = []
    for ad in sorted(os.listdir(klasor)):
        tam = os.path.join(klasor, ad)
        if not os.path.isfile(tam):
            continue
        uz = os.path.splitext(ad)[1].lower()
        if uz == ".dxf":
            dosyalar.append({"yol": tam, "ad": ad, "tur": "dxf"})
        elif uz in P.GCODE_UZANTILAR:
            dosyalar.append({"yol": tam, "ad": ad, "tur": "gcode"})
    return {"klasor": os.path.abspath(klasor), "dosyalar": dosyalar}


# Guvenlik/performans limitleri (sistem cokmesin diye)
_ALT_KLASOR_SAYIM_LIMITI = 400     # bundan fazla alt klasor varsa sayim yapilma
_KLASOR_TARAMA_LIMITI = 4000       # bir klasorde en fazla bu kadar oge taranir


def _klasor_say(yol):
    """Bir klasordeki (yalnizca dogrudan icindeki) DXF ve G-Code dosya
    sayisini doner: (dxf, gcode). Cok buyuk klasorlerde sistemin kilitlenmesini
    onlemek icin taranan oge sayisi _KLASOR_TARAMA_LIMITI ile sinirlidir."""
    dxf = gcode = 0
    try:
        with os.scandir(yol) as it:
            for i, g in enumerate(it):
                if i >= _KLASOR_TARAMA_LIMITI:
                    break
                try:
                    if not g.is_file():
                        continue
                except OSError:
                    continue
                uz = os.path.splitext(g.name)[1].lower()
                if uz == ".dxf":
                    dxf += 1
                elif uz in P.GCODE_UZANTILAR:
                    gcode += 1
    except (PermissionError, OSError):
        return None
    return (dxf, gcode)


def api_gozat(veri):
    """Sunucu tarafinda klasor gezme: alt klasorler + DXF/G-Code dosyalari.
    Her alt klasor icin dogrudan icindeki DXF/G-Code sayilari da hesaplanir
    (cok fazla alt klasor varsa performans icin atlanir)."""
    yol = veri.get("yol") or os.getcwd()
    yol = os.path.abspath(os.path.expanduser(yol))
    if os.path.isfile(yol):
        yol = os.path.dirname(yol)
    if not os.path.isdir(yol):
        return {"hata": f"Klasor yok: {yol}"}
    ham_klasorler, dosyalar = [], []
    try:
        for ad in sorted(os.listdir(yol), key=str.lower):
            if ad.startswith("."):
                continue
            tam = os.path.join(yol, ad)
            try:
                st = os.stat(tam)
                if os.path.isdir(tam):
                    ham_klasorler.append((ad, tam, st.st_mtime))
                elif os.path.isfile(tam):
                    uz = os.path.splitext(ad)[1].lower()
                    tur = ("dxf" if uz == ".dxf"
                           else "gcode" if uz in P.GCODE_UZANTILAR else None)
                    if tur:
                        dosyalar.append({"ad": ad, "yol": tam, "tur": tur,
                                         "boyut": _boyut_str(st.st_size),
                                         "bayt": st.st_size, "mtime": st.st_mtime})
            except OSError:
                continue
    except PermissionError:
        return {"hata": f"Erisim reddedildi: {yol}"}

    # Alt klasor icerik sayimlari (limit dahilinde)
    say = len(ham_klasorler) <= _ALT_KLASOR_SAYIM_LIMITI
    klasorler = []
    for ad, tam, mtime in ham_klasorler:
        d = {"ad": ad, "yol": tam, "mtime": mtime, "dxf": None, "gcode": None}
        if say:
            sonuc = _klasor_say(tam)
            if sonuc is not None:
                d["dxf"], d["gcode"] = sonuc
        klasorler.append(d)

    ust = os.path.dirname(yol)
    return {"yol": yol, "ust": ust if ust != yol else None,
            "ev": os.path.expanduser("~"), "cwd": os.getcwd(),
            "sayim_yapildi": say,
            "klasorler": klasorler, "dosyalar": dosyalar}


_DESTEK_YONU = {"sol-ust": (-1.0, 1.0), "ust": (0.0, 1.0), "sag-ust": (1.0, 1.0)}


def _guvenli_ad(ad):
    """Yol gezme (path traversal) engelle: sadece dosya/klasor adi."""
    return os.path.basename(str(ad)).strip()


def api_klasor_olustur(veri):
    ust = os.path.abspath(veri.get("yol") or os.getcwd())
    ad = _guvenli_ad(veri.get("ad", ""))
    if not ad:
        return {"hata": "Gecerli bir klasor adi girin."}
    if not os.path.isdir(ust):
        return {"hata": f"Ust klasor yok: {ust}"}
    hedef = os.path.join(ust, ad)
    if os.path.exists(hedef):
        return {"hata": "Bu isimde bir oge zaten var."}
    try:
        os.makedirs(hedef)
    except Exception as e:      # noqa: BLE001
        return {"hata": str(e)}
    return {"yol": hedef}


def api_klasor_sil(veri):
    import shutil
    yol = os.path.abspath(veri.get("yol", ""))
    korumali = {"/", os.path.abspath(os.path.expanduser("~")),
                os.path.abspath(os.getcwd())}
    if yol in korumali or os.path.dirname(yol) == yol:
        return {"hata": "Bu klasor silinemez (korumali)."}
    if not os.path.isdir(yol):
        return {"hata": "Klasor yok."}
    try:
        shutil.rmtree(yol)
    except Exception as e:      # noqa: BLE001
        return {"hata": str(e)}
    return {"ust": os.path.dirname(yol)}


def api_yeniden_adlandir(veri):
    yol = os.path.abspath(veri.get("yol", ""))
    yeni = _guvenli_ad(veri.get("yeni_ad", ""))
    if not os.path.exists(yol):
        return {"hata": "Oge yok."}
    if not yeni:
        return {"hata": "Gecerli bir ad girin."}
    hedef = os.path.join(os.path.dirname(yol), yeni)
    if os.path.exists(hedef):
        return {"hata": "Bu isimde bir oge zaten var."}
    try:
        os.rename(yol, hedef)
    except Exception as e:      # noqa: BLE001
        return {"hata": str(e)}
    return {"yol": hedef}


def _dxf_opts(veri):
    return {
        "node_temizle": veri.get("node_temizle", True),
        "node_tol": float(veri.get("node_tol", 1e-6)),
        "destek_yonu": _DESTEK_YONU.get(veri.get("destek_yonu", "sol-ust"),
                                        (-1.0, 1.0)),
        "referans_dxf": veri.get("referans_dxf") or None,
    }


def api_dxf_onizle(veri):
    """DXF'i bellek uzerinde optimize eder (diske YAZMAZ); onizleme doner."""
    yol = veri["yol"]
    if not os.path.isfile(yol):
        return {"hata": f"Dosya yok: {yol}"}
    sonuc = D.optimize_doc(yol, _dxf_opts(veri),
                           float(veri.get("alan_orani", 0.10)),
                           float(veri.get("boyut_orani", 0.50)))
    _DXF_DOC[yol] = sonuc["doc"]
    _DXF_ONIZLE[yol] = {"oncesi": sonuc["oncesi"], "sonrasi": sonuc["sonrasi"],
                        "riskli": sonuc["riskli_handlelar"]}
    riskli_kutu = [{"merkez": m, "w": w, "h": h}
                   for _, _, m, w, h in sonuc["riskli"]]
    return {
        "kaydirilan": sonuc["kaydirilan"],
        "silinen_node": sonuc["silinen_node"],
        "cember": sonuc["cember"],
        "dogrulama": sonuc["dogrulama"],
        "cevre": sonuc["cevre"],
        "oncesi": [_varlik_json(v) for v in sonuc["oncesi"]],
        "sonrasi": [_varlik_json(v) for v in sonuc["sonrasi"]],
        "riskli_handlelar": list(sonuc["riskli_handlelar"]),
        "riskli": riskli_kutu,
    }


def api_dxf_kaydet(veri):
    """Onizlenen (bellekteki) optimize DXF'i diske kaydeder."""
    yol = veri["yol"]
    if yol not in _DXF_DOC:
        return {"hata": "Once onizleyin."}
    kok, _ = os.path.splitext(yol)
    cikti = veri.get("cikti") or f"{kok}_optimized.dxf"
    _DXF_DOC[yol].saveas(cikti)
    return {"cikti": cikti}


def api_gcode_yukle(veri):
    yol = veri["yol"]
    if not os.path.isfile(yol):
        return {"hata": f"Dosya yok: {yol}"}
    prog, orijinal, _ = _gcode_yukle(yol)
    if not prog.guvenli:
        return {"guvenli": False,
                "uyarilar": ["Dosyada G91 (artimli mod) var; siralama "
                             "guvenlik nedeniyle kapatildi."]}
    bloklar = _ozet_bloklar(orijinal)
    onerilen = _sirala_idler(yol, "sol-alt")
    return {"guvenli": True, "uyarilar": prog.uyarilar,
            "sabit_son": prog.sabit_son is not None,
            "birim": prog.birim,
            "karsilastir": prog.karsilastir(),
            "bloklar": bloklar, "onerilen_sira": onerilen}


def api_gcode_karsilastir(veri):
    yol = veri["yol"]
    if yol not in _DURUM:
        return {"hata": "Once dosyayi yukleyin."}
    return _DURUM[yol]["prog"].karsilastir()


def api_gcode_tablar(veri):
    """Verilen sira icin her blogun konturuna KOPRU (tab) konumlarini uretir.
    Kesim geometrisini degistirmez; sadece 'nereye koprü' bilgisi."""
    yol = veri["yol"]
    if yol not in _DURUM:
        return {"hata": "Once dosyayi yukleyin."}
    adet = int(veri.get("adet", 4))
    d = _DURUM[yol]
    sira = veri.get("sira") or list(range(len(d["orijinal"])))
    tablar = []
    for i in sira:
        kontur = GC.blok_yol(d["orijinal"][i])
        pts = GEO.tab_pozisyonlari(kontur, adet=adet) if len(kontur) >= 3 else []
        tablar.append([[round(x, 4), round(y, 4)] for x, y, _ in pts])
    return {"tablar": tablar}


def api_gcode_sirala(veri):
    yol = veri["yol"]
    if yol not in _DURUM:
        return {"hata": "Once dosyayi yukleyin."}
    return {"sira": _sirala_idler(yol, veri.get("mod", "sol-alt"))}


def api_gcode_dogrula(veri):
    yol = veri["yol"]
    if yol not in _DURUM:
        return {"hata": "Once dosyayi yukleyin."}
    return {"ihlaller": _ihlaller(yol, veri["sira"])}


def api_gcode_kaydet(veri):
    yol = veri["yol"]
    if yol not in _DURUM:
        return {"hata": "Once dosyayi yukleyin."}
    d = _DURUM[yol]
    sira = veri["sira"]
    d["prog"].bloklar = [d["orijinal"][i] for i in sira]
    kok, _ = os.path.splitext(yol)
    cikti = veri.get("cikti") or f"{kok}_reordered.tap"
    d["prog"].yaz(cikti)
    return {"cikti": cikti, "ihlaller": d["prog"].icerme_ihlalleri(),
            "bosta_yol": d["prog"].bosta_yol()}


_ONIZ_FORMATLAR = {"pdf", "png", "svg"}
_ONIZ_PANEL_ETIKET = {"birlikte": "onizleme", "oncesi": "oncesi",
                      "sonrasi": "sonrasi"}


def _oniz_varliklar(veri):
    """Onizleme icin ONCESI/SONRASI varliklarini (bellek/onbellek) getirir."""
    yol = veri["yol"]
    o = _DXF_ONIZLE.get(yol)
    if o is None:
        if not os.path.isfile(yol):
            return None, {"hata": f"Dosya yok: {yol}"}
        s = D.optimize_doc(yol, _dxf_opts(veri))
        o = {"oncesi": s["oncesi"], "sonrasi": s["sonrasi"],
             "riskli": s["riskli_handlelar"]}
    return o, None


def api_dxf_onizleme(veri):
    """Onizlemeyi kullanicinin sectigi stil/panel/formatta uretir.

    veri: yol, dxf opts, ayrica:
      stil    : {cizgi_kalinlik, vektor_renk, riskli_renk, bas_renk, bas_boyut,
                 numara, numara_boyut, izgara}
      paneller: "birlikte" | "oncesi" | "sonrasi"  (varsayilan birlikte)
      format  : "pdf" | "png" | "svg"              (varsayilan pdf)
    Doner: {dosya, indir} veya {hata}."""
    o, hata = _oniz_varliklar(veri)
    if hata:
        return hata
    paneller = veri.get("paneller", "birlikte")
    if paneller not in _ONIZ_PANEL_ETIKET:
        paneller = "birlikte"
    fmt = str(veri.get("format", "pdf")).lower()
    if fmt not in _ONIZ_FORMATLAR:
        fmt = "pdf"
    stil = veri.get("stil") or None
    kok, _ = os.path.splitext(veri["yol"])
    cikti = f"{kok}_{_ONIZ_PANEL_ETIKET[paneller]}.{fmt}"
    ok = PV.onizleme_uret(o["oncesi"], o["sonrasi"], o["riskli"], cikti,
                          paneller=paneller, stil=stil)
    if not ok:
        return {"hata": "matplotlib kurulu degil; onizleme uretilemedi."}
    _INDIRILEBILIR.add(os.path.abspath(cikti))
    return {"dosya": cikti,
            "indir": "/indir?yol=" + urllib.parse.quote(os.path.abspath(cikti))}


def api_dxf_pdf(veri):
    """Geriye donuk uc: ONCESI+SONRASI birlikte, PDF (varsayilan stil)."""
    v = dict(veri); v.setdefault("paneller", "birlikte"); v.setdefault("format", "pdf")
    r = api_dxf_onizleme(v)
    if "dosya" in r:
        r["pdf"] = r["dosya"]
    return r


def api_dxf_nest(veri):
    """DXF parcalarini tabakaya yeniden yerlestirir (nesting) ve kaydeder."""
    yol = veri["yol"]
    if not os.path.isfile(yol):
        return {"hata": f"Dosya yok: {yol}"}
    doc = ezdxf.readfile(yol)
    oncesi = D.varlik_yollari(doc)
    r = NEST.nest_doc(doc,
                      tabaka_genislik=float(veri.get("tabaka_genislik", 0)) or None,
                      bosluk=float(veri.get("bosluk", 5.0)),
                      kenar=float(veri.get("kenar", 5.0)))
    if r.get("hata"):
        return r
    kok, _ = os.path.splitext(yol)
    cikti = veri.get("cikti") or f"{kok}_nested.dxf"
    doc.saveas(cikti)
    _DXF_DOC[cikti] = doc
    sonrasi = D.varlik_yollari(doc)
    return {"cikti": cikti, "parca_sayisi": r["parca_sayisi"],
            "tabaka": r["tabaka"], "cevre_korundu": r["cevre_korundu"],
            "oncesi": [_varlik_json(v) for v in oncesi],
            "sonrasi": [_varlik_json(v) for v in sonrasi]}


def api_yukle(veri):
    """Tarayicidan surukle-birak ile gonderilen dosyayi sunucuya yazar."""
    ad = os.path.basename(veri.get("ad", "dosya"))
    b64 = veri.get("b64", "")
    os.makedirs(_YUKLEME_DIZIN, exist_ok=True)
    hedef = os.path.join(_YUKLEME_DIZIN, ad)
    try:
        with open(hedef, "wb") as f:
            f.write(base64.b64decode(b64))
    except Exception as e:      # noqa: BLE001
        return {"hata": f"Yukleme hatasi: {e}"}
    uz = os.path.splitext(ad)[1].lower()
    tur = "dxf" if uz == ".dxf" else "gcode" if uz in P.GCODE_UZANTILAR else None
    if not tur:
        return {"hata": "Desteklenmeyen dosya turu (DXF veya G-Code olmali)."}
    return {"yol": hedef, "ad": ad, "tur": tur}


def api_nest_parcalar_dxf(veri):
    """Bir DXF'teki kapali konturlari nesting parcalari olarak doner."""
    yol = veri["yol"]
    if not os.path.isfile(yol):
        return {"hata": f"Dosya yok: {yol}"}
    doc = ezdxf.readfile(yol)
    parcalar = []
    for i, v in enumerate(D.baslangic_noktalari_ve_konturlar(doc)):
        pts = v["kontur"]
        if len(pts) < 3:
            continue
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if w < 1e-6 or h < 1e-6:
            continue
        parcalar.append({"id": f"{os.path.basename(yol)}#{i}",
                         "ad": f"{v['tip']} {i}", "poly": pts, "adet": 1,
                         "w": round(w, 2), "h": round(h, 2)})
    return {"parcalar": parcalar}


def api_nest_calistir(veri):
    parcalar = veri.get("parcalar") or []
    tabakalar = veri.get("tabakalar") or []
    if not parcalar or not tabakalar:
        return {"hata": "En az bir parca ve bir tabaka gerekli."}
    ayar = veri.get("ayar", {})
    if ayar.get("motor") == "nfp":
        r = NEST_NFP.nfp_nest(parcalar, tabakalar, ayar)
        if r is None:
            r = NEST.raster_nest(parcalar, tabakalar, ayar)
            r["uyari"] = ("pyclipper kurulu degil; hizli (raster) motor "
                          "kullanildi. NFP icin: pip install pyclipper")
        return r
    return NEST.raster_nest(parcalar, tabakalar, ayar)


def _poly_to_lw(msp, poly, layer, dx=0.0, dy=0.0):
    msp.add_lwpolyline([(x + dx, y + dy) for x, y in poly],
                       close=True, dxfattribs={"layer": layer})


def api_nest_disari_aktar(veri):
    """Nesting sonucunu DXF (+ vektorel PDF) olarak yazar. Tabakalar yan yana
    yerlestirilir (aralarinda bosluk)."""
    yerlesim = veri.get("yerlesim") or []
    tabakalar = veri.get("tabakalar") or []
    if not yerlesim:
        return {"hata": "Once yerlestirme calistirin."}
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    ofsx = 0.0
    tab_ofset = []
    for t in tabakalar:
        xs = [p[0] for p in t["poly"]]; ys = [p[1] for p in t["poly"]]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        dx = ofsx - x0
        tab_ofset.append((dx, -y0))
        _poly_to_lw(msp, t["poly"], "TABAKA", dx, -y0)
        ofsx += (x1 - x0) + max((x1 - x0), (y1 - y0)) * 0.05 + 10
    for y in yerlesim:
        ti = y.get("tabaka", 0)
        dx, dy = tab_ofset[ti] if ti < len(tab_ofset) else (0.0, 0.0)
        _poly_to_lw(msp, y["poly"], "PARCA", dx, dy)
    ad = veri.get("ad", "nesting")
    kok = os.path.join(_YUKLEME_DIZIN, ad)
    os.makedirs(_YUKLEME_DIZIN, exist_ok=True)
    dxf_yol = f"{kok}.dxf"
    doc.saveas(dxf_yol)
    _INDIRILEBILIR.add(os.path.abspath(dxf_yol))
    # PDF (vektorel) onizleme: tabakalar + yerlesmis parcalar (ofsetli)
    pdf_link = None
    try:
        def _yol_komut(poly, dx, dy):
            pts = [(x + dx, y + dy) for x, y in poly]
            return [["M", pts[0][0], pts[0][1]]] + [["L", q[0], q[1]] for q in pts[1:]]
        varliklar = []
        for i, t in enumerate(tabakalar):
            dx, dy = tab_ofset[i]
            varliklar.append({"tip": "T", "handle": f"t{i}", "kapali": True,
                              "baslangic": None, "d": _yol_komut(t["poly"], dx, dy)})
        for j, y in enumerate(yerlesim):
            dx, dy = tab_ofset[y.get("tabaka", 0)] if tab_ofset else (0, 0)
            varliklar.append({"tip": "P", "handle": f"p{j}", "kapali": True,
                              "baslangic": None, "d": _yol_komut(y["poly"], dx, dy)})
        pdf_yol = f"{kok}.pdf"
        # tabaka handle'larini vurgula (kirmizi kontur)
        vurgu = {f"t{i}" for i in range(len(tabakalar))}
        if PV.vektor_pdf(varliklar, pdf_yol, "Nesting sonucu", vurgu):
            _INDIRILEBILIR.add(os.path.abspath(pdf_yol))
            pdf_link = "/indir?yol=" + urllib.parse.quote(os.path.abspath(pdf_yol))
    except Exception:
        pass
    return {"dxf": dxf_yol,
            "indir_dxf": "/indir?yol=" + urllib.parse.quote(os.path.abspath(dxf_yol)),
            "indir_pdf": pdf_link}


def api_proje_klasor(veri):
    klasor = veri["klasor"]
    if not os.path.isdir(klasor):
        return {"hata": f"Klasor bulunamadi: {klasor}"}
    kok = veri.get("proje_kok") or os.path.join(klasor, "cnc_ciktilar")
    ad = veri.get("proje_ad") or "proje"
    opts = veri.get("opts", {})
    proje = P.Proje(kok, ad, opts)
    sonuclar = proje.klasor_isle(klasor, onizleme=veri.get("onizleme", True))
    return {"dizin": proje.dizin, "gunluk": sonuclar,
            "sayi": len(sonuclar)}


API = {
    "/api/scan": api_scan,
    "/api/gozat": api_gozat,
    "/api/klasor/olustur": api_klasor_olustur,
    "/api/klasor/sil": api_klasor_sil,
    "/api/yeniden_adlandir": api_yeniden_adlandir,
    "/api/dxf/onizle": api_dxf_onizle,
    "/api/dxf/kaydet": api_dxf_kaydet,
    "/api/dxf/pdf": api_dxf_pdf,
    "/api/dxf/onizleme": api_dxf_onizleme,
    "/api/dxf/nest": api_dxf_nest,
    "/api/gcode/yukle": api_gcode_yukle,
    "/api/gcode/sirala": api_gcode_sirala,
    "/api/gcode/dogrula": api_gcode_dogrula,
    "/api/gcode/kaydet": api_gcode_kaydet,
    "/api/gcode/karsilastir": api_gcode_karsilastir,
    "/api/gcode/tablar": api_gcode_tablar,
    "/api/yukle": api_yukle,
    "/api/nest/parcalar_dxf": api_nest_parcalar_dxf,
    "/api/nest/calistir": api_nest_calistir,
    "/api/nest/disari_aktar": api_nest_disari_aktar,
    "/api/proje/klasor": api_proje_klasor,
}


# ----------------------------------------------------------------------
# HTTP isleyici
# ----------------------------------------------------------------------

class Isleyici(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # sessiz

    def _gonder(self, kod, icerik, tur="application/json; charset=utf-8"):
        gövde = icerik if isinstance(icerik, bytes) else icerik.encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(gövde)))
        self.end_headers()
        self.wfile.write(gövde)

    def do_GET(self):
        yol = self.path.split("?", 1)[0]
        if yol == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if yol == "/indir":
            self._indir()
            return
        if yol == "/":
            yol = "/index.html"
        dosya = os.path.join(WEB_DIZIN, yol.lstrip("/"))
        if os.path.isfile(dosya) and os.path.abspath(dosya).startswith(WEB_DIZIN):
            tur = ("text/html; charset=utf-8" if dosya.endswith(".html")
                   else "text/javascript" if dosya.endswith(".js")
                   else "text/css" if dosya.endswith(".css")
                   else "application/octet-stream")
            with open(dosya, "rb") as f:
                self._gonder(200, f.read(), tur)
        else:
            self._gonder(404, json.dumps({"hata": "bulunamadi"}))

    def _indir(self):
        """Bizim urettigimiz (izinli) dosyalari indirme olarak sunar."""
        q = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
        hedef = os.path.abspath((q.get("yol", [""])[0]))
        if hedef not in _INDIRILEBILIR or not os.path.isfile(hedef):
            self._gonder(404, json.dumps({"hata": "bulunamadi"}))
            return
        with open(hedef, "rb") as f:
            veri = f.read()
        tur = ("application/pdf" if hedef.endswith(".pdf")
               else "image/svg+xml" if hedef.endswith(".svg")
               else "image/png" if hedef.endswith(".png")
               else "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Disposition",
                         f'attachment; filename="{os.path.basename(hedef)}"')
        self.send_header("Content-Length", str(len(veri)))
        self.end_headers()
        self.wfile.write(veri)

    def do_POST(self):
        yol = self.path.split("?", 1)[0]
        fn = API.get(yol)
        if not fn:
            self._gonder(404, json.dumps({"hata": "bilinmeyen uc"}))
            return
        uzunluk = int(self.headers.get("Content-Length", 0))
        try:
            veri = json.loads(self.rfile.read(uzunluk) or b"{}")
            sonuc = fn(veri)
        except Exception as e:      # noqa: BLE001 - kullaniciya hatayi don
            self._gonder(200, json.dumps({"hata": str(e)}))
            return
        self._gonder(200, json.dumps(sonuc, ensure_ascii=False))


def calistir(port=8000, ac=False, host="127.0.0.1"):
    sunucu = ThreadingHTTPServer((host, port), Isleyici)
    url = f"http://{host}:{port}"
    print("=" * 62)
    print(f"CNC-Assistant web arayuzu hazir:  {url}")
    print("Tarayicinizda yukaridaki adresi acin.  Durdurmak icin Ctrl+C")
    print("=" * 62)
    if ac:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        sunucu.serve_forever()
    except KeyboardInterrupt:
        print("\nSunucu durduruldu.")
        sunucu.shutdown()
