#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CNC Tabaka Kesim Optimizasyon Araci - v3
=========================================
Kutuphaneler:
  - ezdxf       (zorunlu)  -> DXF okuma/yazma
  - matplotlib  (istege bagli) -> kontrol amacli PNG onizleme gorseli

Kullanim (dosya uzantisina gore mod otomatik secilir):

    python cnc_optimizer.py tabaka.dxf        Adim 1 + Adim 2
    python cnc_optimizer.py kesim.tap         Adim 3 (G-Code yeniden siralama)
    python cnc_optimizer.py a.dxf b.tap ...   Birden fazla dosya ayni anda

Istege bagli parametreler (verilmezse mantikli varsayilanlar kullanilir):
    --alan-orani 0.10     Risk esigi: parca alani / tabaka alani
    --boyut-orani 0.50    Risk esigi: parca eni-boyu / tabaka eni-boyu
    --serpantin           G-Code siralamada zigzag (serpantin) deseni kullan
    --onizleme-yok        DXF icin PNG onizleme uretme

Yapilan isler:
  Adim 1: Kapali vektorlerin baslangic noktasi hedef bolgeye tasinir
          (geometri %100 korunur; kayit sonrasi otomatik dogrulanir):
            - Normal parcalarda: bbox sag-ust kosesine YAKIN bir vertex
              (tam kosedeki vertex sart degil; kose civarindaki en yakin
              vertex secilir).
            - El yazisi gibi serbest egrilerde kose civarinda hic vertex
              yoksa, en yakin DUZ segment uzerine geometriyi bozmadan
              YENI bir nokta eklenir ve baslangic oraya tasinir.
            - Uzun-ince (I-tipi, orn. dikey yerlesmis 'I' harfi) parcalarda
              baslangic, sag kenarda sag-alt ile sag-orta arasina cekilir
              (tabakanin sag/ust kenarlarinda destek daha yogun oldugundan).
  Adim 2: Buyuk/riskli parcalar konsola loglanir. DXF'e cizim EKLENMEZ.
  Adim 3: Hazir G-Code'daki kesim bloklari akilli sekilde siralanir.
          G-Code URETILMEZ; mevcut satirlar aynen korunur, sadece blok
          sirasi degisir. G91 (artimli mod) tespitinde guvenlik nedeniyle
          islem iptal edilir. Cikti dosyasi .tap uzantili olarak yazilir.
"""

import argparse
import math
import os
import re
import sys

try:
    import ezdxf
    from ezdxf import bbox as _ezbbox
    from ezdxf import path as _ezpath
except ImportError:
    print("Hata: 'ezdxf' kutuphanesi kurulu degil.  ->  pip install ezdxf")
    sys.exit(1)

GCODE_UZANTILAR = {".nc", ".gcode", ".tap", ".ngc", ".cnc", ".txt"}


# ======================================================================
# ADIM 1 - BASLANGIC NOKTASI (LEAD-IN) OPTIMIZASYONU
# ======================================================================

def _kapali_mi_lwpolyline(pl):
    """LWPOLYLINE kapali mi? (closed bayragi veya ilk=son nokta)"""
    if pl.closed:
        return True
    pts = pl.get_points("xy")
    if len(pts) >= 3:
        return math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-9
    return False


def _bbox_ve_oran(noktalar):
    """Vektorun bbox'i ve eni/boyu (uzun-ince tespiti icin)."""
    xs = [p[0] for p in noktalar]
    ys = [p[1] for p in noktalar]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    w = xmax - xmin
    h = ymax - ymin
    return xmin, ymin, xmax, ymax, w, h


# Uzun-ince (I-tipi) parca esigi: kisa kenar / uzun kenar bu degerin altindaysa
# parca "uzun-ince" sayilir (orn. dikey yerlesmis "I" harfi).
_UZUN_INCE_ORAN = 0.18

# Kose-civari aday bolge yaricapi: bbox kosegeninin bu orani.
_KOSE_TOL_ORANI = 0.15


