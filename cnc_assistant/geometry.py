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

# BASLANGIC (lead-in) hedefi -- normal parcalar icin, parcanin GERCEK EN UST
# bolgesi (ust bant kosusu) ICINDE, o bolgenin SOLUNDAN bu oranda bir nokta
# hedeflenir (0 = bolgenin sol ucu, 1 = sag ucu). Nokta daima gercek ust kontura
# oturur -> egik "N" gibi parcalarda egime DEGIL, gercek uste denk gelir.
BASLANGIC_X_ORANI = 0.22

# Kose kacinma payi (bbox eninin orani): baslangic, ust bolgenin uc (kose)
# noktalarindan en az bu kadar iceride tutulur -> "tam kosede" degil, az iceride.
BASLANGIC_KOSE_PAYI = 0.05

# Ust bolge (kose) arama bandi: parca boyunun bu orani kadar ustteki bolgeler
# "aday ust bolge" sayilir. GENIS tutulur (~%35) -> ust kismi SAG'da olan (sol
# tarafi daha alcak) karmasik/serpme parcalarda (ok/kama, yan yatik harfler)
# bile SOL bolge yakalanir; secilen X'te nokta yine gercek ust kontura (ust
# zarf) oturur, gobege/egime dusmez. Dar band ust kismi sagda olan parcalarda
# yanlislikla sag-uste kayiyordu; genis band bunu duzeltir.
UST_BANT_ORANI = 0.35

# Ust bolge (kose) aday esigi: bir ust bolge, bbox eninin bu orani kadar
# genisse "kayda deger" sayilir (kucuk sivri tepeler yerine gercek ust kenar
# tercih edilir). Tek bolge varsa yine o kullanilir.
MIN_KOSE_ORANI = 0.06

# Dikey ince serit parcalarda baslangic: destek tarafi (varsayilan SOL) kenar
# uzerinde, alttan bu oranda -> serit kesilirken iki uctan da destekli kalir.
SERIT_Y_ORANI = 0.25

# Dikey serit / "I" esigi: parca boyunca AZAMI yatay kalinlik / yukseklik bu
# degerin altindaysa parca "serit" sayilir (bbox oranindan bagimsiz -> serifli
# "I" de yakalanir). Bunlarin baslangici sag kenar orta-altta olur.
SERIT_KALINLIK_ORANI = 0.24

# Ust bolge secimi: en genis (en destekli) ust bolge tercih edilir; birden cok
# bolge bu oranin ustunde genislikteyse destek yonundeki (sol) secilir. Boylece
# sivri tepe (orn. yan yatik "A"nin ucu) yerine genis/duz ust kenar secilir.
UST_GENIS_TOLERANS = 0.70

# Cok uzun (kirmizi-onizleme/riskli) YATAY serit parcalarda baslangicin ust
# kontur uzerindeki yatay konumu (soldan): sag-uste yakin (elle-optimize ~0.89).
YATAY_SERIT_X_ORANI = 0.88

# Baslangic hedefine mevcut bir vertex bu kadar yakinsa (bbox kosegeninin orani)
# o vertex kullanilir; degilse ust kontur DUZ segmenti uzerine TAM hedefte tek
# bir lead-in node'u eklenir (sekil %100 korunur). All-straight polyline'larda
# (bulge yok) bu ekleme her zaman geometriyi birebir korur.
BASLANGIC_KABUL_TOL = 0.02

# --- Geriye donuk uyumluluk (eski API/testler) ---
UST_Y_AGIRLIK = 0.10

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


def _yay_parametreleri(p1, p2):
    """LWPOLYLINE bulge segmentinin yay parametreleri: (cx, cy, r, a1, a2, ccw)
    ya da duz/dejenere segmentte None."""
    b = p1[4]
    if abs(b) < 1e-12:
        return None
    x1, y1, x2, y2 = p1[0], p1[1], p2[0], p2[1]
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy)
    if L < 1e-12:
        return None
    s = b * L / 2.0
    r = L * (1 + b * b) / (4 * abs(b))
    rx, ry = dy / L, -dx / L
    off = (s - r) if b > 0 else (s + r)
    cx, cy = (x1 + x2) / 2 + rx * off, (y1 + y2) / 2 + ry * off
    a1 = math.atan2(y1 - cy, x1 - cx)
    a2 = math.atan2(y2 - cy, x2 - cx)
    return cx, cy, r, a1, a2, (b > 0)


