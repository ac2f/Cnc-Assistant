#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geometri yardimcilari
=====================
Bu modul saf-Python (ezdxf'e bagimli olmayan) geometri islemlerini icerir:

  * Node (vertex) sadelestirme  -> gereksiz, es-dogrultulu (collinear) ve
    sifir-uzunluklu noktalarin GEOMETRIYI BOZMADAN kaldirilmasi.
  * Baslangic (lead-in) noktasi hedefleme:
        - Normal parcalar: UST kenarda, SOLDAN ~%20 konumunda (sol-ust bolge,
          keskin kose degil) -> operatorun elle yaptigi "manuel optimize"
          yerlesimini birebir taklit eder; kesim boyunca destek korunur.
        - Uzun-ince (serit) parcalar:
            * dikey serit -> SOL kenar, ucundan degil ~%25 iceride
              (iki uctan da destekte kalir),
            * yatay serit -> UST kenar (normal parca kurali).

  Not: Baslangic hedefi eskiden SAG-UST idi; gercek uretim dosyalari
  (ArtCAM'de elle optimize edilmis) incelendiginde operatorun tutarli olarak
  SOL-UST bolgeyi sectigi olculdu ve algoritma buna gore duzeltildi.

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

# BASLANGIC (lead-in) hedefi -- normal parcalar icin UST kenarda, SOLDAN bu
# oranda bir nokta hedeflenir (0 = sol kose, 1 = sag kose). Uretim dosyalarinda
# elle optimize edilmis yerlesimlerin medyani ~0.20 (sol-ust) cikti.
BASLANGIC_X_ORANI = 0.20

# "Ust" sayilacak vertex bandi: bbox yuksekliginin bu orani kadar ust kenardan
# asagisi ust bolge kabul edilir. Bu bant icindeki adaylar arasindan yatayda
# hedefe (BASLANGIC_X_ORANI) en yakin vertex secilir. Genis tutulur; boylece
# ust kenari cukurlu/tabli karmasik parcalarda da sol-ust bolge yakalanir.
UST_BANT_ORANI = 0.30

# Ust banttaki adaylarda dusey sapmanin agirligi (yatay hedefe kiyasla).
# Kucuk tutulur -> once dogru YATAY konum (sol), sonra mumkun oldugunca yukari.
UST_Y_AGIRLIK = 0.10

# Dikey serit parcalarda baslangicin uzun (yan) kenar boyunca konumu: alttan
# bu oranda. Ucundan degil iceride -> serit kesilirken iki uctan da destekli.
SERIT_Y_ORANI = 0.25

# Baslangic hedefine (ust kenar, soldan BASLANGIC_X_ORANI) mevcut bir vertex
# bu kadar yakinsa (bbox kosegeninin orani) o vertex kullanilir; degilse ust
# kenar DUZ segmenti uzerine TAM hedefte bir baslangic node'u eklenir (ArtCAM'de
# elle yapilan mid-edge baslangic yerlesiminin birebir karsiligi -> sekil
# %100 korunur, yalnizca tek bir lead-in node'u eklenir).
BASLANGIC_KABUL_TOL = 0.04

# DESTEK/BASLANGIC YONU (dx, dy). Yalnizca YATAY isaret (dx) kullanilir:
# dx<0 -> sol-ust (varsayilan), dx>0 -> sag-ust, dx~0 -> orta-ust. Dikey serit
# parcalarda ayni isaret hangi yan kenarin secilecegini belirler.
DESTEK_YONU = (-1.0, 1.0)

# Yon-projeksiyonu primitifi (destek_ucu_indeks) icin "en uc" bandi.
DESTEK_BANT_ORANI = 0.02

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


def _silinebilir(A, B, C, tol):
    """B vertex'i (A ile C arasinda) gereksiz mi? Silinebilmesi icin:
      * A->B ve B->C DUZ (bulge == 0) olmali (yay segmentleri korunur),
      * A ve B genislik (taper) tasimamali,
      * A, B, C es-dogrultulu ve B aralarinda olmali."""
    if abs(A[4]) > 1e-12 or abs(B[4]) > 1e-12:
        return False
    if not (_genislikler_sifir(A) and _genislikler_sifir(B)):
        return False
    return _es_dogrultulu_mu(A, B, C, tol)


def node_sadelestir(noktalar, kapali, tol=NODE_TOL):
    """Gereksiz (es-dogrultulu / sifir-uzunluklu) vertex'leri GEOMETRIYI
    KORUYARAK kaldirir. Cevre uzunlugunu ve bbox'u degistirmez; sadece nokta
    sayisini azaltir (ArtCAM vb. yuk/karmasayi dusurur).

    Yigin-tabanli TEK GECIS -> O(n) (buyuk/karmasik dosyalarda hizli). Bir
    vertex kaldirilinca zincirleme sadelesmeler ayni gecisde yakalanir.

    `noktalar`: (x, y, start_w, end_w, bulge) tuple listesi.
    `kapali`  : poligon kapali mi (dikis/seam ucu da sadelesir).
    Doner: (yeni_noktalar, silinen_sayisi)
    """
    pts = list(noktalar)
    asgari = 3 if kapali else 2
    if len(pts) <= asgari:
        return pts, 0

    res = []
    for p in pts:
        res.append(p)
        while len(res) >= 3 and _silinebilir(res[-3], res[-2], res[-1], tol):
            res.pop(-2)      # ortadaki gereksiz noktayi at (zincirleme)

    # Kapali poligonda dikis (son<->ilk) civarini da temizle
    if kapali:
        temizlendi = True
        while temizlendi and len(res) > asgari:
            temizlendi = False
            if len(res) >= 3 and _silinebilir(res[-2], res[-1], res[0], tol):
                res.pop(-1); temizlendi = True
            if len(res) >= 3 and _silinebilir(res[-1], res[0], res[1], tol):
                res.pop(0); temizlendi = True

    return res, len(pts) - len(res)


# ----------------------------------------------------------------------
# BASLANGIC NOKTASI HEDEFLEME
# ----------------------------------------------------------------------

def hedef_nokta(noktalar, uzun_ince,
                bas_x_orani=BASLANGIC_X_ORANI,
                serit_y_orani=SERIT_Y_ORANI):
    """Parcanin baslangic noktasinin idealde NEREDE olmasi gerektigini doner.

      * uzun_ince (dikey serit): SOL kenar uzerinde, dikeyde `serit_y_orani`
        konumunda (varsayilan sol, alttan ~%25).  -> her iki uctan destek.
      * normal: UST kenar uzerinde, yatayda `bas_x_orani` konumunda
        (varsayilan soldan ~%20 = sol-ust bolge).  -> kose degil; kesim
        boyunca destek korunur.
    """
    xmin, ymin, xmax, ymax, w, h = bbox_ve_olcu(noktalar)
    if uzun_ince:
        return (xmin, ymin + h * serit_y_orani)
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


def kontur_uzunlugu(kontur, kapali=True):
    n = len(kontur)
    if n < 2:
        return 0.0
    L = 0.0
    rng = range(n) if kapali else range(n - 1)
    for i in rng:
        a, b = kontur[i], kontur[(i + 1) % n]
        L += math.hypot(b[0] - a[0], b[1] - a[1])
    return L


def tab_pozisyonlari(kontur, adet=4, kose_kacinma=0.12):
    """Kapali bir kontur uzerinde, KOPRU (tab) yerlestirmek icin esit araliklı
    nokta konumlari doner. Koseler (keskin donusler) civarindan kacinilir;
    boylece kesim sonrasi parca yerinde kalir. GEOMETRIYI DEGISTIRMEZ - yalnizca
    'nereye koprü konmali' bilgisini uretir (ArtCAM'de/elde koprü buraya konur).

    Doner: [(x, y, aci_derece), ...]  (aci = konturun o noktadaki teget acisi)
    """
    n = len(kontur)
    if n < 2 or adet < 1:
        return []
    toplam = kontur_uzunlugu(kontur, kapali=True)
    if toplam <= 1e-9:
        return []
    # kenar uzunluklari ve kumulatif
    kenarlar = []
    for i in range(n):
        a, b = kontur[i], kontur[(i + 1) % n]
        kenarlar.append((a, b, math.hypot(b[0] - a[0], b[1] - a[1])))

    def nokta_at(mesafe):
        d = mesafe % toplam
        for a, b, L in kenarlar:
            if d <= L or L <= 1e-12:
                t = 0.0 if L <= 1e-12 else d / L
                x = a[0] + (b[0] - a[0]) * t
                y = a[1] + (b[1] - a[1]) * t
                aci = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
                # koseye cok yakinsa kenarin ortasina dogru it
                yakin_kose = min(t, 1 - t) * L
                return (x, y, aci), yakin_kose, L
            d -= L
        return (kontur[0][0], kontur[0][1], 0.0), 0.0, 0.0

    sonuc = []
    for i in range(adet):
        hedef = toplam * (i + 0.5) / adet
        (x, y, aci), yakin, L = nokta_at(hedef)
        # kose civarindaysa biraz kaydir (kenarin ortasina)
        if L > 1e-9 and yakin < kose_kacinma * L:
            hedef += (kose_kacinma * L)
            (x, y, aci), _, _ = nokta_at(hedef)
        sonuc.append((x, y, aci))
    return sonuc


def destek_ucu_indeks(pts, d=(1.0, 1.0), band_orani=DESTEK_BANT_ORANI):
    """Baslangic (lead-in / kopma) noktasi icin en SAG-UST (destek yonundeki)
    vertex'in indeksini DETERMINISTIK olarak secer.

    Yontem: her vertex'in destek yonune (d) izdusumu hesaplanir; izdusumu en
    yuksek olanlar (kucuk bir bant icinde) 'destek-yonune bakan uc' adaylaridir.
      - Tek aday varsa (keskin sag-ust kose): o secilir.
      - Birden cok aday varsa (destek yonune dik, DUZ bir sag-ust kenar): o
        kenarin ORTASINDAKI vertex secilir -> kose yerine, arkasi tamamen dolu
        malzemeyle destekli bir nokta.

    Bu, tolerans/kose-yakinligi tahminlerinden bagimsizdir; 4 vertex'li kucuk
    parcada da, 900+ vertex'li karmasik/ic bukey parcada da AYNI guvenle
    calisir ve parcayi asla desteksiz birakmaz."""
    n = len(pts)
    if n == 0:
        return 0
    dx, dy = d
    nrm = math.hypot(dx, dy) or 1.0
    dx, dy = dx / nrm, dy / nrm
    proj = [p[0] * dx + p[1] * dy for p in pts]
    mx = max(proj)

    xmin, ymin, xmax, ymax, w, h = bbox_ve_olcu(pts)
    diag = math.hypot(w, h) or 1.0
    band = diag * band_orani

    adaylar = [i for i in range(n) if proj[i] >= mx - band]
    if len(adaylar) == 1:
        return adaylar[0]
    # Duz sag-ust kenar: dik eksende (perp) ORTADAKI adayi sec
    px, py = -dy, dx
    adaylar.sort(key=lambda i: pts[i][0] * px + pts[i][1] * py)
    return adaylar[len(adaylar) // 2]


def _baslangic_hedef(pts, **kw):
    """Baslangicin idealde OLMASI gereken hedef noktayi ve aday bandi doner.

    Doner: (tx, ty, uzun_ince, band_idxler, serit_mi)
      * Normal parca + yatay serit: hedef UST kenarda, soldan `frac_x`
        (varsayilan %20 = sol-ust). Aday band = UST bant icindeki vertex'ler.
      * Dikey serit: hedef destek tarafindaki yan kenarda, ucundan degil
        `SERIT_Y_ORANI` kadar iceride (iki uctan da destekli).

    Yatay hedef orani ve serit tarafi `destek_yonu`nun dx isaretinden turer:
    dx<0 -> sol (varsayilan), dx>0 -> sag, dx~0 -> orta. Isterseniz dogrudan
    `bas_x_orani` gecebilirsiniz."""
    n = len(pts)
    xmin, ymin, xmax, ymax, w, h = bbox_ve_olcu(pts)
    uzun_ince = uzun_ince_mi(w, h)

    d = kw.get("destek_yonu", DESTEK_YONU)
    dx = d[0] if d else -1.0
    if "bas_x_orani" in kw:
        frac_x = kw["bas_x_orani"]
    elif dx < -0.05:
        frac_x = BASLANGIC_X_ORANI            # sol-ust
    elif dx > 0.05:
        frac_x = 1.0 - BASLANGIC_X_ORANI      # sag-ust
    else:
        frac_x = 0.5                          # orta-ust
    sol_taraf = dx <= 0.05
    ust_band = kw.get("ust_bant_orani", UST_BANT_ORANI)
    serit_y = kw.get("serit_y_orani", SERIT_Y_ORANI)

    # Dikey serit: uzun kenar dusey -> baslangic destek tarafindaki yan kenarda.
    if uzun_ince and h > w:
        tx = xmin if sol_taraf else xmax
        ty = ymin + serit_y * h
        return tx, ty, uzun_ince, list(range(n)), True

    # Normal parca + yatay serit: ust bantta, yatayda hedefe en yakin.
    tx = xmin + frac_x * w
    ty = ymax
    if h > 1e-12:
        band = [i for i in range(n) if (pts[i][1] - ymin) >= (1.0 - ust_band) * h]
    else:
        band = list(range(n))
    if not band:
        band = list(range(n))
    return tx, ty, uzun_ince, band, False


def baslangic_ucu_indeks(pts, **kw):
    """Baslangic hedefine en yakin MEVCUT vertex'in indeksini secer (yeni node
    EKLEMEZ). `baslangic_indeksi_belirle`nin vertex-yalniz cekirdegi; ayrica
    dogrudan cagirilabilir. Bkz. `_baslangic_hedef`."""
    n = len(pts)
    if n == 0:
        return 0
    tx, ty, _uzun, band, serit = _baslangic_hedef(pts, **kw)
    yw = 1.0 if serit else kw.get("ust_y_agirlik", UST_Y_AGIRLIK)
    return min(band, key=lambda i: (pts[i][0] - tx) ** 2
               + yw * (pts[i][1] - ty) ** 2)


def baslangic_indeksi_belirle(pts, **kw):
    """Baslangici sol-ust (elle-optimize) hedefine gore belirler.

    Once hedefe (ust kenar, soldan `BASLANGIC_X_ORANI`) en yakin mevcut vertex
    bulunur. Vertex hedefe yeterince yakinsa (`BASLANGIC_KABUL_TOL`) o kullanilir;
    degilse ust kenarin DUZ segmenti uzerine TAM hedefte bir baslangic node'u
    eklenir -> ArtCAM'de elle yapilan mid-edge yerlesimin karsiligi. Boylece
    sade dikdortgen parcalarda bile baslangic sol-ust ~%20 noktaya oturur.
    Node ekleme `nokta_ekle=False` ile kapatilabilir (yalnizca mevcut vertex).

    Doner: (indeks, uzun_ince, eklenecek)
      indeks==None ve eklenecek=(seg_idx, yeni_pt) ise cagiran node ekler;
      aksi halde indeks gecerli bir vertex indeksidir, eklenecek=None.
    """
    n = len(pts)
    xmin, ymin, xmax, ymax, w, h = bbox_ve_olcu(pts)
    uzun_ince = uzun_ince_mi(w, h)
    if n == 0:
        return 0, uzun_ince, None

    tx, ty, uzun_ince, band, serit = _baslangic_hedef(pts, **kw)
    yw = 1.0 if serit else kw.get("ust_y_agirlik", UST_Y_AGIRLIK)
    i = min(band, key=lambda k: (pts[k][0] - tx) ** 2 + yw * (pts[k][1] - ty) ** 2)

    # Serit parcalarda ya da node ekleme kapaliysa mevcut vertex'i kullan.
    if serit or not kw.get("nokta_ekle", True):
        return i, uzun_ince, None

    diag = math.hypot(w, h) or 1.0
    dist = math.hypot(pts[i][0] - tx, pts[i][1] - ty)
    tol = kw.get("kabul_tol_orani", BASLANGIC_KABUL_TOL) * diag
    if dist <= tol:
        return i, uzun_ince, None

    # Hedefte mevcut vertex yok -> ust kenar DUZ segmentine tam hedefte ekle.
    eklenen = en_uygun_duz_segment_ekleme_noktasi(pts, (tx, ty))
    if eklenen is not None:
        return None, uzun_ince, eklenen
    return i, uzun_ince, None