def _uzun_ince_mi(w, h):
    if w <= 1e-12 or h <= 1e-12:
        return False
    kisa, uzun = min(w, h), max(w, h)
    return (kisa / uzun) < _UZUN_INCE_ORAN


def _koseye_yakin_sag_ust_indeks(noktalar):
    """Bbox sag-ust kosesine YAKIN bolgedeki vertex'ler arasindan, kosenin
    kendisine en yakin olani secer. 'Tam kose' yerine 'koseye yakin' bir
    vertex secilmesi istendigi icin sadece tolerans icindeki adaylar
    degerlendirilir. Hicbir vertex bu bolgeye girmiyorsa None doner
    (cagiran taraf yeni bir nokta eklemeyi degerlendirir)."""
    xmin, ymin, xmax, ymax, w, h = _bbox_ve_oran(noktalar)
    su = (xmax, ymax)
    diag = math.hypot(w, h)
    if diag <= 1e-12:
        return 0
    tol = diag * _KOSE_TOL_ORANI

    adaylar = [i for i, p in enumerate(noktalar)
               if math.hypot(p[0] - su[0], p[1] - su[1]) <= tol]
    if not adaylar:
        return None
    return min(adaylar,
               key=lambda i: (noktalar[i][0] - su[0]) ** 2 + (noktalar[i][1] - su[1]) ** 2)


def _sag_orta_alt_hedefi(xmin, ymin, xmax, ymax, w, h):
    """Uzun-ince parcalar icin hedef nokta: sag kenar uzerinde, sag-alt ile
    sag-orta arasinda (alta yakin) bir konum. Tabakanin sag/ust kenarlarinda
    destek (hold-down) daha yogun oldugundan, baslangic buraya cekilir."""
    return (xmax, ymin + h * 0.25)


def _hedef_baslangic_indeks(noktalar):
    """Parca tipine gore hedef baslangic vertex indeksini (varsa) ve
    parcanin uzun-ince olup olmadigini dondurur. Uzun-ince (I-tipi)
    parcalarda hedef = sag-alt/sag-orta arasi bolge; digerlerinde hedef =
    bbox sag-ust kosesine yakin bolge. Uygun vertex yoksa indeks None."""
    xmin, ymin, xmax, ymax, w, h = _bbox_ve_oran(noktalar)
    if _uzun_ince_mi(w, h):
        hedef = _sag_orta_alt_hedefi(xmin, ymin, xmax, ymax, w, h)
        diag = math.hypot(w, h)
        tol = diag * _KOSE_TOL_ORANI
        adaylar = [i for i, p in enumerate(noktalar)
                   if math.hypot(p[0] - hedef[0], p[1] - hedef[1]) <= tol]
        if not adaylar:
            return None, True
        i = min(adaylar,
                key=lambda i: (noktalar[i][0] - hedef[0]) ** 2 + (noktalar[i][1] - hedef[1]) ** 2)
        return i, True
    return _koseye_yakin_sag_ust_indeks(noktalar), False


def _hedef_nokta(noktalar, uzun_ince):
    xmin, ymin, xmax, ymax, w, h = _bbox_ve_oran(noktalar)
    if uzun_ince:
        return _sag_orta_alt_hedefi(xmin, ymin, xmax, ymax, w, h)
    return (xmax, ymax)


def _en_uygun_duz_segment_ekleme_noktasi(pts, hedef):
    """Bulge=0 (duz/dogru) segmentler arasinda, hedefe en yakin ara nokta
    uretimini dener. pts elemanlari (x, y, start_w, end_w, bulge) formatinda
    olmalidir. Donen deger: (segment_baslangic_idx, yeni_pt_tuple) ya da
    hicbir duz segment yoksa None."""
    en_iyi = None
    en_iyi_d2 = None
    n = len(pts)
    for i in range(n):
        p1, p2 = pts[i], pts[(i + 1) % n]
        if abs(p1[4]) > 1e-9:     # bulge != 0 -> yay, bu segmenti bolme
            continue
        x1, y1 = p1[0], p1[1]
        x2, y2 = p2[0], p2[1]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        if L2 <= 1e-15:
            continue
        t = ((hedef[0] - x1) * dx + (hedef[1] - y1) * dy) / L2
        t = max(0.05, min(0.95, t))   # tam ucta birikmesini onle
        nx, ny = x1 + t * dx, y1 + t * dy
        d2 = (nx - hedef[0]) ** 2 + (ny - hedef[1]) ** 2
        if en_iyi_d2 is None or d2 < en_iyi_d2:
            en_iyi_d2 = d2
            en_iyi = (i, (nx, ny, 0.0, 0.0, 0.0))   # x,y,start_w,end_w,bulge
    return en_iyi


