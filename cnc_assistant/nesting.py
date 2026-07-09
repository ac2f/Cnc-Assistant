#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Basit yerlesim (nesting) optimizasyonu
=====================================
Parcalari, tabakada fire'i azaltacak sekilde bir tabaka genisligine gore
raf (shelf) algoritmasiyla yeniden yerlestirir. Parcalar yalnizca OTELENIR
(rigid translation) -> sekil ve olcu %100 korunur, sadece KONUM degisir.

Ic ice konturlar (orn. "O" harfinin dis+ic konturu, gobekteki adalar) tek
bir PARCA olarak birlikte tasinir (icerme grupmasi).

Not: Bu, dondurmesiz (rotation'suz) hafif bir yerlesimdir; kompleks poligon
no-fit hesabi yapmaz. Amaci makul, cakismasiz ve derli toplu bir dizilim.
"""

import math

from ezdxf import bbox as _ezbbox
from ezdxf import path as _ezpath


def _entity_bilgi(e):
    """Cizilebilir varligin (poligon, bbox) bilgisini doner; degilse None."""
    if e.dxftype() not in ("LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC",
                           "ELLIPSE", "SPLINE"):
        return None
    try:
        p = _ezpath.make_path(e)
        pts = [(v.x, v.y) for v in p.flattening(0.1)]
    except Exception:
        return None
    if len(pts) < 2:
        return None
    xs = [q[0] for q in pts]
    ys = [q[1] for q in pts]
    return {"e": e, "poly": pts,
            "bbox": (min(xs), min(ys), max(xs), max(ys))}


def _nokta_icinde(nokta, poly):
    n = len(poly)
    if n < 3:
        return False
    px, py = nokta
    icinde = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and \
           (px < (xj - xi) * (py - yi) / (yj - yi + 1e-18) + xi):
            icinde = not icinde
        j = i
    return icinde


def _merkez(poly):
    return (sum(p[0] for p in poly) / len(poly),
            sum(p[1] for p in poly) / len(poly))


def _parcalari_grupla(bilgiler):
    """Ic ice varliklari tek parcaya toplar. Her varlik icin, onu iceren en
    KUCUK varlik 'ebeveyn'dir; ebeveyni olmayanlar parca kokudur."""
    n = len(bilgiler)
    ebeveyn = [None] * n
    for i in range(n):
        bi = bilgiler[i]["bbox"]
        ai = (bi[2] - bi[0]) * (bi[3] - bi[1])
        en_kucuk_alan = None
        for j in range(n):
            if i == j:
                continue
            bj = bilgiler[j]["bbox"]
            aj = (bj[2] - bj[0]) * (bj[3] - bj[1])
            if aj <= ai:
                continue
            if bj[0] <= bi[0] and bi[2] <= bj[2] and \
               bj[1] <= bi[1] and bi[3] <= bj[3] and \
               _nokta_icinde(_merkez(bilgiler[i]["poly"]), bilgiler[j]["poly"]):
                if en_kucuk_alan is None or aj < en_kucuk_alan:
                    en_kucuk_alan = aj
                    ebeveyn[i] = j

    def kok(i):
        while ebeveyn[i] is not None:
            i = ebeveyn[i]
        return i

    gruplar = {}
    for i in range(n):
        gruplar.setdefault(kok(i), []).append(i)

    parcalar = []
    for kok_i, uyeler in gruplar.items():
        xs0 = [bilgiler[u]["bbox"][0] for u in uyeler]
        ys0 = [bilgiler[u]["bbox"][1] for u in uyeler]
        xs1 = [bilgiler[u]["bbox"][2] for u in uyeler]
        ys1 = [bilgiler[u]["bbox"][3] for u in uyeler]
        parcalar.append({"uyeler": [bilgiler[u]["e"] for u in uyeler],
                         "bbox": (min(xs0), min(ys0), max(xs1), max(ys1))})
    return parcalar


def nest_doc(doc, tabaka_genislik=None, bosluk=5.0, kenar=5.0):
    """Modelspace'teki parcalari raf algoritmasiyla yeniden yerlestirir.
    tabaka_genislik None ise otomatik (toplam alanin karekokune yakin) secilir.
    Doner: {yerlesim:[...], tabaka:(w,h), parca_sayisi, cevre_korundu}."""
    msp = doc.modelspace()
    bilgiler = [b for b in (_entity_bilgi(e) for e in msp) if b]
    if not bilgiler:
        return {"hata": "Yerlestirilecek kapali varlik yok.", "parca_sayisi": 0}

    cevre_once = _toplam_cevre(bilgiler)
    parcalar = _parcalari_grupla(bilgiler)

    # tabaka genisligi
    if not tabaka_genislik or tabaka_genislik <= 0:
        toplam_alan = sum((p["bbox"][2] - p["bbox"][0]) *
                          (p["bbox"][3] - p["bbox"][1]) for p in parcalar)
        en_genis = max(p["bbox"][2] - p["bbox"][0] for p in parcalar)
        tabaka_genislik = max(en_genis + 2 * kenar,
                              math.sqrt(max(toplam_alan, 1e-9)) * 1.3)

    # yuksekten alcaga sirala (raf yerlesimi)
    parcalar.sort(key=lambda p: (p["bbox"][3] - p["bbox"][1]), reverse=True)

    imx = kenar        # imlec x
    imy = kenar        # imlec y (rafin alt kenari)
    raf_h = 0.0
    max_x = 0.0
    yerlesim = []
    for p in parcalar:
        x0, y0, x1, y1 = p["bbox"]
        w, h = x1 - x0, y1 - y0
        if imx > kenar and (imx + w) > (tabaka_genislik - kenar):
            # yeni raf
            imx = kenar
            imy += raf_h + bosluk
            raf_h = 0.0
        dx = imx - x0
        dy = imy - y0
        for e in p["uyeler"]:
            try:
                e.translate(dx, dy, 0)
            except Exception:
                pass
        yerlesim.append({"eski": (x0, y0, x1, y1),
                         "yeni": (imx, imy, imx + w, imy + h)})
        imx += w + bosluk
        raf_h = max(raf_h, h)
        max_x = max(max_x, imx)

    tabaka = (max(max_x - bosluk + kenar, tabaka_genislik), imy + raf_h + kenar)

    # cevre (uzunluk) korundu mu? (oteleme uzunlugu bozmaz)
    bilgiler2 = [b for b in (_entity_bilgi(e) for e in msp) if b]
    cevre_sonra = _toplam_cevre(bilgiler2)
    korundu = cevre_once <= 1e-9 or abs(cevre_once - cevre_sonra) / cevre_once < 1e-6

    return {"yerlesim": yerlesim, "tabaka": tabaka,
            "parca_sayisi": len(parcalar), "cevre_korundu": korundu}


def _toplam_cevre(bilgiler):
    L = 0.0
    for b in bilgiler:
        poly = b["poly"]
        for i in range(len(poly) - 1):
            L += math.hypot(poly[i + 1][0] - poly[i][0],
                            poly[i + 1][1] - poly[i][1])
    return L
