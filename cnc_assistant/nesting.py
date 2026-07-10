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


# ======================================================================
# GELISMIS RASTER (gercek-sekil) NESTING
# ======================================================================
# Herhangi bir konteyner sekli (dikdortgen veya rastgele poligon + delikler),
# rotasyon, ve kenar boslugu / bicak payi (kerf) / parca boslugu ayarlarini
# destekler. Cakisma testleri FFT korelasyonu ile vektorize edilir.

import numpy as _np


def _poly_bbox_pts(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _dondur(poly, aci_derece, ox=0.0, oy=0.0):
    a = math.radians(aci_derece)
    ca, sa = math.cos(a), math.sin(a)
    return [((x - ox) * ca - (y - oy) * sa + ox,
             (x - ox) * sa + (y - oy) * ca + oy) for x, y in poly]


def _rasterize(poly, hucre, x0, y0, W, H):
    """Poligonu HxW boolean maskeye tarar (scanline). row r -> y ekseni
    (asagidan yukari), col c -> x ekseni."""
    mask = _np.zeros((H, W), dtype=bool)
    n = len(poly)
    for r in range(H):
        yc = y0 + (r + 0.5) * hucre
        xk = []
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            if (y1 <= yc < y2) or (y2 <= yc < y1):
                xk.append(x1 + (yc - y1) / (y2 - y1) * (x2 - x1))
        xk.sort()
        for k in range(0, len(xk) - 1, 2):
            ca = max(0, int(math.floor((xk[k] - x0) / hucre)))
            cb = min(W, int(math.ceil((xk[k + 1] - x0) / hucre)))
            if cb > ca:
                mask[r, ca:cb] = True
    return mask


def _disk_ofset(r):
    o = []
    for di in range(-r, r + 1):
        for dj in range(-r, r + 1):
            if di * di + dj * dj <= r * r:
                o.append((di, dj))
    return o


def _kaydir(mask, di, dj):
    out = _np.zeros_like(mask)
    H, W = mask.shape
    r0s, r0d = (di, 0) if di >= 0 else (0, -di)
    c0s, c0d = (dj, 0) if dj >= 0 else (0, -dj)
    rh = H - abs(di)
    cw = W - abs(dj)
    if rh > 0 and cw > 0:
        out[r0d:r0d + rh, c0d:c0d + cw] = mask[r0s:r0s + rh, c0s:c0s + cw]
    return out


def _dilate(mask, r):
    if r <= 0:
        return mask.copy()
    out = _np.zeros_like(mask)
    for di, dj in _disk_ofset(r):
        out |= _kaydir(mask, di, dj)
    return out


def _erode(mask, r):
    if r <= 0:
        return mask.copy()
    return ~_dilate(~mask, r)


def _korelasyon(A, K):
    """Capraz korelasyon (FFT): sonuc[i,j] = sum_{u,v} A[i+u,j+v]*K[u,v].
    Gecerli araligi [0..H-kh, 0..W-kw] icin dogru (dairesel sarma disinda)."""
    fa = _np.fft.rfft2(A)
    fk = _np.fft.rfft2(K, s=A.shape)
    return _np.fft.irfft2(fa * _np.conj(fk), s=A.shape)


def raster_nest(parcalar, tabakalar, ayar):
    """Gercek-sekil raster nesting.

    parcalar : [{"id","poly":[(x,y)...],"adet":n}]
    tabakalar: [{"poly":[(x,y)...]}]  (dikdortgen de 4 noktali poligon)
    ayar     : {kerf, bosluk(spacing), kenar, cozunurluk(mm/hucre), rotasyonlar:[derece...]}

    Doner: {"yerlesim":[ {"tabaka":i,"id":..,"aci":..,"poly":[(x,y)..]} ],
            "yerlesmeyen":[{"id","adet"}], "doluluk":[% per tabaka],
            "hucre":cozunurluk}
    """
    kerf = float(ayar.get("kerf", 0.0))
    bosluk = float(ayar.get("bosluk", 0.0))
    kenar = float(ayar.get("kenar", 0.0))
    rotasyonlar = ayar.get("rotasyonlar") or [0]

    # Cozunurluk: verilmezse en buyuk tabakaya gore otomatik (~350 hucre/kenar)
    hucre = float(ayar.get("cozunurluk", 0) or 0)
    if hucre <= 0:
        en_buyuk = 1.0
        for t in tabakalar:
            x0, y0, x1, y1 = _poly_bbox_pts(t["poly"])
            en_buyuk = max(en_buyuk, x1 - x0, y1 - y0)
        hucre = max(en_buyuk / 350.0, 0.3)

    parca_yari = (kerf + bosluk) / 2.0        # parca-parca aciklik yarisi
    r_dilate = max(0, int(round(parca_yari / hucre)))
    r_kenar = max(0, int(round(kenar / hucre)))

    # Yerlestirme sirasi: alani buyukten kucuge (parca ornekleri ac)
    ornekler = []
    for p in parcalar:
        x0, y0, x1, y1 = _poly_bbox_pts(p["poly"])
        alan = (x1 - x0) * (y1 - y0)
        for _ in range(int(p.get("adet", 1))):
            ornekler.append({"id": p["id"], "poly": p["poly"], "alan": alan})
    ornekler.sort(key=lambda o: o["alan"], reverse=True)

    # Her tabaka icin izgara/maske hazirla. Konteyner dikdortgen ise izgarayi
    # tam doldurur; erozyon icin 'disari' kalmadigindan izgarayi FALSE bir
    # kenarlik ile doldurup (pad) kenar boslugu erozyonunu dogru yapariz.
    pad = max(r_kenar, r_dilate) + 1
    tab_durum = []
    for t in tabakalar:
        x0, y0, x1, y1 = _poly_bbox_pts(t["poly"])
        Wc = max(1, int(math.ceil((x1 - x0) / hucre)))
        Hc = max(1, int(math.ceil((y1 - y0) / hucre)))
        W, H = Wc + 2 * pad, Hc + 2 * pad
        xg, yg = x0 - pad * hucre, y0 - pad * hucre
        C = _rasterize(t["poly"], hucre, xg, yg, W, H)
        U = _erode(C, r_kenar)                # kullanilabilir bolge
        tab_durum.append({"x0": xg, "y0": yg, "W": W, "H": H,
                          "U": U, "occ": _np.zeros((H, W), bool),
                          "notU_f": (~U).astype(_np.float64),
                          "kullanilan": 0})

    # rotasyon maske onbellegi: (id, aci) -> (true_mask, inflated_mask, kh, kw)
    onbellek = {}

    def maske_al(oid, poly, aci):
        anahtar = (oid, aci)
        if anahtar in onbellek:
            return onbellek[anahtar]
        rp = _dondur(poly, aci)
        x0, y0, x1, y1 = _poly_bbox_pts(rp)
        Wt = max(1, int(math.ceil((x1 - x0) / hucre)))
        Ht = max(1, int(math.ceil((y1 - y0) / hucre)))
        tm0 = _rasterize(rp, hucre, x0, y0, Wt, Ht)
        # Sisirme (clearance) icin maskeyi r_dilate kadar FALSE ile cevrele ki
        # dilate disari dogru buyuyebilsin (aksi halde bbox'a kirpilir -> parcalar
        # bosluksuz bitisir). true + inflated ayni sekil/orijini paylasir.
        p = r_dilate
        tm = _np.zeros((Ht + 2 * p, Wt + 2 * p), dtype=bool)
        tm[p:p + Ht, p:p + Wt] = tm0
        im = _dilate(tm, r_dilate)
        ox, oy = x0 - p * hucre, y0 - p * hucre     # padli maskenin data orijini
        onbellek[anahtar] = (tm, im, tm.shape[0], tm.shape[1], ox, oy)
        return onbellek[anahtar]

    yerlesim = []
    yerlesmeyen = {}
    for o in ornekler:
        kondu = False
        for ti, td in enumerate(tab_durum):
            en_iyi = None
            for aci in rotasyonlar:
                tm, im, kh, kw, rminx, rminy = maske_al(o["id"], o["poly"], aci)
                if kh > td["H"] or kw > td["W"]:
                    continue
                # cakismasiz konumlar: true_mask U icinde VE inflated occ ile cakismiyor
                c_ic = _korelasyon(td["notU_f"], tm.astype(_np.float64))
                c_ov = _korelasyon(td["occ"].astype(_np.float64),
                                   im.astype(_np.float64))
                uygun = (c_ic < 0.5) & (c_ov < 0.5)
                uygun[td["H"] - kh + 1:, :] = False
                uygun[:, td["W"] - kw + 1:] = False
                idx = _np.argwhere(uygun)
                if idx.size == 0:
                    continue
                # bottom-left: en kucuk row, sonra en kucuk col
                secim = idx[_np.lexsort((idx[:, 1], idx[:, 0]))][0]
                i, j = int(secim[0]), int(secim[1])
                if en_iyi is None or (i, j) < (en_iyi[0], en_iyi[1]):
                    en_iyi = (i, j, aci, tm, im, kh, kw, rminx, rminy)
            if en_iyi is None:
                continue
            i, j, aci, tm, im, kh, kw, rminx, rminy = en_iyi
            td["occ"][i:i + kh, j:j + kw] |= im
            td["kullanilan"] += int(tm.sum())
            # yerlesmis poligon (data koordinatlari)
            hedef_x = td["x0"] + j * hucre
            hedef_y = td["y0"] + i * hucre
            rp = _dondur(o["poly"], aci)
            tx, ty = hedef_x - rminx, hedef_y - rminy
            yerlesim.append({"tabaka": ti, "id": o["id"], "aci": aci,
                             "poly": [(x + tx, y + ty) for x, y in rp]})
            kondu = True
            break
        if not kondu:
            yerlesmeyen[o["id"]] = yerlesmeyen.get(o["id"], 0) + 1

    doluluk = []
    for td in tab_durum:
        toplam = int(td["U"].sum()) or 1
        doluluk.append(round(100.0 * td["kullanilan"] / toplam, 1))

    return {"yerlesim": yerlesim,
            "yerlesmeyen": [{"id": k, "adet": v} for k, v in yerlesmeyen.items()],
            "doluluk": doluluk, "hucre": hucre}