def lwpolyline_baslangic_kaydir(pl):
    """Kapali LWPOLYLINE'in vertex sirasini dondurerek baslangici hedef
    bolgeye tasir:
      - Normal parcalarda: bbox sag-ust kosesine YAKIN bir vertex
        (tam kosedeki vertex degil, kose civarindaki en yakin vertex).
      - Uzun-ince (I-tipi, orn. dikey yerlesmis 'I' harfi) parcalarda:
        sag kenarda, sag-alt ile sag-orta arasinda bir vertex (tabakanin
        sag/ust kenarlarinda destek daha yogun oldugundan).

    Hedef bolgede mevcut bir vertex yoksa (orn. el yazisi gibi serbest
    egrilerde kose civarinda hic vertex bulunmayabilir), en yakin DUZ
    (bulge=0) segment uzerine GEOMETRIYI BOZMADAN yeni bir vertex eklenir
    ve baslangic oraya tasinir. Eklenen nokta var olan duz segmenti sadece
    ikiye boler; sekil/uzunluk degismez."""
    fmt = "xyseb"
    pts = list(pl.get_points(fmt))

    acik_kapali = False
    if not pl.closed:                 # ilk=son nokta ile kapatilmis
        pts = pts[:-1]
        acik_kapali = True

    if len(pts) < 3:
        return False

    i, uzun_ince = _hedef_baslangic_indeks(pts)

    if i is None:
        hedef = _hedef_nokta(pts, uzun_ince)
        eklenen = _en_uygun_duz_segment_ekleme_noktasi(pts, hedef)
        if eklenen is None:
            # Tum kenarlar yay (bulge != 0) -> geometriyi bozmadan yeni
            # nokta eklenemez; en yakin mevcut vertex kullanilir.
            i = min(range(len(pts)),
                    key=lambda k: (pts[k][0] - hedef[0]) ** 2 + (pts[k][1] - hedef[1]) ** 2)
        else:
            seg_idx, yeni_pt = eklenen
            pts.insert(seg_idx + 1, yeni_pt)
            i = seg_idx + 1

    if i == 0:
        return False

    pts = pts[i:] + pts[:i]
    if acik_kapali:
        pts = pts + [pts[0]]
    pl.set_points(pts, format=fmt)
    return True


def polyline2d_baslangic_kaydir(pl):
    """Klasik 2D POLYLINE icin ayni mantik. Hedef bolgede vertex yoksa ve
    duz bir segment uzerine yeni nokta eklenebiliyorsa, mevcut bir vertex
    KLONLANIP konumu/bulge/genislik degerleri yeni noktaya gore guncellenir
    (boylece DXF entity tipiyle uyumlu, gecerli bir VERTEX nesnesi elde
    edilir); bu sayede segment ikiye bolunur ama geometri degismez."""
    if not pl.is_closed or pl.get_mode() != "AcDb2dPolyline":
        return False
    vlist = list(pl.vertices)
    if len(vlist) < 3:
        return False
    pts = [(v.dxf.location.x, v.dxf.location.y,
            v.dxf.get("start_width", 0.0),
            v.dxf.get("end_width", 0.0),
            v.dxf.get("bulge", 0.0)) for v in vlist]

    i, uzun_ince = _hedef_baslangic_indeks([(p[0], p[1]) for p in pts])

    if i is None:
        hedef = _hedef_nokta([(p[0], p[1]) for p in pts], uzun_ince)
        eklenen = _en_uygun_duz_segment_ekleme_noktasi(pts, hedef)
        if eklenen is None:
            i = min(range(len(pts)),
                    key=lambda k: (pts[k][0] - hedef[0]) ** 2 + (pts[k][1] - hedef[1]) ** 2)
        else:
            seg_idx, yeni_pt = eklenen
            # Komsu vertex'lerden birini klonlayip yeni konuma tasiyarak
            # gecerli bir VERTEX entity'si elde edilir.
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

    if i == 0:
        return False

    veriler = [((p[0], p[1], 0.0), p[4], p[2], p[3]) for p in pts]
    yeni_vlist = vlist[i:] + vlist[:i]
    veriler = veriler[i:] + veriler[:i]
    for v, (loc, bulge, sw, ew) in zip(yeni_vlist, veriler):
        v.dxf.location = loc
        v.dxf.bulge = bulge
        v.dxf.start_width = sw
        v.dxf.end_width = ew
    pl.vertices = yeni_vlist
    return True