def _aci_arada(a, a1, a2, ccw):
    TAU = 2 * math.pi
    if ccw:
        return ((a - a1) % TAU) <= ((a2 - a1) % TAU) + 1e-9
    return ((a1 - a) % TAU) <= ((a1 - a2) % TAU) + 1e-9


def ust_kontur_y(pts, X):
    """Verilen X'te parcanin GERCEK UST konturunun (ust zarf) y degeri ve
    uzerinde bulundugu segment. Doner: (y, seg_idx, yay_mi) veya None.
    Duz ve yay (bulge) segmentlerini birlikte ele alir."""
    n = len(pts)
    best = None
    for i in range(n):
        p1, p2 = pts[i], pts[(i + 1) % n]
        if abs(p1[4]) < 1e-12:
            x1, y1, x2, y2 = p1[0], p1[1], p2[0], p2[1]
            lo, hi = (x1, x2) if x1 <= x2 else (x2, x1)
            if abs(x2 - x1) < 1e-12:
                if abs(X - x1) <= 1e-9:
                    y = max(y1, y2)
                else:
                    continue
            elif lo - 1e-9 <= X <= hi + 1e-9:
                t = (X - x1) / (x2 - x1)
                y = y1 + t * (y2 - y1)
            else:
                continue
            if best is None or y > best[0]:
                best = (y, i, False)
        else:
            prm = _yay_parametreleri(p1, p2)
            if prm is None:
                continue
            cx, cy, r, a1, a2, ccw = prm
            d = X - cx
            if abs(d) > r + 1e-9:
                continue
            yy = math.sqrt(max(0.0, r * r - d * d))
            for y in (cy + yy, cy - yy):
                a = math.atan2(y - cy, X - cx)
                if _aci_arada(a, a1, a2, ccw) and (best is None or y > best[0]):
                    best = (y, i, True)
    return best


def sag_kontur_x(pts, Y):
    """Verilen Y'de parcanin GERCEK SAG konturunun (sag zarf) x degeri ve
    segmenti. Doner: (x, seg_idx, yay_mi) veya None."""
    n = len(pts)
    best = None
    for i in range(n):
        p1, p2 = pts[i], pts[(i + 1) % n]
        if abs(p1[4]) < 1e-12:
            x1, y1, x2, y2 = p1[0], p1[1], p2[0], p2[1]
            lo, hi = (y1, y2) if y1 <= y2 else (y2, y1)
            if abs(y2 - y1) < 1e-12:
                if abs(Y - y1) <= 1e-9:
                    x = max(x1, x2)
                else:
                    continue
            elif lo - 1e-9 <= Y <= hi + 1e-9:
                t = (Y - y1) / (y2 - y1)
                x = x1 + t * (x2 - x1)
            else:
                continue
            if best is None or x > best[0]:
                best = (x, i, False)
        else:
            prm = _yay_parametreleri(p1, p2)
            if prm is None:
                continue
            cx, cy, r, a1, a2, ccw = prm
            d = Y - cy
            if abs(d) > r + 1e-9:
                continue
            xx = math.sqrt(max(0.0, r * r - d * d))
            for x in (cx + xx, cx - xx):
                a = math.atan2(Y - cy, x - cx)
                if _aci_arada(a, a1, a2, ccw) and (best is None or x > best[0]):
                    best = (x, i, True)
    return best


