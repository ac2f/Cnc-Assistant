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

def lwpolyline_optimize_et(pl, opts):
    """Kapali LWPOLYLINE icin: once gereksiz node'lari temizler, sonra
    baslangici hedef bolgeye tasir. Doner: (degisti_mi, silinen_node)."""
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
        pts.insert(seg_idx + 1, yeni_pt)
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
# Klasik 2D POLYLINE: node temizligi + baslangic kaydirma
# ----------------------------------------------------------------------

def polyline2d_optimize_et(pl, opts):
    if not pl.is_closed or pl.get_mode() != "AcDb2dPolyline":
        return False, 0
    vlist = list(pl.vertices)
    if len(vlist) < 3:
        return False, 0

    def vpt(v):
        return (v.dxf.location.x, v.dxf.location.y,
                v.dxf.get("start_width", 0.0),
                v.dxf.get("end_width", 0.0),
                v.dxf.get("bulge", 0.0))

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
                pl.delete_vertices(k, 1)
            vlist = list(pl.vertices)
            pts = [vpt(v) for v in vlist]

    if len(vlist) < 3:
        return (silinen > 0), silinen

    # 2) BASLANGIC HEDEFI
    i, _uzun, eklenen = G.baslangic_indeksi_belirle(pts, **opts)
    if i is None and eklenen is not None:
        seg_idx, yeni_pt = eklenen
        kaynak_v = vlist[seg_idx]
        yeni_v = kaynak_v.copy()
        yeni_v.dxf.location = (yeni_pt[0], yeni_pt[1], 0.0)
        yeni_v.dxf.bulge = yeni_pt[4]
        yeni_v.dxf.start_width = yeni_pt[2]
        yeni_v.dxf.end_width = yeni_pt[3]
        pl.doc.entitydb.add(yeni_v)
        vlist.insert(seg_idx + 1, yeni_v)
        pts.insert(seg_idx + 1, yeni_pt)
        i = seg_idx + 1

    degisti = silinen > 0
    if i and i != 0:
        veriler = [((p[0], p[1], 0.0), p[4], p[2], p[3]) for p in pts]
        yeni_vlist = vlist[i:] + vlist[:i]
        veriler = veriler[i:] + veriler[:i]
        for v, (loc, bulge, sw, ew) in zip(yeni_vlist, veriler):
            v.dxf.location = loc
            v.dxf.bulge = bulge
            v.dxf.start_width = sw
            v.dxf.end_width = ew
        pl.vertices = yeni_vlist
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
    olusan kapali LWPOLYLINE ile degistirilir. Baslangic: sag-ust 45 derece."""
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
    for e in list(msp):
        t = e.dxftype()
        if t == "LWPOLYLINE":
            if _kapali_mi_lwpolyline(e):
                d, s = lwpolyline_optimize_et(e, opts)
                toplam_silinen += s
                if d:
                    kaydirilan += 1
        elif t == "POLYLINE":
            d, s = polyline2d_optimize_et(e, opts)
            toplam_silinen += s
            if d:
                kaydirilan += 1
        elif t == "CIRCLE":
            cember_baslangic_kaydir(e, msp)
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
            "cember": cember}


# ----------------------------------------------------------------------
# GEOMETRIK BUTUNLUK DOGRULAMA
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

    sorun = []
    if ba.has_data and bc.has_data:
        for v1, v2 in ((ba.extmin, bc.extmin), (ba.extmax, bc.extmax)):
            if abs(v1.x - v2.x) > 1e-7 or abs(v1.y - v2.y) > 1e-7:
                sorun.append("bounding box farkli")
                break
    la, lb = _toplam_yol_uzunlugu(a), _toplam_yol_uzunlugu(b)
    if la > 0 and abs(la - lb) / la > 1e-6:
        sorun.append(f"toplam cevre farkli ({la:.6f} -> {lb:.6f})")

    if sorun:
        print("[Dogrulama] UYARI! Geometrik fark tespit edildi: "
              + "; ".join(sorun))
        return False
    print(f"[Dogrulama] OK - bbox ve toplam cevre ({la:.4f}) birebir korundu.")
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

def optimize_ve_kaydet(giris, cikti, opts, alan_orani=0.10, boyut_orani=0.50):
    """Bir DXF'i optimize edip `cikti` yoluna kaydeder. Konsola log basar ve
    onizleme/istatistik icin toplu bir sozluk doner (oncesi/sonrasi kontur +
    baslangic noktalari, riskli parcalar, dogrulama sonucu)."""
    doc = ezdxf.readfile(giris)
    msp = doc.modelspace()
    oncesi = baslangic_noktalari_ve_konturlar(doc)
    stats = adim1_baslangic_optimizasyonu(msp, opts)
    print("-" * 62)
    riskli = adim2_riskli_parca_uyarisi(msp, alan_orani, boyut_orani)
    doc.saveas(cikti)
    print("-" * 62)
    dogrulama = butunluk_dogrula(giris, cikti)
    print(f"[Adim 1] Cikti dosyasi: {cikti}")
    sonrasi_doc = ezdxf.readfile(cikti)
    sonrasi = baslangic_noktalari_ve_konturlar(sonrasi_doc)
    return {
        "giris": giris, "cikti": cikti,
        "kaydirilan": stats["kaydirilan"],
        "silinen_node": stats["silinen_node"],
        "cember": stats["cember"],
        "riskli": riskli,
        "riskli_handlelar": {h for _, h, _, _, _ in riskli},
        "oncesi": oncesi, "sonrasi": sonrasi,
        "dogrulama": dogrulama,
    }


def baslangic_noktalari_ve_konturlar(doc):
    """Onizleme icin her cizilebilir varligin baslangic noktasini ve
    flatten edilmis kontur noktalarini doner."""
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