def cember_baslangic_kaydir(circle, msp):
    """DXF'te CIRCLE baslangic noktasi tasimaz; CAM kendi secer. Baslangici
    kontrol icin cember, MATEMATIKSEL OLARAK BIREBIR AYNI geometriyi
    tanimlayan iki adet 180 derecelik yaydan (bulge=1.0) olusan kapali
    LWPOLYLINE ile degistirilir. Merkez/yaricap/form %100 korunur.
    Baslangic: cemberin sag-ust 45 derece noktasi."""
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


def adim1_baslangic_optimizasyonu(msp):
    kaydirilan, cember, atlanan = 0, 0, []
    for e in list(msp):
        t = e.dxftype()
        if t == "LWPOLYLINE":
            if _kapali_mi_lwpolyline(e) and lwpolyline_baslangic_kaydir(e):
                kaydirilan += 1
        elif t == "POLYLINE":
            if polyline2d_baslangic_kaydir(e):
                kaydirilan += 1
        elif t == "CIRCLE":
            cember_baslangic_kaydir(e, msp)
            cember += 1
        elif t in ("SPLINE", "ELLIPSE") and getattr(e, "closed", False):
            atlanan.append((t, e.dxf.handle))

    print(f"[Adim 1] Baslangici sag-uste tasinan polyline sayisi: {kaydirilan}")
    if cember:
        print(f"[Adim 1] Es-geometrik 2-yayli polyline'a cevrilen cember: {cember} "
              f"(form/olcu birebir ayni)")
    for t, h in atlanan:
        print(f"[Adim 1] NOT: Kapali {t} (handle {h}) parametrik oldugundan "
              f"baslangici guvenle kaydirilamaz; oldugu gibi korundu.")


# ======================================================================
# GEOMETRIK BUTUNLUK DOGRULAMA (otomatik guvence)
# ======================================================================

def _toplam_yol_uzunlugu(doc):
    """Desteklenen 2D varliklarin flatten edilmis toplam cevre uzunlugu."""
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
    """Kaydedilen dosyayi yeniden acip orijinalle karsilastirir:
    genel bounding box ve toplam cevre uzunlugu birebir tutmali."""
    a = ezdxf.readfile(orijinal_yol)
    b = ezdxf.readfile(cikti_yol)
    ba = _ezbbox.extents(a.modelspace())
    bc = _ezbbox.extents(b.modelspace())

    sorun = []
    if ba.has_data and bc.has_data:
        for v1, v2 in ((ba.extmin, bc.extmin), (ba.extmax, bc.extmax)):
            if (abs(v1.x - v2.x) > 1e-7 or abs(v1.y - v2.y) > 1e-7):
                sorun.append("bounding box farkli")
                break
    la, lb = _toplam_yol_uzunlugu(a), _toplam_yol_uzunlugu(b)
    if la > 0 and abs(la - lb) / la > 1e-6:
        sorun.append(f"toplam cevre farkli ({la:.6f} -> {lb:.6f})")

    if sorun:
        print("[Dogrulama] UYARI! Geometrik fark tespit edildi: " + "; ".join(sorun))
        return False
    print(f"[Dogrulama] OK - bbox ve toplam cevre ({la:.4f}) birebir korundu.")
    return True