def sol_kontur_x(pts, Y):
    """Verilen Y'de parcanin GERCEK SOL konturunun (sol zarf) x degeri.
    Doner: (x, seg_idx, yay_mi) veya None."""
    n = len(pts)
    best = None
    for i in range(n):
        p1, p2 = pts[i], pts[(i + 1) % n]
        if abs(p1[4]) < 1e-12:
            x1, y1, x2, y2 = p1[0], p1[1], p2[0], p2[1]
            lo, hi = (y1, y2) if y1 <= y2 else (y2, y1)
            if abs(y2 - y1) < 1e-12:
                if abs(Y - y1) <= 1e-9:
                    x = min(x1, x2)
                else:
                    continue
            elif lo - 1e-9 <= Y <= hi + 1e-9:
                t = (Y - y1) / (y2 - y1)
                x = x1 + t * (x2 - x1)
            else:
                continue
            if best is None or x < best[0]:
                best = (x, i, False)
        else:
            prm = _yay_parametreleri(p1, p2)
            if prm is None:
                continue
            cx, cy, r, a1, a2, ccw = prm
            d = Y - cy
            if abs(d) > r + 1e-9:
                continue
            xx = math.sqrt(max(0.0, r * r - d * d))
            for x in (cx + xx, cx - xx):
                a = math.atan2(Y - cy, x - cx)
                if _aci_arada(a, a1, a2, ccw) and (best is None or x < best[0]):
                    best = (x, i, True)
    return best


def azami_yatay_kalinlik_orani(pts, xmin, ymin, w, h, levels=11):
    """Parcanin yukseklik boyunca AZAMI yatay kalinliginin (sag zarf - sol zarf)
    yukseklige oranini doner. Dikey serit / "I" gibi harfleri tespit icin:
    boyunca ince (bu oran kucuk) olanlar serit sayilir. bbox oranindan daha
    guveniolir -- serifli "I"de bbox genis gorunse de govde incedir."""
    if h <= 1e-12:
        return 1.0
    tmax = 0.0
    for k in range(1, levels):
        Y = ymin + h * k / levels
        sol = sol_kontur_x(pts, Y)
        sag = sag_kontur_x(pts, Y)
        if sol is not None and sag is not None:
            tmax = max(tmax, sag[0] - sol[0])
    return tmax / h


def dikey_serit_mi(pts, w, h, esik=None):
    """Parca dikey ince serit / "I" benzeri mi? (uzun kenar dusey ve boyunca
    ince). CNC'de bu parcalarin baslangici SAG kenarda, orta-alt bolgede
    olmali (iki uctan destekli). bbox oranina degil, boyunca kalinliga bakar."""
    if h <= w:
        return False
    xmin = min(p[0] for p in pts)
    ymin = min(p[1] for p in pts)
    esik = SERIT_KALINLIK_ORANI if esik is None else esik
    return azami_yatay_kalinlik_orani(pts, xmin, ymin, w, h) < esik


