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
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ezdxf

from . import dxf_processor as D
from . import gcode as GC
from . import geometry as GEO
from . import nesting as NEST
from . import project as P

_YUKLEME_DIZIN = os.path.join(tempfile.gettempdir(), "cnc_assistant_yukleme")

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
            "kontur": v["kontur"], "baslangic": v["baslangic"]}


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
        out.append({"id": i, "x": bx, "y": by, "bbox": GC.blok_bbox(blok),
                    "poligon": GC.blok_polygon(blok),
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


_DESTEK_YONU = {"sag-ust": (1.0, 1.0), "ust": (0.35, 1.0), "sag": (1.0, 0.35)}


def _dxf_opts(veri):
    return {
        "node_temizle": veri.get("node_temizle", True),
        "node_tol": float(veri.get("node_tol", 1e-6)),
        "destek_yonu": _DESTEK_YONU.get(veri.get("destek_yonu", "sag-ust"),
                                        (1.0, 1.0)),
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


def api_dxf_nest(veri):
    """DXF parcalarini tabakaya yeniden yerlestirir (nesting) ve kaydeder."""
    yol = veri["yol"]
    if not os.path.isfile(yol):
        return {"hata": f"Dosya yok: {yol}"}
    doc = ezdxf.readfile(yol)
    oncesi = D.baslangic_noktalari_ve_konturlar(doc)
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
    sonrasi = D.baslangic_noktalari_ve_konturlar(doc)
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
    "/api/dxf/onizle": api_dxf_onizle,
    "/api/dxf/kaydet": api_dxf_kaydet,
    "/api/dxf/nest": api_dxf_nest,
    "/api/gcode/yukle": api_gcode_yukle,
    "/api/gcode/sirala": api_gcode_sirala,
    "/api/gcode/dogrula": api_gcode_dogrula,
    "/api/gcode/kaydet": api_gcode_kaydet,
    "/api/gcode/karsilastir": api_gcode_karsilastir,
    "/api/gcode/tablar": api_gcode_tablar,
    "/api/yukle": api_yukle,
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