# ======================================================================
# ADIM 2 - RISKLI PARCA UYARI SISTEMI (sadece konsol logu)
# ======================================================================

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


# ======================================================================
# PNG ONIZLEME (istege bagli, DXF'e dokunmaz - sadece kontrol gorseli)
# ======================================================================

def onizleme_uret(doc, riskli_handlelar, png_yol):
    """Yesil nokta = yeni kesim baslangici, kirmizi kontur = riskli parca.
    matplotlib kurulu degilse sessizce atlanir."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[Onizleme] matplotlib kurulu degil, PNG uretilmedi "
              "(istege bagli: pip install matplotlib)")
        return

    fig, ax = plt.subplots(figsize=(11, 8))
    for e in doc.modelspace():
        if e.dxftype() not in ("LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC",
                               "LINE", "SPLINE", "ELLIPSE"):
            continue
        try:
            p = _ezpath.make_path(e)
            pts = list(p.flattening(0.01))
        except Exception:
            continue
        xs = [v.x for v in pts]
        ys = [v.y for v in pts]
        riskli = e.dxf.handle in riskli_handlelar
        ax.plot(xs, ys, color="#d62728" if riskli else "#1f77b4",
                lw=1.6 if riskli else 0.9)
        if e.dxftype() in ("LWPOLYLINE", "POLYLINE") and xs:
            ax.plot(xs[0], ys[0], "o", color="#2ca02c", ms=5, zorder=5)

    ax.plot([], [], "o", color="#2ca02c", label="Kesim baslangici (sag ust)")
    ax.plot([], [], color="#d62728", label="Riskli parca (hold-down onerilir)")
    ax.legend(loc="upper right", fontsize=8)
    ax.set_aspect("equal")
    ax.set_title("Optimizasyon Onizlemesi (kontrol amaclidir)")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(png_yol, dpi=150)
    plt.close(fig)
    print(f"[Onizleme] Kontrol gorseli: {png_yol}")


# ======================================================================
# ADIM 3 - HAZIR G-CODE BLOKLARINI AKILLI YENIDEN SIRALAMA
# ======================================================================
# G-Code URETILMEZ. Mevcut satirlar aynen korunur; sadece bagimsiz kesim
# bloklarinin sirasi degistirilir.

_WORD_RE = re.compile(r"([A-Za-z])\s*([+-]?\d+\.?\d*)")
_BITIS_RE = re.compile(r"\b(M0?2|M30|M0?5|M0?9|G28|G53)\b|^\s*%\s*$", re.I)


def _satir_kelimeleri(satir):
    s = re.sub(r"\(.*?\)", "", satir)      # ( ... ) yorumlari
    s = s.split(";", 1)[0]                  # ; yorumlari
    return {h.upper(): float(v) for h, v in _WORD_RE.findall(s)}


def _blok_basi_mi(satir):
    """Yeni kesim blogunun basi: X ve Y iceren G0/G00 hizli hareket."""
    w = _satir_kelimeleri(satir)
    return w.get("G") == 0.0 and "X" in w and "Y" in w


def _g91_var_mi(satirlar):
    """Artimli mod (G91) kontrolu. G91.1 (yay merkezi modu) haric tutulur."""
    rx = re.compile(r"\bG91(?!\.)\b", re.I)
    for s in satirlar:
        temiz = re.sub(r"\(.*?\)", "", s).split(";", 1)[0]
        if rx.search(temiz):
            return True
    return False


def _blok_son_xy(blok, varsayilan):
    """Bloktaki son bilinen mutlak XY konumu (travel istatistigi icin)."""
    x, y = varsayilan
    for s in blok:
        w = _satir_kelimeleri(s)
        if "X" in w:
            x = w["X"]
        if "Y" in w:
            y = w["Y"]
    return (x, y)


def _toplam_bosta_yol(bloklar):
    """Bloklar arasi (kesim disi) XY tasima mesafesi toplami."""
    toplam, konum = 0.0, None
    for blok in bloklar:
        w = _satir_kelimeleri(blok[0])
        bas = (w.get("X", 0.0), w.get("Y", 0.0))
        if konum is not None:
            toplam += math.hypot(bas[0] - konum[0], bas[1] - konum[1])
        konum = _blok_son_xy(blok, bas)
    return toplam


def _blok_bbox(blok):
    """Bloktaki tum X/Y degerlerinden (G0 ve kesim hareketleri dahil)
    yaklasik bir bbox (xmin, ymin, xmax, ymax) cikarir. Z ve diger
    kelimeler yok sayilir; sadece konum tahmini icindir."""
    xs, ys = [], []
    for s in blok:
        w = _satir_kelimeleri(s)
        if "X" in w:
            xs.append(w["X"])
        if "Y" in w:
            ys.append(w["Y"])
    if not xs or not ys:
        w = _satir_kelimeleri(blok[0])
        x0, y0 = w.get("X", 0.0), w.get("Y", 0.0)
        return (x0, y0, x0, y0)
    return (min(xs), min(ys), max(xs), max(ys))


def _blok_bas_xy(blok):
    w = _satir_kelimeleri(blok[0])
    return (w.get("X", 0.0), w.get("Y", 0.0))


# X-araliklari "ayni kolonda / cakisan" sayilmasi icin tolerans orani
# (genel X araliginin bu orani kadar bindirme/kapinda olabilir).
_X_CAKISMA_TOLERANSI = 0.02


def _x_araliklari_cakisiyor_mu(b1, b2, x_toleransi):
    """Iki bbox'in X araliklari (toleranslari ile) kesisiyor mu?"""
    x1min, _, x1max, _ = b1
    x2min, _, x2max, _ = b2
    return (x1min - x_toleransi) <= x2max and (x2min - x_toleransi) <= x1max