def ust_kosular(pts, ythr, w):
    """Parcanin ust bant (y >= ythr) icindeki GERCEK ust kontur parcalarini
    (X araliklari) doner: [(x_sol, x_sag), ...]. Duz ve yay segmentleri ele
    alinir. Yakin araliklar birlestirilir. Bu, parcanin 'en ust bolgeleri'ni
    verir -> baslangic daima bu bolgelerden birine (gercek ustune) oturur,
    parcanin gobegine/egimine DEGIL."""
    ints = []
    n = len(pts)
    for i in range(n):
        p1, p2 = pts[i], pts[(i + 1) % n]
        if abs(p1[4]) < 1e-12:
            x1, y1, x2, y2 = p1[0], p1[1], p2[0], p2[1]
            if max(y1, y2) < ythr:
                continue
            if min(y1, y2) >= ythr:
                ints.append((min(x1, x2), max(x1, x2)))
            elif abs(y2 - y1) > 1e-12:
                t = (ythr - y1) / (y2 - y1)
                xc = x1 + t * (x2 - x1)
                a, b = (x1, xc) if y1 >= ythr else (xc, x2)
                ints.append((min(a, b), max(a, b)))
        else:
            prm = _yay_parametreleri(p1, p2)
            if prm is None:
                continue
            cx, cy, r, a1, a2, ccw = prm
            TAU = 2 * math.pi
            sweep = ((a2 - a1) % TAU) if ccw else -((a1 - a2) % TAU)
            k = 24
            run = []
            for j in range(k + 1):
                ang = a1 + sweep * j / k
                x, y = cx + r * math.cos(ang), cy + r * math.sin(ang)
                if y >= ythr:
                    run.append(x)
                elif run:
                    ints.append((min(run), max(run)))
                    run = []
            if run:
                ints.append((min(run), max(run)))
    if not ints:
        return []
    ints.sort()
    gap = 0.02 * w
    merged = [list(ints[0])]
    for a, b in ints[1:]:
        if a <= merged[-1][1] + gap:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def _baslangic_hedef_nokta(pts, **kw):
    """Baslangicin idealde OLMASI gereken noktayi (parcanin GERCEK konturu
    uzerinde) ve konturdaki segmentini doner.

    Doner: (tx, ty, seg_idx, yay_mi, uzun_ince)

    YONTEM (kritik): once parcanin GERCEK EN UST bolgeleri (ust bant kosulari)
    bulunur; baslangic DAIMA bu bolgelerden birine oturur. Boylece parcanin
    gobegine/egimine (egik "N"in inen kenarina, "V"nin dibine) ASLA dusmez.

      * Dikey ince serit / "I": SAG kontur uzerinde, alttan `serit_y`
        (sag-orta/sag-alt). Serit tespiti boyunca kalinliga bakar (bbox degil).
      * Cok uzun (riskli) yatay serit: en genis ust bolgede, soldan
        `YATAY_SERIT_X_ORANI` (ust-orta ile sag-ust arasi).
      * Normal parca: EN GENIS (en destekli) ust bolge secilir -> sivri tepe
        (orn. yan yatik "A"nin ucu) yerine genis/duz ust kenar. O bolgenin
        solundan `BASLANGIC_X_ORANI` kadar iceride (kosede degil). Nokta o
        X'teki gercek ust kontura (ust zarf) oturur."""
    xmin, ymin, xmax, ymax, w, h = bbox_ve_olcu(pts)
    uzun_ince = uzun_ince_mi(w, h)
    serit_y = kw.get("serit_y_orani", SERIT_Y_ORANI)

    d = kw.get("destek_yonu", DESTEK_YONU)
    dx = d[0] if d else -1.0

    # 1) Dikey ince serit / "I" -> sag kontur, sag-orta/sag-alt. Serit tespiti
    #    boyunca AZAMI yatay kalinliga bakar (serifli "I" de yakalanir).
    serit = dikey_serit_mi(pts, w, h,
                           kw.get("serit_kalinlik_orani", SERIT_KALINLIK_ORANI))
    if serit:
        ty = ymin + serit_y * h
        # Destek tarafi (varsayilan SOL): dx<=0 -> sol kontur, dx>0 -> sag.
        if dx > 0.05:
            r = sag_kontur_x(pts, ty)
            return (r[0], ty, r[1], r[2], True) if r else (xmax, ty, None, False, True)
        r = sol_kontur_x(pts, ty)
        return (r[0], ty, r[1], r[2], True) if r else (xmin, ty, None, False, True)

    # 2) Gercek ust bolgeler (ust bant kosulari).
    band = kw.get("ust_bant_orani", UST_BANT_ORANI)
    kosular = ust_kosular(pts, ymax - band * h, w) if h > 1e-12 else []
    if not kosular:
        tx = xmin + BASLANGIC_X_ORANI * w
        r = ust_kontur_y(pts, tx)
        return (tx, r[0] if r else ymax,
                r[1] if r else None, r[2] if r else False, uzun_ince)

    # 3) Cok uzun/riskli yatay serit -> en genis bolgede, orta-sag.
    tabaka_w = kw.get("tabaka_w")
    boyut_orani = kw.get("boyut_orani", 0.50)
    riskli_yatay = (w > h and tabaka_w and tabaka_w > 0
                    and (w / tabaka_w) > boyut_orani)

    if riskli_yatay and "bas_x_orani" not in kw:
        a, b = max(kosular, key=lambda ab: ab[1] - ab[0])
        frac = kw.get("yatay_serit_x_orani", YATAY_SERIT_X_ORANI)
        tx = a + frac * (b - a)
    else:
        # Hedef X orani (bolge ICINDE soldan): destek_yonu'nun dx isaretine gore.
        if "bas_x_orani" in kw:
            frac = kw["bas_x_orani"]
        elif dx > 0.05:
            frac = 1.0 - BASLANGIC_X_ORANI
        elif abs(dx) <= 0.05:
            frac = 0.5
        else:
            frac = BASLANGIC_X_ORANI
        # Aday bolge: yeterince genis (kayda deger) ust bolgeler arasindan
        # destek yonundeki UC bolge -> varsayilan SOL (elle-optimize dosyasi
        # bu yonde). dx>0 ise en sagdaki. Kucuk sivri tepeler (min_kose altinda)
        # elenir, boylece gercek ust kenar tercih edilir.
        min_run = kw.get("min_kose_orani", MIN_KOSE_ORANI) * w
        genis = [r for r in kosular if (r[1] - r[0]) >= min_run] or kosular
        a, b = (max(genis, key=lambda ab: ab[1]) if dx > 0.05
                else min(genis, key=lambda ab: ab[0]))
        iw = b - a
        kose_payi = min(kw.get("kose_payi_orani", BASLANGIC_KOSE_PAYI) * w, 0.4 * iw)
        tx = a + frac * iw
        tx = max(a + kose_payi, min(tx, b - kose_payi)) if iw > 1e-9 else (a + b) / 2

    r = ust_kontur_y(pts, tx)
    if r is not None:
        return tx, r[0], r[1], r[2], uzun_ince
    return tx, ymax, None, False, uzun_ince


