#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geometri yardimcilari
=====================
Bu modul saf-Python (ezdxf'e bagimli olmayan) geometri islemlerini icerir:

  * Node (vertex) sadelestirme  -> gereksiz, es-dogrultulu (collinear) ve
    sifir-uzunluklu noktalarin GEOMETRIYI BOZMADAN kaldirilmasi.
  * Baslangic (lead-in) noktasi hedefleme:
        - Normal parcalar: ust kenarda, orta-ust ile sag-ust arasinda
          (kose degil!) bir hedef -> kesim sonuna kadar destek korunur.
        - Uzun-ince (serit) parcalar: her zaman SAG kenar -> serit kesilirken
          her iki uctan da destekte kalir.

Noktalar `(x, y, start_width, end_width, bulge)` bicimindeki tuple listesi
olarak temsil edilir (ezdxf LWPOLYLINE "xyseb" formatiyla birebir uyumlu).
Boylece hem LWPOLYLINE hem de klasik 2D POLYLINE ayni mantigi paylasir.
"""

import math

# ----------------------------------------------------------------------
# Esik / tolerans sabitleri
# ----------------------------------------------------------------------

# Uzun-ince (serit) parca esigi: kisa kenar / uzun kenar bu degerin altindaysa
# parca "serit" sayilir (orn. dikey yerlesmis "I" harfi, ince cubuk).
UZUN_INCE_ORAN = 0.18

# Kose-civari aday bolge yaricapi: bbox kosegeninin bu orani.
KOSE_TOL_ORANI = 0.15

# Normal parcalarda baslangic hedefinin ust kenar uzerindeki yatay konumu.
# 0.5 = tam orta-ust, 1.0 = tam sag-ust. Varsayilan ikisinin arasi (saga
# yakin) -> kose degil ama saga dogru; boylece kesim boyunca destek kalir.
BASLANGIC_X_ORANI = 0.75

# Uzun-ince parcalarda baslangic hedefinin sag kenar uzerindeki dikey konumu.
# 0.0 = sag-alt, 1.0 = sag-ust, 0.5 = sag-orta.
SERIT_Y_ORANI = 0.5

# Node sadelestirmede "es-dogrultulu" kabul edilecek azami sapma (cizim
# birimi). Bir nokta, komsulariyla olusturdugu dogruya bu mesafeden daha
# yakinsa gereksiz sayilir ve kaldirilir. Cok kucuk tutulur ki sekil
# %100 korunsun.
NODE_TOL = 1e-6


# ----------------------------------------------------------------------
# Temel bbox
# ----------------------------------------------------------------------

def bbox_ve_olcu(noktalar):
    """Verilen noktalarin (xmin, ymin, xmax, ymax, w, h) degerlerini doner."""
    xs = [p[0] for p in noktalar]
    ys = [p[1] for p in noktalar]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    return xmin, ymin, xmax, ymax, xmax - xmin, ymax - ymin


def uzun_ince_mi(w, h, oran=UZUN_INCE_ORAN):
    """Parca uzun-ince (serit) mi?"""
    if w <= 1e-12 or h <= 1e-12:
        return False
    kisa, uzun = min(w, h), max(w, h)
    return (kisa / uzun) < oran


# ----------------------------------------------------------------------
# NODE SADELESTIRME (gereksiz vertex temizligi)
# ----------------------------------------------------------------------

def _es_dogrultulu_mu(a, b, c, tol):
    """B noktasi, A-C dogru parcasinin uzerinde (es-dogrultulu) ve A ile C
    arasinda mi? Oyleyse B gereksizdir (silinince sekil degismez)."""
    ax, ay = a[0], a[1]
    bx, by = b[0], b[1]
    cx, cy = c[0], c[1]
    dx, dy = cx - ax, cy - ay
    L2 = dx * dx + dy * dy
    if L2 <= 1e-18:
        # A ile C ayni nokta -> B ortadaysa (kucuk capli) silinebilir,
        # degilse koru. Pratikte bu durum nadir; guvenli tarafta kal.
        return math.hypot(bx - ax, by - ay) <= tol
    # B'nin A-C dogrusuna dik uzakligi
    capraz = abs(dx * (by - ay) - dy * (bx - ax))
    dik_uzaklik = capraz / math.sqrt(L2)
    if dik_uzaklik > tol:
        return False
    # B, A ve C arasinda mi? (projeksiyon parametresi 0..1)
    t = ((bx - ax) * dx + (by - ay) * dy) / L2
    return -1e-9 <= t <= 1.0 + 1e-9


def _genislikler_sifir(p):
    """Vertex'in baslangic/bitis genisligi sifir mi? (Genislik tasiyan
    noktalar silinirse interpolasyon degisebilir -> onlari koru.)"""
    return abs(p[2]) <= 1e-12 and abs(p[3]) <= 1e-12


def node_sadelestir(noktalar, kapali, tol=NODE_TOL):
    """Gereksiz vertex'leri GEOMETRIYI KORUYARAK kaldirir.

    Bir B vertex'i ancak su kosullarda silinir:
      * B'ye gelen segment (A->B) ve B'den giden segment (B->C) DUZ
        (bulge == 0) ise,
      * A, B ve C es-dogrultulu ve B aralarinda ise (ya da B, A ile cakisik
        -> sifir uzunluklu segment),
      * ilgili noktalar genislik (taper) tasimiyorsa.

    Bu islem cevre uzunlugunu ve bbox'u degistirmez; sadece fazla nokta
    sayisini azaltir (ArtCAM vb. yazilimlarda yuk/karmasayi dusurur).

    `noktalar`: (x, y, start_w, end_w, bulge) tuple listesi.
    `kapali`  : poligon kapali mi (cyclic komsuluk kullanilir).
    Doner: (yeni_noktalar, silinen_sayisi)
    """
    pts = list(noktalar)
    asgari = 3 if kapali else 2
    silinen = 0

    devam = True
    while devam and len(pts) > asgari:
        devam = False
        n = len(pts)
        for i in range(n):
            if kapali:
                ia, ic = (i - 1) % n, (i + 1) % n
            else:
                # Acik polyline'da uc noktalar korunur
                if i == 0 or i == n - 1:
                    continue
                ia, ic = i - 1, i + 1

            A, B, C = pts[ia], pts[i], pts[ic]

            # A->B ve B->C duz olmali (yay segmentleri bolunmez)
            if abs(A[4]) > 1e-12 or abs(B[4]) > 1e-12:
                continue
            if not (_genislikler_sifir(A) and _genislikler_sifir(B)):
                continue
            if _es_dogrultulu_mu(A, B, C, tol):
                del pts[i]
                silinen += 1
                devam = True
                break

    return pts, silinen


# ----------------------------------------------------------------------
# BASLANGIC NOKTASI HEDEFLEME
# ----------------------------------------------------------------------

def hedef_nokta(noktalar, uzun_ince,
                bas_x_orani=BASLANGIC_X_ORANI,
                serit_y_orani=SERIT_Y_ORANI):
    """Parcanin baslangic noktasinin idealde NEREDE olmasi gerektigini doner.

      * uzun_ince (serit): sag kenar uzerinde, dikeyde `serit_y_orani`
        konumunda (varsayilan sag-orta).  -> her iki uctan destek.
      * normal: ust kenar uzerinde, yatayda `bas_x_orani` konumunda
        (varsayilan orta-ust ile sag-ust arasi).  -> kose degil; kesim
        boyunca destek korunur.
    """
    xmin, ymin, xmax, ymax, w, h = bbox_ve_olcu(noktalar)
    if uzun_ince:
        return (xmax, ymin + h * serit_y_orani)
    return (xmin + w * bas_x_orani, ymax)


def hedefe_en_yakin_vertex(noktalar, hedef, tol_orani=KOSE_TOL_ORANI):
    """Hedefe yakin bolgedeki (tolerans icindeki) vertex'ler arasindan
    hedefe en yakin olanin indeksini doner. Bolgede vertex yoksa None."""
    xmin, ymin, xmax, ymax, w, h = bbox_ve_olcu(noktalar)
    diag = math.hypot(w, h)
    if diag <= 1e-12:
        return 0
    tol = diag * tol_orani
    adaylar = [i for i, p in enumerate(noktalar)
               if math.hypot(p[0] - hedef[0], p[1] - hedef[1]) <= tol]
    if not adaylar:
        return None
    return min(adaylar,
               key=lambda i: (noktalar[i][0] - hedef[0]) ** 2
               + (noktalar[i][1] - hedef[1]) ** 2)


def en_uygun_duz_segment_ekleme_noktasi(pts, hedef):
    """Hedef bolgede vertex yoksa, hedefe en yakin DUZ (bulge=0) segment
    uzerine eklenecek ara noktayi bulur. Doner: (segment_idx, yeni_pt) veya
    hic duz segment yoksa None. yeni_pt = (x, y, 0, 0, 0)."""
    en_iyi = None
    en_iyi_d2 = None
    n = len(pts)
    for i in range(n):
        p1, p2 = pts[i], pts[(i + 1) % n]
        if abs(p1[4]) > 1e-9:          # yay segmenti -> bolme
            continue
        x1, y1, x2, y2 = p1[0], p1[1], p2[0], p2[1]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        if L2 <= 1e-15:
            continue
        t = ((hedef[0] - x1) * dx + (hedef[1] - y1) * dy) / L2
        t = max(0.05, min(0.95, t))    # tam ucta birikmeyi onle
        nx, ny = x1 + t * dx, y1 + t * dy
        d2 = (nx - hedef[0]) ** 2 + (ny - hedef[1]) ** 2
        if en_iyi_d2 is None or d2 < en_iyi_d2:
            en_iyi_d2 = d2
            en_iyi = (i, (nx, ny, 0.0, 0.0, 0.0))
    return en_iyi


def baslangic_indeksi_belirle(pts, **kw):
    """Hedef noktayi belirler ve baslangic vertex'inin indeksini doner.

    Doner: (indeks, uzun_ince, eklenecek)
      indeks      : rotasyon yapilacak vertex indeksi (None ise yeni nokta
                    eklenmeli),
      uzun_ince   : parca serit mi,
      eklenecek   : (segment_idx, yeni_pt) ya da None.
    """
    xmin, ymin, xmax, ymax, w, h = bbox_ve_olcu(pts)
    uzun_ince = uzun_ince_mi(w, h)
    hedef = hedef_nokta(pts, uzun_ince,
                        kw.get("bas_x_orani", BASLANGIC_X_ORANI),
                        kw.get("serit_y_orani", SERIT_Y_ORANI))

    i = hedefe_en_yakin_vertex(pts, hedef, kw.get("tol_orani", KOSE_TOL_ORANI))
    if i is not None:
        return i, uzun_ince, None

    eklenen = en_uygun_duz_segment_ekleme_noktasi(pts, hedef)
    if eklenen is None:
        # Tum kenarlar yay -> yeni nokta eklenemez; en yakin mevcut vertex.
        i = min(range(len(pts)),
                key=lambda k: (pts[k][0] - hedef[0]) ** 2
                + (pts[k][1] - hedef[1]) ** 2)
        return i, uzun_ince, None

    return None, uzun_ince, eklenen