def _akilli_oncelik_sirala(bloklar):
    """Vektorleri, sadece Y konumuna gore degil, 'ustune uzanma / golgede
    kalma' iliskisine gore sıralar.

    Mantik: Eger bir parca (B), tabakanin solunda fakat bir digerinden (A)
    biraz daha yukarida ve A'nin X araligi ile cakismiyorsa (yani A, B'nin
    UZERINDEN/UZERINE GECMIYOR), B'nin once islenmesini geciktirmek icin
    bir sebep yoktur; bu durumda B, sadece daha asagida oldugu icin
    oncelik kazanan A'dan ONCE gelebilir.

    Tersine, eger B'nin X araligiyla cakisan ve B'nin USTUNDE (daha yuksek
    Y'de) duran bir parca varsa, o ust parca digerlerine gore makul bir
    sirada once islenmelidir (B'ye 'uzanmasini' onlemek icin once temizlenir).

    Uygulama: her parca icin 'engelleyici ust parca sayisi' hesaplanir -
    kendisinin X araligiyla cakisan ve kendisinden daha yukarida (ymin
    buyuk) olan parca sayisi. Bu sayi birincil siralama anahtari olarak
    kullanilir (az engelleyicisi olan once gelir); esitlik durumunda
    Y, sonra X ile siralanir (sol-alt -> sag-ust egilimi korunur)."""
    bboxlar = [_blok_bbox(b) for b in bloklar]

    # Genel X araligina gore tolerans mesafesi
    tum_x = [v for box in bboxlar for v in (box[0], box[2])]
    genel_x_araligi = (max(tum_x) - min(tum_x)) if tum_x else 0.0
    x_tol = genel_x_araligi * _X_CAKISMA_TOLERANSI

    n = len(bloklar)
    engelleyici_sayisi = [0] * n
    for i in range(n):
        bi = bboxlar[i]
        for j in range(n):
            if i == j:
                continue
            bj = bboxlar[j]
            # j, i'nin "ustunde" sayilir eger: X araliklari cakisiyor VE
            # j'nin alt sinirinin cogu i'nin ust sinirindan yukarida.
            if _x_araliklari_cakisiyor_mu(bi, bj, x_tol) and bj[1] > bi[3] - x_tol:
                engelleyici_sayisi[i] += 1

    indeksli = list(range(n))

    def anahtar(i):
        x, y = _blok_bas_xy(bloklar[i])
        return (engelleyici_sayisi[i], y, x)

    indeksli.sort(key=anahtar)
    return [bloklar[i] for i in indeksli]