def baslangic_ucu_indeks(pts, **kw):
    """Baslangic hedefine en yakin MEVCUT vertex'in indeksini secer (yeni node
    EKLEMEZ). `baslangic_indeksi_belirle`nin vertex-yalniz cekirdegi."""
    n = len(pts)
    if n == 0:
        return 0
    tx, ty, _seg, _yay, _uzun = _baslangic_hedef_nokta(pts, **kw)
    return min(range(n), key=lambda i: (pts[i][0] - tx) ** 2 + (pts[i][1] - ty) ** 2)


def baslangic_indeksi_belirle(pts, **kw):
    """Baslangici parcanin GERCEK ust/sag konturu uzerinde belirler.

    Hedef nokta `_baslangic_hedef_nokta` ile bulunur (daima kontur uzerinde,
    egik "N" gibi parcalarda bile gercek uste denk gelir, koseden az iceride).
    Hedefe cok yakin mevcut bir vertex varsa (`BASLANGIC_KABUL_TOL`) o kullanilir;
    degilse hedefin uzerinde bulundugu DUZ segmente tam hedefte tek bir lead-in
    node'u eklenir (sekil %100 korunur). Hedef bir YAY segmenti uzerindeyse
    (bulge != 0) node eklenmez -> yayi bozmamak icin en yakin mevcut vertex
    kullanilir. Node ekleme `nokta_ekle=False` ile de kapatilabilir.

    Doner: (indeks, uzun_ince, eklenecek)
      indeks==None ve eklenecek=(seg_idx, yeni_pt) ise cagiran node ekler;
      aksi halde indeks gecerli bir vertex indeksidir, eklenecek=None.
    """
    n = len(pts)
    xmin, ymin, xmax, ymax, w, h = bbox_ve_olcu(pts)
    uzun_ince = uzun_ince_mi(w, h)
    if n == 0:
        return 0, uzun_ince, None

    tx, ty, seg_idx, yay_mi, uzun_ince = _baslangic_hedef_nokta(pts, **kw)
    i = min(range(n), key=lambda k: (pts[k][0] - tx) ** 2 + (pts[k][1] - ty) ** 2)

    diag = math.hypot(w, h) or 1.0
    dist = math.hypot(pts[i][0] - tx, pts[i][1] - ty)
    tol = kw.get("kabul_tol_orani", BASLANGIC_KABUL_TOL) * diag

    # Hedefe yeterince yakin vertex var, ya da ekleme kapali, ya da hedef yay
    # uzerinde (yayi bozmamak icin) -> mevcut vertex'i kullan.
    if dist <= tol or not kw.get("nokta_ekle", True) or yay_mi or seg_idx is None:
        return i, uzun_ince, None

    # Hedef DUZ bir segment uzerinde -> tam hedefte node ekle (sekil korunur).
    yeni_pt = (tx, ty, 0.0, 0.0, 0.0)
    return None, uzun_ince, (seg_idx, yeni_pt)
