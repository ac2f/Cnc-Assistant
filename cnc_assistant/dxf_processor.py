#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DXF isleme katmani
==================
ezdxf uzerinde calisir:

  Adim 1: Once GEREKSIZ NODE'LARI temizler (geometri korunur), sonra
          kapali vektorlerin baslangic (lead-in) noktasini hedef bolgeye
          tasir.
  Adim 2: Buyuk/riskli parcalari konsola loglar (DXF'e cizim eklenmez).
  Dogrulama: Kaydedilen dosya yeniden acilip orijinalle (bbox + toplam
          cevre) karsilastirilir; en ufak geometrik sapma uyari verir.

Tasarim ilkesi: olculer ASLA degismez. Node temizligi ve baslangic kaydirma
yalnizca vertex SIRASINI / SAYISINI degistirir, sekli degil.
"""

import math

import ezdxf
from ezdxf import bbox as _ezbbox
from ezdxf import path as _ezpath
from ezdxf.path import Command as _Cmd

from . import geometry as G


# ----------------------------------------------------------------------
# Kapalilik testleri
# ----------------------------------------------------------------------

def _kapali_mi_lwpolyline(pl):
    if pl.closed:
        return True
    pts = pl.get_points("xy")
    if len(pts) >= 3:
        return math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-9
    return False


# ----------------------------------------------------------------------
# LWPOLYLINE: node temizligi + baslangic kaydirma
# ----------------------------------------------------------------------

def _ocs_yon_duzelt(entity, opts):
    """Varliktaki EXTRUSION Z<0 (aynalanmis OCS) ise yatay yon (dx) TERS
    cevrilmis bir opts kopyasi doner. LWPOLYLINE/POLYLINE noktalari OCS'de
    okunur; extrusion (0,0,-1) oldugunda OCS-X ekseni WCS'de aynalidir
    (WCS_x = -OCS_x). Bu durumda 'sag-ust' kurali OCS'de dogru tarafa denk
    gelsin diye dx isareti cevrilir (Y degismez). Boylece dis dunyada
    (gordugumuz cizimde) baslangic DAIMA gercek sag-uste gider -- hicbir
    yerde ayna bozukluğu kalmaz."""
    try:
        ez = entity.dxf.get("extrusion", (0.0, 0.0, 1.0))
        z = ez[2] if ez is not None else 1.0
    except Exception:
        z = 1.0
    if z < 0:
        o = dict(opts)
        d = o.get("destek_yonu", G.DESTEK_YONU) or G.DESTEK_YONU
        o["destek_yonu"] = (-d[0], d[1])
        return o
    return opts


# DXF $INSUNITS kodu -> insan/makine okunur birim adi. (Ham kodu disari
# vermek yaniltici oluyordu: rapora "birim": 4 diye dusuyordu.)
INSUNITS = {0: None, 1: "inch", 2: "feet", 4: "mm", 5: "cm", 6: "m",
            8: "microinch", 9: "mil", 10: "yard", 11: "angstrom",
            12: "nanometre", 13: "mikron", 14: "dm", 15: "dam",
            16: "hm", 17: "gm", 18: "au", 19: "isik_yili", 20: "parsek"}


def birim_adi(kod):
    """$INSUNITS kodunu birim adina cevirir (bilinmiyorsa None)."""
    try:
        return INSUNITS.get(int(kod))
    except (TypeError, ValueError):
        return None


def _segment_orani(a, b, p):
    """`p` noktasinin a->b segmenti uzerindeki parametresi (0..1). Lead-in
    node'u segmenti bolerken genislik/yukseklik interpolasyonu icin gerekir."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 <= 1e-18:
        return 0.0
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2
    return max(0.0, min(1.0, t))


def lwpolyline_optimize_et(pl, opts):
    """Kapali LWPOLYLINE icin: once gereksiz node'lari temizler, sonra
    baslangici hedef bolgeye tasir. Doner: (degisti_mi, silinen_node)."""
    opts = _ocs_yon_duzelt(pl, opts)     # aynali (extrusion Z<0) varliklarda dx ters
    fmt = "xyseb"
    pts = list(pl.get_points(fmt))

    acik_kapali = False
    if not pl.closed:                  # ilk=son nokta ile kapatilmis
        pts = pts[:-1]
        acik_kapali = True

    if len(pts) < 3:
        return False, 0

    # 1) NODE SADELESTIRME
    silinen = 0
    if opts.get("node_temizle", True):
        pts, silinen = G.node_sadelestir(pts, kapali=True,
                                         tol=opts.get("node_tol", G.NODE_TOL))

    if len(pts) < 3:
        return (silinen > 0), silinen

    # 2) BASLANGIC HEDEFI
    i, _uzun, eklenen = G.baslangic_indeksi_belirle(pts, **opts)
    if i is None and eklenen is not None:
        seg_idx, yeni_pt = eklenen
        # Lead-in node'u DUZ bir segmenti boler. Segment genislik (taper)
        # tasiyorsa bolme noktasindaki genislik interpole edilmeli; aksi halde
        # 0/0 yazmak taper'i (dolayisiyla gercek formu) bozar.
        a = pts[seg_idx]
        b = pts[(seg_idx + 1) % len(pts)]
        t = _segment_orani(a, b, yeni_pt)
        wt = a[2] + t * (a[3] - a[2])
        pts[seg_idx] = (a[0], a[1], a[2], wt, a[4])
        pts.insert(seg_idx + 1, (yeni_pt[0], yeni_pt[1], wt, a[3], 0.0))
        i = seg_idx + 1

    degisti = silinen > 0
    if i and i != 0:                   # 0 ise rotasyon gereksiz
        pts = pts[i:] + pts[:i]
        degisti = True

    if not degisti:
        return False, silinen

    if acik_kapali:
        pts = pts + [pts[0]]
    pl.set_points(pts, format=fmt)
    return True, silinen


# ----------------------------------------------------------------------
# ELLE BASLANGIC (LEAD-IN) TASIMA
# ----------------------------------------------------------------------
#
# Kullanicinin isaretledigi noktaya gore kapali bir vektorun baslangicini
# tasir. GEOMETRI DEGISMEZ: vertex listesi dondurulur (rotate); gerekiyorsa
# DUZ bir segment tam hedefte ikiye bolunur. Yay (bulge) segmentleri ASLA
# bolunmez -> hedef yaya denk gelirse en yakin MEVCUT vertex kullanilir.

# Hedefe bu kadar yakin (bbox kosegeninin orani) bir vertex varsa yeni node
# acmak yerine o vertex kullanilir.
ELLE_KABUL_TOL = 0.02


def _en_yakin_konum(pts, hedef, bol=True, kabul_orani=ELLE_KABUL_TOL):
    """Hedefe en yakin kontur konumunu bulur.

    Doner: (bas_idx, yeni_pts, yeni_node)
      bas_idx  : dondurmenin baslayacagi indeks
      yeni_pts : (gerekiyorsa segment bolunmus) nokta listesi
      yeni_node: kontur uzerinde yeni bir node acildi mi
    """
    n = len(pts)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    kabul = diag * kabul_orani

    k = min(range(n), key=lambda i: (pts[i][0] - hedef[0]) ** 2
            + (pts[i][1] - hedef[1]) ** 2)
    k_uz = math.hypot(pts[k][0] - hedef[0], pts[k][1] - hedef[1])

    en_iyi = None
    if bol:
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            if abs(a[4]) > 1e-9:                  # yay segmenti: bolunmez
                continue
            t = _segment_orani(a, b, hedef)
            if not (1e-9 < t < 1 - 1e-9):
                continue
            cx = a[0] + t * (b[0] - a[0])
            cy = a[1] + t * (b[1] - a[1])
            d = math.hypot(cx - hedef[0], cy - hedef[1])
            if en_iyi is None or d < en_iyi[3]:
                en_iyi = (i, (cx, cy), t, d)

    if en_iyi is not None and en_iyi[3] < k_uz and k_uz > kabul:
        i, c, t, _d = en_iyi
        a = pts[i]
        wt = a[2] + t * (a[3] - a[2])             # genislik interpolasyonu
        yeni = list(pts)
        yeni[i] = (a[0], a[1], a[2], wt) + tuple(a[4:])
        ek = (c[0], c[1], wt, a[3], 0.0) + tuple(a[5:])
        yeni.insert(i + 1, ek)
        return i + 1, yeni, True
    return k, list(pts), False


def lwpolyline_baslangic_tasi(pl, hedef, bol=True):
    """Kapali LWPOLYLINE'in baslangicini hedefe en yakin kontur konumuna
    tasir. Doner: {degisti, baslangic, yeni_node} veya {hata}."""
    fmt = "xyseb"
    pts = list(pl.get_points(fmt))
    acik_kapali = False
    if not pl.closed:
        if len(pts) >= 3 and math.hypot(pts[0][0] - pts[-1][0],
                                        pts[0][1] - pts[-1][1]) < 1e-9:
            pts = pts[:-1]
            acik_kapali = True
        else:
            return {"hata": "Kapali olmayan vektorun baslangici tasinamaz."}
    if len(pts) < 3:
        return {"hata": "Vektorde yeterli node yok."}

    eski = [pts[0][0], pts[0][1]]
    bas, pts, yeni_node = _en_yakin_konum(pts, hedef, bol)
    if bas == 0 and not yeni_node:
        return {"degisti": False, "baslangic": eski, "yeni_node": False,
                "eski_baslangic": eski}
    pts = pts[bas:] + pts[:bas]
    if acik_kapali:
        pts = pts + [pts[0]]
    pl.set_points(pts, format=fmt)
    return {"degisti": True, "baslangic": [pts[0][0], pts[0][1]],
            "yeni_node": yeni_node, "eski_baslangic": eski}


def polyline2d_baslangic_tasi(pl, hedef, bol=True):
    """Kapali klasik 2D POLYLINE icin ayni islem (Z ve genislikler korunur)."""
    vlist = list(pl.vertices)
    if not pl.is_closed or len(vlist) < 3:
        return {"hata": "Kapali olmayan vektorun baslangici tasinamaz."}

    def vpt(v):
        loc = v.dxf.location
        return (loc.x, loc.y, v.dxf.get("start_width", 0.0),
                v.dxf.get("end_width", 0.0), v.dxf.get("bulge", 0.0), loc.z)

    pts = [vpt(v) for v in vlist]
    eski = [pts[0][0], pts[0][1]]
    bas, yeni_pts, yeni_node = _en_yakin_konum(pts, hedef, bol)
    if bas == 0 and not yeni_node:
        return {"degisti": False, "baslangic": eski, "yeni_node": False,
                "eski_baslangic": eski}

    if yeni_node:                                  # bolunen segmente vertex ekle
        i = bas - 1
        p = yeni_pts[bas]
        kaynak = vlist[i]
        yv = kaynak.copy()
        yv.dxf.location = (p[0], p[1], p[5] if len(p) > 5 else 0.0)
        yv.dxf.bulge = 0.0
        yv.dxf.start_width, yv.dxf.end_width = p[2], p[3]
        kaynak.dxf.end_width = p[2]
        pl.doc.entitydb.add(yv)
        yv.dxf.owner = kaynak.dxf.owner
        pl.vertices.insert(bas, yv)
        vlist = list(pl.vertices)

    veriler = [(p[0], p[1], p[5] if len(p) > 5 else 0.0, p[4], p[2], p[3])
               for p in yeni_pts]
    veriler = veriler[bas:] + veriler[:bas]
    for v, (x, y, z, bulge, sw, ew) in zip(vlist, veriler):
        v.dxf.location = (x, y, z)
        v.dxf.bulge = bulge
        v.dxf.start_width, v.dxf.end_width = sw, ew
    return {"degisti": True, "baslangic": [veriler[0][0], veriler[0][1]],
            "yeni_node": yeni_node, "eski_baslangic": eski}


def varlik_baslangic_tasi(doc, handle, hedef, bol=True):
    """`handle` ile belirtilen kapali vektorun baslangicini tasir."""
    e = None
    for x in doc.modelspace():
        if x.dxf.handle == handle:
            e = x
            break
    if e is None:
        return {"hata": f"Vektor bulunamadi: {handle}"}
    t = e.dxftype()
    if t == "LWPOLYLINE":
        return lwpolyline_baslangic_tasi(e, hedef, bol)
    if t == "POLYLINE":
        return polyline2d_baslangic_tasi(e, hedef, bol)
    return {"hata": f"{t} tipinde baslangic tasinamaz (parametrik varlik)."}


# ----------------------------------------------------------------------
# Klasik 2D POLYLINE: node temizligi + baslangic kaydirma
# ----------------------------------------------------------------------

def polyline2d_optimize_et(pl, opts):
    if not pl.is_closed or pl.get_mode() != "AcDb2dPolyline":
        return False, 0
    opts = _ocs_yon_duzelt(pl, opts)     # aynali (extrusion Z<0) varliklarda dx ters
    vlist = list(pl.vertices)
    if len(vlist) < 3:
        return False, 0

    # NOT: 6. eleman Z'dir (yukseklik/elevation). Geometri katmani yalnizca
    # 0..4 indekslerini kullanir; Z burada TASINIR ki hicbir vertex istemeden
    # Z=0 duzlemine dusmesin (koordinat degisikligi olurdu).
    def vpt(v):
        loc = v.dxf.location
        return (loc.x, loc.y,
                v.dxf.get("start_width", 0.0),
                v.dxf.get("end_width", 0.0),
                v.dxf.get("bulge", 0.0),
                loc.z)

    pts = [vpt(v) for v in vlist]

    # 1) NODE SADELESTIRME -> hangi indeksler kalacak?
    silinen = 0
    if opts.get("node_temizle", True):
        sade, silinen = G.node_sadelestir(pts, kapali=True,
                                          tol=opts.get("node_tol", G.NODE_TOL))
        if silinen > 0:
            # Kalan noktalari orijinal vertex'lerle eslestir (konum esitligi)
            kalan_idx = _eslestir_kalanlar(pts, sade)
            silinecek = [k for k in range(len(vlist)) if k not in kalan_idx]
            for k in sorted(silinecek, reverse=True):
                del pl.vertices[k]
            vlist = list(pl.vertices)
            pts = [vpt(v) for v in vlist]

    if len(vlist) < 3:
        return (silinen > 0), silinen

    # 2) BASLANGIC HEDEFI
    i, _uzun, eklenen = G.baslangic_indeksi_belirle(pts, **opts)
    if i is None and eklenen is not None:
        seg_idx, yeni_pt = eklenen
        a = pts[seg_idx]
        b = pts[(seg_idx + 1) % len(pts)]
        t = _segment_orani(a, b, yeni_pt)
        wt = a[2] + t * (a[3] - a[2])          # bolme noktasindaki genislik
        z = a[5] + t * (b[5] - a[5])           # yukseklik de interpole edilir
        kaynak_v = vlist[seg_idx]
        yeni_v = kaynak_v.copy()
        yeni_v.dxf.location = (yeni_pt[0], yeni_pt[1], z)
        yeni_v.dxf.bulge = 0.0                 # bolunen segment DAIMA duzdur
        yeni_v.dxf.start_width = wt
        yeni_v.dxf.end_width = a[3]
        kaynak_v.dxf.end_width = wt            # taper bolme noktasina cekilir
        pl.doc.entitydb.add(yeni_v)
        yeni_v.dxf.owner = kaynak_v.dxf.owner
        pl.vertices.insert(seg_idx + 1, yeni_v)
        vlist = list(pl.vertices)
        pts = [vpt(v) for v in vlist]
        i = seg_idx + 1

    degisti = silinen > 0
    if i:
        # Vertex NESNELERI yerinde kalir; yalnizca tasidiklari veri dondurulur.
        # (ezdxf 1.x'te `Polyline.vertices` salt-okunur bir ozelliktir; nesne
        # listesini degistirmek yerine verinin donmesi hem guvenli hem de
        # katman/renk gibi vertex ozelliklerini korur.)
        veriler = [(p[0], p[1], p[5], p[4], p[2], p[3]) for p in pts]
        veriler = veriler[i:] + veriler[:i]
        for v, (x, y, z, bulge, sw, ew) in zip(vlist, veriler):
            v.dxf.location = (x, y, z)
            v.dxf.bulge = bulge
            v.dxf.start_width = sw
            v.dxf.end_width = ew
        degisti = True

    return degisti, silinen


def _eslestir_kalanlar(orijinal, sade, tol=1e-9):
    """Sadelestirilmis noktalarin orijinal listedeki indekslerini bulur
    (konum esitligiyle, sirayi koruyarak)."""
    kalan = []
    j = 0
    for idx, p in enumerate(orijinal):
        if j < len(sade) and \
           abs(p[0] - sade[j][0]) <= tol and abs(p[1] - sade[j][1]) <= tol:
            kalan.append(idx)
            j += 1
    return set(kalan)


# ----------------------------------------------------------------------
# CIRCLE -> es-geometrik 2 yayli LWPOLYLINE
# ----------------------------------------------------------------------

def cember_baslangic_kaydir(circle, msp):
    """CIRCLE baslangic noktasi tasimaz; CAM kendi secer. Kontrol icin cember,
    matematiksel olarak birebir ayni iki 180 derecelik yaydan (bulge=1.0)
    olusan kapali LWPOLYLINE ile degistirilir. Baslangic: SAG-UST 45 derece."""
    cx, cy = circle.dxf.center.x, circle.dxf.center.y
    r = circle.dxf.radius
    k = r / math.sqrt(2.0)
    pl = msp.add_lwpolyline(
        [(cx + k, cy + k, 0.0, 0.0, 1.0),
         (cx - k, cy - k, 0.0, 0.0, 1.0)],
        format="xyseb",
        dxfattribs={
            "layer": circle.dxf.layer,
            "closed": True,
            "color": circle.dxf.get("color", 256),
            "linetype": circle.dxf.get("linetype", "BYLAYER"),
        })
    msp.delete_entity(circle)
    return pl


# ----------------------------------------------------------------------
# ADIM 1 - ana akis
# ----------------------------------------------------------------------

def adim1_baslangic_optimizasyonu(msp, opts):
    kaydirilan, cember, toplam_silinen, atlanan = 0, 0, 0, []
    # Butunluk denetimi icin: dokunulan varliklarin handle'lari ve cember ->
    # polyline donusum haritasi (yeni handle -> eski CIRCLE handle).
    dokunulan, donusen = set(), {}
    for e in list(msp):
        t = e.dxftype()
        if t == "LWPOLYLINE":
            if _kapali_mi_lwpolyline(e):
                d, s = lwpolyline_optimize_et(e, opts)
                toplam_silinen += s
                if d or s:
                    dokunulan.add(e.dxf.handle)
                if d:
                    kaydirilan += 1
        elif t == "POLYLINE":
            d, s = polyline2d_optimize_et(e, opts)
            toplam_silinen += s
            if d or s:
                dokunulan.add(e.dxf.handle)
            if d:
                kaydirilan += 1
        elif t == "CIRCLE":
            eski = e.dxf.handle
            yeni = cember_baslangic_kaydir(e, msp)
            donusen[yeni.dxf.handle] = eski
            dokunulan.add(yeni.dxf.handle)
            cember += 1
        elif t in ("SPLINE", "ELLIPSE") and getattr(e, "closed", False):
            atlanan.append((t, e.dxf.handle))

    print(f"[Adim 1] Baslangici hedef bolgeye tasinan polyline: {kaydirilan}")
    if toplam_silinen:
        print(f"[Adim 1] Geometriyi bozmadan kaldirilan gereksiz node: "
              f"{toplam_silinen}")
    if cember:
        print(f"[Adim 1] Es-geometrik 2-yayli polyline'a cevrilen cember: "
              f"{cember} (form/olcu birebir ayni)")
    for t, h in atlanan:
        print(f"[Adim 1] NOT: Kapali {t} (handle {h}) parametrik oldugundan "
              f"baslangici guvenle kaydirilamaz; oldugu gibi korundu.")
    return {"kaydirilan": kaydirilan, "silinen_node": toplam_silinen,
            "cember": cember, "dokunulan": dokunulan, "donusen": donusen}


# ----------------------------------------------------------------------
# VEKTOR-BAZLI (HER BIR VEKTOR ICIN) BUTUNLUK DOGRULAMA
# ----------------------------------------------------------------------
#
# Dokuman geneli (toplam cevre + genel bbox) kontrolu TEK BASINA yetmez:
# bir vektorun bir koordinati kayarken toplam cevre/bbox degismeyebilir
# (orn. bir vertex kendi konturu boyunca kayarsa, ya da iki parca birbirini
# telafi ederse). Bu yuzden HER VEKTOR kendi icinde, ONCESI/SONRASI olarak
# karsilastirilir:
#
#   1) bbox         - parca kaydi/olcegi degisti mi?
#   2) cevre        - kontur uzunlugu degisti mi?
#   3) alan         - kapali form degisti mi?
#   4) nokta-bazli  - SONRASI'nin her noktasi ONCESI konturu UZERINDE mi
#                     (ve tersi)? Baslangic noktasi dondugunde/node
#                     eklenip silindiginde bile bu test gecer; ama tek bir
#                     koordinat oynadiginda ANINDA yakalanir.
#
# (4) asil koruma; (1..3) ucuz on-elemedir.

# Egrileri duz parcalara acarken kabul edilen azami sapma (cizim birimi).
BUTUNLUK_FLATTEN = 0.005
# Nokta-bazli karsilastirmada kabul edilen azami sapma. Iki farkli fazda
# duzlestirilmis AYNI egri arasindaki olcum artefaktini (<= 2*FLATTEN)
# absorbe eder, gercek koordinat kaymasini yakalar.
BUTUNLUK_TOL = 0.02


def _kontur_noktalari(e, sapma=BUTUNLUK_FLATTEN):
    """Varligi duz cizgi parcalarina acar; [(x, y), ...] doner."""
    p = _ezpath.make_path(e)
    if p.start is None:
        return []
    return [(v.x, v.y) for v in p.flattening(sapma)]


def _kontur_haritasi(doc, sapma=BUTUNLUK_FLATTEN):
    """{handle: (tip, [(x, y), ...])} - her cizilebilir varligin konturu."""
    harita = {}
    for e in doc.modelspace():
        if e.dxftype() not in ("LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC",
                               "LINE", "SPLINE", "ELLIPSE"):
            continue
        try:
            pts = _kontur_noktalari(e, sapma)
        except Exception:
            continue
        if pts:
            harita[e.dxf.handle] = (e.dxftype(), pts)
    return harita


def _kontur_olculeri(pts):
    """(bbox, cevre, alan) - kapali kontur varsayimiyla."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    n = len(pts)
    cevre = 0.0
    alan = 0.0
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        cevre += math.hypot(b[0] - a[0], b[1] - a[1])
        alan += a[0] * b[1] - b[0] * a[1]
    return bbox, cevre, abs(alan) / 2.0


class _KonturIndeks:
    """Bir konturun segmentleri uzerinde duzgun-izgara (uniform grid) indeksi.

    Nokta-kontur mesafesi sorgusunu segment sayisindan bagimsiz hale getirir;
    boylece binlerce vektorlu buyuk tabakalarda da butunluk denetimi hizli
    kalir."""

    def __init__(self, pts, hucre):
        self.hucre = max(hucre, 1e-9)
        self.kova = {}
        n = len(pts)
        self.seg = []
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            k = len(self.seg)
            self.seg.append((a[0], a[1], b[0], b[1]))
            # Segmentin gectigi tum hucrelere kaydet (bbox tarama yeterli).
            i0, j0 = self._hucre(min(a[0], b[0]), min(a[1], b[1]))
            i1, j1 = self._hucre(max(a[0], b[0]), max(a[1], b[1]))
            for ii in range(i0, i1 + 1):
                for jj in range(j0, j1 + 1):
                    self.kova.setdefault((ii, jj), []).append(k)

    def _hucre(self, x, y):
        return int(math.floor(x / self.hucre)), int(math.floor(y / self.hucre))

    # Halka taramasi icin ust sinir: hucre boyu seklin kosegenine gore
    # secildiginden pratikte birkac halkada biter; bu yalnizca emniyet freni.
    AZAMI_HALKA = 96

    def uzaklik(self, x, y):
        """(x, y) noktasinin kontura EN KISA uzakligi (her zaman sonlu).

        Sorgu hucresinden disari dogru halka halka taranir. `halka` halkasi
        tarandiginda `halka * hucre` mesafesindeki tum segmentler gorulmus
        olur; bulunan en iyi deger bu siniri asmiyorsa kesin sonuctur."""
        ci, cj = self._hucre(x, y)
        en_iyi = float("inf")
        for halka in range(self.AZAMI_HALKA + 1):
            for ii in range(ci - halka, ci + halka + 1):
                for jj in range(cj - halka, cj + halka + 1):
                    if halka and abs(ii - ci) != halka and abs(jj - cj) != halka:
                        continue          # ic halkalar zaten tarandi
                    for k in self.kova.get((ii, jj), ()):
                        ax, ay, bx, by = self.seg[k]
                        d = _nokta_seg_uzaklik(x, y, ax, ay, bx, by)
                        if d < en_iyi:
                            en_iyi = d
            if en_iyi <= halka * self.hucre:
                return en_iyi             # kesin: daha yakini olamaz
        if en_iyi == float("inf"):        # olmamali (kontur bos degil)
            return self.AZAMI_HALKA * self.hucre
        return en_iyi


def _nokta_seg_uzaklik(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 <= 1e-18 else ((px - ax) * dx + (py - ay) * dy) / L2
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _azami_sapma(indeks, pts, tol, ornek=None):
    """`pts` noktalarinin indekslenmis kontura AZAMI uzakligi (tek yon)."""
    n = len(pts)
    if not n:
        return 0.0
    if ornek and n > ornek:
        adim = n / float(ornek)
        secili = [pts[int(i * adim)] for i in range(ornek)]
    else:
        secili = pts
    en = 0.0
    for x, y in secili:
        d = indeks.uzaklik(x, y)
        if d > en:
            en = d
            if en > tol * 50:            # acikca bozuk; devam etmeye gerek yok
                break
    return en


def varlik_butunluk(once_harita, sonra_harita, dokunulan=None, donusen=None,
                    tol=BUTUNLUK_TOL, ornek=256):
    """HER VEKTOR icin oncesi/sonrasi geometrik esligi dogrular.

    once_harita/sonra_harita : `_kontur_haritasi` ciktilari
    dokunulan : optimizasyonun degistirdigi handle'lar (None = hepsi)
    donusen   : {yeni_handle: eski_handle} (CIRCLE -> polyline donusumu)

    Doner: {"ok": bool, "kontrol": int, "sapan": [{handle, tip, neden,
            sapma, bbox_fark, cevre_fark, alan_fark}, ...]}
    """
    donusen = donusen or {}
    sapan = []
    kontrol = 0

    for handle, (tip, sonra_pts) in sonra_harita.items():
        eski_handle = donusen.get(handle, handle)
        onceki = once_harita.get(eski_handle)
        if onceki is None:
            # Optimizasyon yeni bir varlik uretmez; ureten tek yer CIRCLE
            # donusumudur ve o `donusen` ile eslesir.
            sapan.append({"handle": handle, "tip": tip,
                          "neden": "oncesinde karsiligi yok", "sapma": None})
            continue
        if dokunulan is not None and handle not in dokunulan:
            continue                     # dokunulmamis varlik: bire bir ayni
        kontrol += 1
        once_pts = onceki[1]

        b1, c1, a1 = _kontur_olculeri(once_pts)
        b2, c2, a2 = _kontur_olculeri(sonra_pts)
        bbox_fark = max(abs(x - y) for x, y in zip(b1, b2))
        cevre_fark = abs(c1 - c2)
        alan_fark = abs(a1 - a2)

        kose = math.hypot(b1[2] - b1[0], b1[3] - b1[1]) or 1.0
        # Nokta-bazli iki yonlu kontrol: sonrasi -> oncesi ve oncesi -> sonrasi.
        hucre = max(kose / 32.0, tol * 4)
        i_once = _KonturIndeks(once_pts, hucre)
        i_sonra = _KonturIndeks(sonra_pts, hucre)
        sapma = max(_azami_sapma(i_once, sonra_pts, tol, ornek),
                    _azami_sapma(i_sonra, once_pts, tol, ornek))

        nedenler = []
        if sapma > tol:
            nedenler.append(f"kontur {sapma:.4f} birim kaydi")
        if bbox_fark > tol:
            nedenler.append(f"bbox {bbox_fark:.4f} degisti")
        if c1 > 1e-9 and cevre_fark / c1 > 1e-3 and cevre_fark > tol:
            nedenler.append(f"cevre {c1:.4f} -> {c2:.4f}")
        if a1 > 1e-9 and alan_fark / a1 > 1e-3 and alan_fark > tol * kose:
            nedenler.append(f"alan {a1:.4f} -> {a2:.4f}")
        if nedenler:
            sapan.append({"handle": handle, "tip": tip,
                          "neden": "; ".join(nedenler),
                          "sapma": round(sapma, 6),
                          "bbox_fark": round(bbox_fark, 6),
                          "cevre_fark": round(cevre_fark, 6),
                          "alan_fark": round(alan_fark, 6)})

    # Kaybolan varliklar (donusum disinda hicbir varlik kaybolmamali)
    kalanlar = set(sonra_harita) | {donusen[h] for h in donusen if h in sonra_harita}
    for handle, (tip, _pts) in once_harita.items():
        if handle not in kalanlar:
            sapan.append({"handle": handle, "tip": tip,
                          "neden": "varlik kayboldu", "sapma": None})

    return {"ok": not sapan, "kontrol": kontrol, "sapan": sapan}


# ----------------------------------------------------------------------
# GEOMETRIK BUTUNLUK DOGRULAMA (dokuman geneli)
# ----------------------------------------------------------------------

def _toplam_yol_uzunlugu(doc):
    L = 0.0
    for e in doc.modelspace():
        if e.dxftype() in ("LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC",
                           "LINE", "SPLINE", "ELLIPSE"):
            try:
                p = _ezpath.make_path(e)
                pts = list(p.flattening(1e-4))
                for i in range(len(pts) - 1):
                    L += (pts[i + 1] - pts[i]).magnitude
            except Exception:
                pass
    return L


def butunluk_dogrula(orijinal_yol, cikti_yol):
    """Kaydedilen dosyayi yeniden acip orijinalle karsilastirir."""
    a = ezdxf.readfile(orijinal_yol)
    b = ezdxf.readfile(cikti_yol)
    ba = _ezbbox.extents(a.modelspace())
    bc = _ezbbox.extents(b.modelspace())

    # CIRCLE -> 2-yayli polyline donusumu birebir; ezdxf flatten yontemi
    # ~5e-5 olcum artefakti verir. Cember varsa bu artefakti absorbe et.
    cember_var = any(e.dxftype() == "CIRCLE" for e in a.modelspace())
    cevre_tol, bbox_tol = (1e-3, 0.05) if cember_var else (1e-6, 1e-7)

    sorun = []
    if ba.has_data and bc.has_data:
        for v1, v2 in ((ba.extmin, bc.extmin), (ba.extmax, bc.extmax)):
            if abs(v1.x - v2.x) > bbox_tol or abs(v1.y - v2.y) > bbox_tol:
                sorun.append("bounding box farkli")
                break
    la, lb = _toplam_yol_uzunlugu(a), _toplam_yol_uzunlugu(b)
    if la > 0 and abs(la - lb) / la > cevre_tol:
        sorun.append(f"toplam cevre farkli ({la:.6f} -> {lb:.6f})")

    if sorun:
        print("[Dogrulama] UYARI! Geometrik fark tespit edildi: "
              + "; ".join(sorun))
        return False
    print(f"[Dogrulama] OK - bbox ve toplam cevre ({la:.4f}) korundu.")
    return True


# ----------------------------------------------------------------------
# ADIM 2 - riskli parca uyarisi
# ----------------------------------------------------------------------

def _varlik_bbox(e):
    try:
        box = _ezbbox.extents([e])
        if box.has_data:
            return (box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y)
    except Exception:
        pass
    return None


def adim2_riskli_parca_uyarisi(msp, alan_orani, boyut_orani):
    genel = _ezbbox.extents(msp)
    if not genel.has_data:
        print("[Adim 2] DXF icinde olculebilir varlik bulunamadi.")
        return []

    tab_w = genel.extmax.x - genel.extmin.x
    tab_h = genel.extmax.y - genel.extmin.y
    tab_alan = tab_w * tab_h
    print(f"[Adim 2] Tabaka olcusu otomatik tespit edildi: "
          f"{tab_w:.2f} x {tab_h:.2f} (alan: {tab_alan:.2f})")

    riskli = []
    for idx, e in enumerate(msp):
        if e.dxftype() not in ("LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE"):
            continue
        box = _varlik_bbox(e)
        if not box:
            continue
        w, h = box[2] - box[0], box[3] - box[1]
        merkez = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
        if (tab_alan > 0 and (w * h) / tab_alan > alan_orani) or \
           (tab_w > 0 and w / tab_w > boyut_orani) or \
           (tab_h > 0 and h / tab_h > boyut_orani):
            riskli.append((idx, e.dxf.handle, merkez, w, h))

    if not riskli:
        print("[Adim 2] Riskli (buyuk) parca tespit edilmedi.")
        return []

    print(f"[Adim 2] {len(riskli)} adet riskli parca tespit edildi:")
    for idx, handle, (mx, my), w, h in riskli:
        print(f"  - Indeks {idx} (handle {handle}) | merkez: "
              f"({mx:.2f}, {my:.2f}) | olcu: {w:.2f} x {h:.2f}")
    print("Uyari: Bu vektorlerin boyutlari buyuktur, etrafindaki fire "
          "alanlarina ekstra destek vidasi (hold-down) atilmasi onerilir.")
    return riskli


# ----------------------------------------------------------------------
# Onizleme icin: her kapali vektorun (baslangic_noktasi, [kontur_noktalari])
# ----------------------------------------------------------------------

def _metrikler(doc):
    """Bir dokumanin (toplam cevre, bbox) metriklerini bellek uzerinden doner."""
    box = _ezbbox.extents(doc.modelspace())
    bb = ((box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y)
          if box.has_data else None)
    return _toplam_yol_uzunlugu(doc), bb


def _metrik_dogrula(la, ba, lb, bb, cevre_tol=1e-6, bbox_tol=1e-7):
    if ba and bb:
        for a, b in zip(ba, bb):
            if abs(a - b) > bbox_tol:
                return False
    if la > 0 and abs(la - lb) / la > cevre_tol:
        return False
    return True


def optimize_doc(giris, opts, alan_orani=0.10, boyut_orani=0.50):
    """DXF'i bellek uzerinde optimize eder (DISK'e YAZMAZ). Onizleme/istatistik
    ve butunluk (bbox+cevre) dogrulamasi bellek uzerinden yapilir. Donen sozluk
    `doc` nesnesini icerir; kaydetmek isteyen taraf `doc.saveas(...)` cagirir."""
    doc = ezdxf.readfile(giris)
    msp = doc.modelspace()
    oncesi = varlik_yollari(doc)
    once_kontur = _kontur_haritasi(doc)      # vektor-bazli butunluk icin
    la, ba = _metrikler(doc)
    # Tabaka olcusunu baslangic optimizasyonuna aktar: cok uzun (riskli) yatay
    # seritlerin baslangici ust-orta/sag-uste kayar (bkz. geometry).
    opts = dict(opts)
    _gen = _ezbbox.extents(msp)
    if _gen.has_data:
        opts.setdefault("tabaka_w", _gen.extmax.x - _gen.extmin.x)
        opts.setdefault("tabaka_h", _gen.extmax.y - _gen.extmin.y)
    opts.setdefault("boyut_orani", boyut_orani)
    stats = adim1_baslangic_optimizasyonu(msp, opts)
    print("-" * 62)
    riskli = adim2_riskli_parca_uyarisi(msp, alan_orani, boyut_orani)
    lb, bb = _metrikler(doc)
    # CIRCLE -> 2-yayli polyline donusumu MATEMATIKSEL olarak birebirdir; ancak
    # ezdxf'in cember ve yay-polyline'i flatten etme yontemi ~5e-5 farkli uzunluk
    # OLCUMU verir (sekil ayni, sadece olcum artefakti). Cember donusturuldugunde
    # bu artefakti absorbe eden tolerans kullanilir; aksi halde tam-siki kontrol.
    if stats["cember"] > 0:
        cevre_tol, bbox_tol = 1e-3, 0.05
    else:
        cevre_tol, bbox_tol = 1e-6, 1e-7
    genel_ok = _metrik_dogrula(la, ba, lb, bb, cevre_tol, bbox_tol)

    # HER BIR VEKTOR icin ayri ayri butunluk: dokuman geneli kontrol tek basina
    # tek bir vektorun kayan koordinatini kacirabilir.
    sonra_kontur = _kontur_haritasi(doc)
    vektor = varlik_butunluk(once_kontur, sonra_kontur,
                             stats.get("dokunulan"), stats.get("donusen"))
    dogrulama = bool(genel_ok and vektor["ok"])
    if dogrulama:
        print(f"[Dogrulama] OK - bbox ve toplam cevre ({lb:.4f}) korundu; "
              f"{vektor['kontrol']} vektorun her biri birebir ayni.")
    else:
        if not genel_ok:
            print("[Dogrulama] UYARI! Dokuman geneli geometrik fark tespit edildi.")
        for s in vektor["sapan"]:
            print(f"[Dogrulama] UYARI! Vektor {s['handle']} ({s['tip']}): "
                  f"{s['neden']}")
    sonrasi = varlik_yollari(doc)
    return {
        "giris": giris, "doc": doc,
        "kaydirilan": stats["kaydirilan"],
        "silinen_node": stats["silinen_node"],
        "cember": stats["cember"],
        "riskli": riskli,
        "riskli_handlelar": {h for _, h, _, _, _ in riskli},
        "oncesi": oncesi, "sonrasi": sonrasi,
        "dogrulama": dogrulama, "cevre": lb,
        "genel_dogrulama": genel_ok,
        "vektor_butunluk": vektor,
    }


def optimize_ve_kaydet(giris, cikti, opts, alan_orani=0.10, boyut_orani=0.50):
    """optimize_doc + diske kaydet + kaydedilen dosyayi yeniden acip DOGRULA."""
    sonuc = optimize_doc(giris, opts, alan_orani, boyut_orani)
    sonuc["doc"].saveas(cikti)
    print("-" * 62)
    # Diskteki dosya uzerinden hem dokuman geneli hem de vektor-bazli kontrol.
    sonuc["dogrulama"] = bool(butunluk_dogrula(giris, cikti)
                              and sonuc["vektor_butunluk"]["ok"])
    print(f"[Adim 1] Cikti dosyasi: {cikti}")
    sonuc["cikti"] = cikti
    return sonuc


def _r(v):
    return round(v, 4)


def _varlik_svg_komut(e):
    """Bir varligi SVG yol komutlarina cevirir (M/L/Q/C, gerektiginde Z).
    ezdxf yaylari/spline'lari kubik bezier'e cevirdiginden egriler BIREBIR
    ve kompakt olur (flatten yok -> sonsuz yaklastirmada purüzsuz)."""
    p = _ezpath.make_path(e)
    if p.start is None:
        return None
    d = [["M", _r(p.start.x), _r(p.start.y)]]
    for cmd in p.commands():
        t = cmd.type
        if t == _Cmd.LINE_TO:
            d.append(["L", _r(cmd.end.x), _r(cmd.end.y)])
        elif t == _Cmd.CURVE4_TO:
            d.append(["C", _r(cmd.ctrl1.x), _r(cmd.ctrl1.y),
                      _r(cmd.ctrl2.x), _r(cmd.ctrl2.y), _r(cmd.end.x), _r(cmd.end.y)])
        elif t == _Cmd.CURVE3_TO:
            d.append(["Q", _r(cmd.ctrl.x), _r(cmd.ctrl.y),
                      _r(cmd.end.x), _r(cmd.end.y)])
        elif t == _Cmd.MOVE_TO:
            d.append(["M", _r(cmd.end.x), _r(cmd.end.y)])
    if len(d) < 2:
        return None
    return d


def varlik_yollari(doc):
    """Onizleme icin her cizilebilir varligin VEKTOREL yol komutlarini (d),
    baslangic noktasini ve kapali olup olmadigini doner. (Web onizlemesi bunu
    dogrudan SVG path olarak cizer.)"""
    sonuc = []
    for e in doc.modelspace():
        t = e.dxftype()
        if t not in ("LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC",
                     "LINE", "SPLINE", "ELLIPSE"):
            continue
        try:
            d = _varlik_svg_komut(e)
        except Exception:
            d = None
        if not d:
            continue
        kapali = bool(getattr(e, "closed", False) or
                      getattr(e, "is_closed", False) or t in ("CIRCLE", "ELLIPSE"))
        bas = None
        if t in ("LWPOLYLINE", "POLYLINE"):
            bas = [d[0][1], d[0][2]]     # ilk vertex = baslangic
        sonuc.append({"tip": t, "handle": e.dxf.handle,
                      "d": d, "baslangic": bas, "kapali": kapali})
    return sonuc


def baslangic_noktalari_ve_konturlar(doc):
    """Geriye donuk: flatten edilmis kontur noktalari (matplotlib PNG icin)."""
    sonuc = []
    for e in doc.modelspace():
        t = e.dxftype()
        if t not in ("LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC",
                     "LINE", "SPLINE", "ELLIPSE"):
            continue
        try:
            p = _ezpath.make_path(e)
            pts = [(v.x, v.y) for v in p.flattening(0.05)]
        except Exception:
            continue
        if not pts:
            continue
        bas = None
        if t in ("LWPOLYLINE", "POLYLINE"):
            bas = pts[0]
        sonuc.append({"tip": t, "handle": e.dxf.handle,
                      "kontur": pts, "baslangic": bas})
    return sonuc