def _serpantin_sirala(bloklar):
    """Y'ye gore bantlara ayirip bant icinde X yonunu sirayla degistirir
    (zigzag). Bosta tasima mesafesini azaltir; yine sol-alttan baslar."""
    def bas_xy(blok):
        w = _satir_kelimeleri(blok[0])
        return (w.get("X", 0.0), w.get("Y", 0.0))

    sirali_y = sorted(bloklar, key=lambda b: bas_xy(b)[1])
    ys = [bas_xy(b)[1] for b in sirali_y]
    aralik = (max(ys) - min(ys)) if ys else 0.0
    tolerans = max(aralik * 0.05, 1e-9)   # ayni bant sayilacak Y yakinligi

    bantlar, mevcut, son_y = [], [], None
    for b in sirali_y:
        y = bas_xy(b)[1]
        if son_y is not None and (y - son_y) > tolerans and mevcut:
            bantlar.append(mevcut)
            mevcut = []
        mevcut.append(b)
        son_y = y
    if mevcut:
        bantlar.append(mevcut)

    sonuc = []
    for n, bant in enumerate(bantlar):
        bant.sort(key=lambda b: bas_xy(b)[0], reverse=(n % 2 == 1))
        sonuc.extend(bant)
    return sonuc


def adim3_gcode_yeniden_sirala(yol, serpantin=False):
    with open(yol, "r", encoding="utf-8", errors="replace") as f:
        satirlar = f.read().splitlines()

    # GUVENLIK: artimli mod tespit edilirse siralamak konumlari bozar
    if _g91_var_mi(satirlar):
        print("[Adim 3] GUVENLIK IPTALI: Dosyada G91 (artimli mod) tespit "
              "edildi. Artimli kodda blok sirasi degistirmek tum konumlari "
              "kaydirir. Dosya DEGISTIRILMEDI.")
        return

    bas_indeksler = [i for i, s in enumerate(satirlar) if _blok_basi_mi(s)]
    if not bas_indeksler:
        print("[Adim 3] X-Y iceren G0 hizli hareket bulunamadi; "
              "blok tespiti yapilamadi. Dosya degistirilmedi.")
        return

    header = satirlar[:bas_indeksler[0]]
    bloklar = []
    for n, bi in enumerate(bas_indeksler):
        son = bas_indeksler[n + 1] if n + 1 < len(bas_indeksler) else len(satirlar)
        bloklar.append(satirlar[bi:son])

    # Program-sonu satirlarini (M5/M30/%/G28...) footer'a tasi.
    # GUVENLIK: Z geri cekme (retract) satiri footer'a TASINMAZ,
    # kendi bloguyla birlikte yer degistirir.
    footer = []
    son_blok = bloklar[-1]
    while son_blok:
        s = son_blok[-1]
        if _BITIS_RE.search(s) or not s.strip():
            footer.insert(0, son_blok.pop())
        else:
            break
    bloklar[-1] = son_blok

    # GUVENLIK: Z retract ile bitmeyen blok ortaya tasinirsa takim kesim
    # derinliginde yatay hizli hareket yapar -> boyle blok sonda sabitlenir.
    def _retract_ile_bitiyor(blok):
        for s in reversed(blok):
            w = _satir_kelimeleri(s)
            if not w:
                continue
            return w.get("G") == 0.0 and "Z" in w and "X" not in w and "Y" not in w
        return False

    sabit_son = None
    if not _retract_ile_bitiyor(bloklar[-1]):
        sabit_son = bloklar.pop()
        print("[Adim 3] GUVENLIK: Son blok Z geri cekme ile bitmedigi icin "
              "konumu korundu (en sonda birakildi).")

    onceki_bosta = _toplam_bosta_yol(bloklar + ([sabit_son] if sabit_son else []))

    # Siralama (kararli sort: ayni noktadan baslayan cok-paso bloklarin
    # kendi ic sirasi korunur)
    if serpantin:
        sirali = _serpantin_sirala(bloklar)
    else:
        sirali = _akilli_oncelik_sirala(bloklar)
    if sabit_son is not None:
        sirali.append(sabit_son)

    yeni_bosta = _toplam_bosta_yol(sirali)

    kok, uz = os.path.splitext(yol)
    cikti = f"{kok}_reordered.tap"
    with open(cikti, "w", encoding="utf-8") as f:
        for s in header:
            f.write(s + "\n")
        for blok in sirali:
            for s in blok:
                f.write(s + "\n")
        for s in footer:
            f.write(s + "\n")

    mod = "serpantin (zigzag)" if serpantin else "akilli oncelik (golge/engel farkindaligi)"
    print(f"[Adim 3] {len(sirali)} kesim blogu tespit edildi, '{mod}' "
          f"duzeninde siralandi.")
    for n, blok in enumerate(sirali, 1):
        w = _satir_kelimeleri(blok[0])
        print(f"  {n}. blok -> baslangic X{w.get('X', 0):.2f} Y{w.get('Y', 0):.2f}")
    if onceki_bosta > 0:
        fark = (1 - yeni_bosta / onceki_bosta) * 100 if onceki_bosta else 0
        print(f"[Adim 3] Bosta tasima mesafesi: {onceki_bosta:.1f} -> "
              f"{yeni_bosta:.1f}  ({fark:+.1f}%)")
    print(f"[Adim 3] Cikti dosyasi: {cikti}")


# ======================================================================
# ANA AKIS
# ======================================================================

def dxf_isle(yol, alan_orani, boyut_orani, onizleme):
    doc = ezdxf.readfile(yol)
    msp = doc.modelspace()

    adim1_baslangic_optimizasyonu(msp)
    print("-" * 62)
    riskli = adim2_riskli_parca_uyarisi(msp, alan_orani, boyut_orani)

    kok, _ = os.path.splitext(yol)
    cikti = f"{kok}_optimized.dxf"
    doc.saveas(cikti)
    print("-" * 62)
    butunluk_dogrula(yol, cikti)
    print(f"[Adim 1] Cikti dosyasi: {cikti}")

    if onizleme:
        onizleme_uret(ezdxf.readfile(cikti),
                      {h for _, h, _, _, _ in riskli},
                      f"{kok}_onizleme.png")


def main():
    ap = argparse.ArgumentParser(
        description="CNC tabaka kesimi: DXF baslangic-noktasi optimizasyonu, "
                    "riskli parca uyarisi ve G-Code blok siralama.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("dosyalar", nargs="+",
                    help="Bir veya daha fazla .dxf ve/veya G-Code dosyasi")
    ap.add_argument("--alan-orani", type=float, default=0.10,
                    help="Risk esigi: parca bbox alani / tabaka alani")
    ap.add_argument("--boyut-orani", type=float, default=0.50,
                    help="Risk esigi: parca eni-boyu / tabaka eni-boyu")
    ap.add_argument("--serpantin", action="store_true",
                    help="G-Code siralamada zigzag deseni (bosta yolu azaltir)")
    ap.add_argument("--onizleme-yok", action="store_true",
                    help="DXF icin PNG kontrol gorseli uretme")
    args = ap.parse_args()

    for yol in args.dosyalar:
        print("=" * 62)
        print(f"Dosya: {yol}")
        print("=" * 62)
        if not os.path.isfile(yol):
            print(f"Hata: Dosya bulunamadi -> {yol}")
            continue
        uz = os.path.splitext(yol)[1].lower()
        if uz == ".dxf":
            dxf_isle(yol, args.alan_orani, args.boyut_orani,
                     not args.onizleme_yok)
        elif uz in GCODE_UZANTILAR:
            adim3_gcode_yeniden_sirala(yol, serpantin=args.serpantin)
        else:
            print(f"Hata: Desteklenmeyen uzanti '{uz}'.")


if __name__ == "__main__":
    main()
