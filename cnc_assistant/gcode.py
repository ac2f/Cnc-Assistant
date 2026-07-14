#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
G-Code blok siralama
====================
G-Code URETILMEZ. Mevcut satirlar AYNEN korunur; yalnizca bagimsiz kesim
bloklarinin SIRASI degistirilir.

Siralama hedefi: malzeme her zaman destekte kalacak sekilde SOL-ALTTAN
SAG-USTE dogru ilerlemek. Ayrica bir parcanin "uzerine uzanan / golgede
birakan" parcalar once temizlenir (engel-farkindalikli siralama).

`GCodeProgram` sinifi dosyayi header / kesim-bloklari / footer olarak ayristirir;
hem otomatik siralama hem de etkilesimli (elle) duzenleme bunu kullanir.
"""

import math
import os
import re

_WORD_RE = re.compile(r"([A-Za-z])\s*([+-]?\d+\.?\d*)")
_BITIS_RE = re.compile(r"\b(M0?2|M30|M0?5|M0?9|G28|G53)\b|^\s*%\s*$", re.I)

# X-araliklari "ayni kolonda / cakisan" sayilmasi icin tolerans orani.
_X_CAKISMA_TOLERANSI = 0.02


def satir_kelimeleri(satir):
    s = re.sub(r"\(.*?\)", "", satir)     # ( ... ) yorumlari
    s = s.split(";", 1)[0]                 # ; yorumlari
    return {h.upper(): float(v) for h, v in _WORD_RE.findall(s)}


def _blok_basi_mi(satir):
    """Yeni kesim blogunun basi: X ve Y iceren G0/G00 hizli hareket."""
    w = satir_kelimeleri(satir)
    return w.get("G") == 0.0 and "X" in w and "Y" in w


def g91_var_mi(satirlar):
    """Artimli mod (G91) kontrolu. G91.1 (yay merkezi modu) haric."""
    rx = re.compile(r"\bG91(?!\.)\b", re.I)
    for s in satirlar:
        temiz = re.sub(r"\(.*?\)", "", s).split(";", 1)[0]
        if rx.search(temiz):
            return True
    return False


# ----------------------------------------------------------------------
# Blok geometri yardimcilari
# ----------------------------------------------------------------------

def blok_bas_xy(blok):
    w = satir_kelimeleri(blok[0])
    return (w.get("X", 0.0), w.get("Y", 0.0))


def _blok_son_xy(blok, varsayilan):
    x, y = varsayilan
    for s in blok:
        w = satir_kelimeleri(s)
        if "X" in w:
            x = w["X"]
        if "Y" in w:
            y = w["Y"]
    return (x, y)


def blok_bbox(blok):
    xs, ys = [], []
    for s in blok:
        w = satir_kelimeleri(s)
        if "X" in w:
            xs.append(w["X"])
        if "Y" in w:
            ys.append(w["Y"])
    if not xs or not ys:
        bx, by = blok_bas_xy(blok)
        return (bx, by, bx, by)
    return (min(xs), min(ys), max(xs), max(ys))


def blok_polygon(blok):
    """Bloktaki hareketlerden (mutlak konum takip edilerek) yaklasik kontur
    poligonunu (x, y) listesi olarak cikarir. Icerme (nesting) testi icin."""
    pts = []
    x = y = None
    for s in blok:
        w = satir_kelimeleri(s)
        if "X" in w or "Y" in w:
            if "X" in w:
                x = w["X"]
            if "Y" in w:
                y = w["Y"]
            if x is not None and y is not None:
                pts.append((x, y))
    return pts


def blok_yol(blok, yay_bolut=14):
    """Bloktaki hareketleri (G0/G1 dogru + G2/G3 YAY interpolasyonu ile)
    gercek takim yolu noktalarina cevirir. Onizlemede yaylar chord yerine
    gercek egri olarak cizilir. I/J (merkez) ve R (yaricap) desteklenir."""
    pts = []
    x = y = None
    g = None
    for s in blok:
        w = satir_kelimeleri(s)
        if "G" in w and w["G"] in (0.0, 1.0, 2.0, 3.0):
            g = w["G"]
        if not ("X" in w or "Y" in w):
            continue
        nx = w.get("X", x if x is not None else 0.0)
        ny = w.get("Y", y if y is not None else 0.0)
        if x is None or y is None:
            x, y = nx, ny
            pts.append((x, y))
            continue
        if g in (2.0, 3.0) and ("I" in w or "J" in w or "R" in w):
            pts.extend(_yay_noktalari(x, y, nx, ny, w, g, yay_bolut)[1:])
        else:
            pts.append((nx, ny))
        x, y = nx, ny
    return pts


def _yay_noktalari(x0, y0, x1, y1, w, g, bolut):
    """G2/G3 yayini nokta dizisine acar."""
    if "I" in w or "J" in w:
        cx, cy = x0 + w.get("I", 0.0), y0 + w.get("J", 0.0)
    else:                                   # R modu
        r = w["R"]
        mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy)
        if d < 1e-9 or abs(r) < d / 2.0:
            return [(x0, y0), (x1, y1)]
        h = math.sqrt(max(r * r - (d / 2.0) ** 2, 0.0))
        sgn = 1 if ((g == 3.0) == (r > 0)) else -1
        cx = mx + sgn * h * (-dy / d)
        cy = my + sgn * h * (dx / d)
    r = math.hypot(x0 - cx, y0 - cy)
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    if g == 2.0:                            # saat yonu (azalan aci)
        while a1 >= a0:
            a1 -= 2 * math.pi
    else:                                   # saat yonu tersi (artan aci)
        while a1 <= a0:
            a1 += 2 * math.pi
    n = max(2, int(abs(a1 - a0) / (2 * math.pi) * (bolut * 4)) + 1)
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n),
             cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def _yay_merkez(x0, y0, x1, y1, w, g):
    """G2/G3 yayinin merkezini (cx, cy) doner (I/J veya R)."""
    if "I" in w or "J" in w:
        return x0 + w.get("I", 0.0), y0 + w.get("J", 0.0)
    r = w["R"]
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    dx, dy = x1 - x0, y1 - y0
    dd = math.hypot(dx, dy)
    if dd < 1e-9 or abs(r) < dd / 2.0:
        return mx, my
    h = math.sqrt(max(r * r - (dd / 2.0) ** 2, 0.0))
    sgn = 1 if ((g == 3.0) == (r > 0)) else -1
    return mx + sgn * h * (-dy / dd), my + sgn * h * (dx / dd)


def _yay_bezier(x0, y0, x1, y1, w, g):
    """G2/G3 yayini kubik bezier ('C') komutlarina cevirir (<=90 derece
    parcalara bolerek; her parca gorsel olarak birebir yay). SVG'de sonsuz
    yaklastirmada purüzsuz kalir."""
    cx, cy = _yay_merkez(x0, y0, x1, y1, w, g)
    r = math.hypot(x0 - cx, y0 - cy)
    if r < 1e-9:
        return [["L", round(x1, 4), round(y1, 4)]]
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    if g == 2.0:                       # saat yonu (azalan aci)
        while a1 >= a0:
            a1 -= 2 * math.pi
    else:                              # saat yonu tersi (artan aci)
        while a1 <= a0:
            a1 += 2 * math.pi
    toplam = a1 - a0
    n = max(1, int(math.ceil(abs(toplam) / (math.pi / 2.0))))
    dth = toplam / n
    k = (4.0 / 3.0) * math.tan(dth / 4.0) * r
    cmds = []
    for i in range(n):
        b0 = a0 + dth * i
        b1 = b0 + dth
        p0 = (cx + r * math.cos(b0), cy + r * math.sin(b0))
        p3 = (cx + r * math.cos(b1), cy + r * math.sin(b1))
        c1 = (p0[0] - k * math.sin(b0), p0[1] + k * math.cos(b0))
        c2 = (p3[0] + k * math.sin(b1), p3[1] - k * math.cos(b1))
        cmds.append(["C", round(c1[0], 4), round(c1[1], 4),
                     round(c2[0], 4), round(c2[1], 4),
                     round(p3[0], 4), round(p3[1], 4)])
    return cmds


def blok_svg_komut(blok):
    """Bloktaki hareketleri SVG yol komutlarina cevirir: G0/G1 -> M/L,
    G2/G3 -> C (kubik bezier). Duz cizgi parcalari L; yaylar gercek egri.
    Frontend bunlari dogrudan SVG path 'd' olarak cizer -> vektorel, kompakt."""
    cmds = []
    x = y = None
    g = None
    for s in blok:
        w = satir_kelimeleri(s)
        if "G" in w and w["G"] in (0.0, 1.0, 2.0, 3.0):
            g = w["G"]
        if not ("X" in w or "Y" in w):
            continue
        nx = w.get("X", x if x is not None else 0.0)
        ny = w.get("Y", y if y is not None else 0.0)
        if x is None or y is None:
            x, y = nx, ny
            cmds.append(["M", round(x, 4), round(y, 4)])
            continue
        if g in (2.0, 3.0) and ("I" in w or "J" in w or "R" in w):
            cmds.extend(_yay_bezier(x, y, nx, ny, w, g))
        else:
            cmds.append(["L", round(nx, 4), round(ny, 4)])
        x, y = nx, ny
    return cmds


def birim_tespit(satirlar):
    """G20 (inch) / G21 (mm) tespit eder. Bulunamazsa None."""
    for s in satirlar:
        temiz = re.sub(r"\(.*?\)", "", s).split(";", 1)[0]
        if re.search(r"\bG20\b", temiz):
            return "inch"
        if re.search(r"\bG21\b", temiz):
            return "mm"
    return None


def _poligon_merkez(poly):
    if not poly:
        return (0.0, 0.0)
    return (sum(p[0] for p in poly) / len(poly),
            sum(p[1] for p in poly) / len(poly))


def _nokta_poligon_icinde(nokta, poly):
    """Ray-casting: nokta kapali poligonun icinde mi?"""
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


def _bbox_alani(b):
    return (b[2] - b[0]) * (b[3] - b[1])


def _ic_ice_mi(i_bbox, i_poly, d_bbox, d_poly, tol):
    """i blogu, d blogunun ICINDE mi? (i=ic aday, d=dis aday)

    Kosullar (hepsi saglanmali):
      * i'nin bbox'i d'nin bbox'i icinde (tolerans ile),
      * d'nin alani i'den belirgin sekilde buyuk (esit/multi-paso kendini
        icermesin diye),
      * i'nin agirlik merkezi d'nin poligonu icinde (ray-casting).
    """
    if len(d_poly) < 3:
        return False
    # bbox icerme
    if not (d_bbox[0] - tol <= i_bbox[0] and i_bbox[2] <= d_bbox[2] + tol and
            d_bbox[1] - tol <= i_bbox[1] and i_bbox[3] <= d_bbox[3] + tol):
        return False
    # alan: dis belirgin buyuk olmali (ayni kontur multi-paso -> icerme yok)
    if _bbox_alani(d_bbox) <= _bbox_alani(i_bbox) + max(tol * tol, 1e-9):
        return False
    # merkez testi
    return _nokta_poligon_icinde(_poligon_merkez(i_poly), d_poly)


def containment_derinlik(bloklar):
    """Her blogun ICERME DERINLIGINI doner: kendisini iceren kac blok var.
    Derinligi buyuk olan (en icteki) once kesilmelidir. Bu, bir 'O' harfinin
    gobegindeki tum vektorlerin dis konturdan ONCE kesilmesini %100 garanti
    etmek icin kullanilir."""
    n = len(bloklar)
    polys = [blok_polygon(b) for b in bloklar]
    bboxes = [blok_bbox(b) for b in bloklar]

    tum = [v for box in bboxes for v in (box[0], box[2])]
    olcek = (max(tum) - min(tum)) if tum else 0.0
    tol = max(olcek * 1e-4, 1e-6)

    derinlik = [0] * n
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if _ic_ice_mi(bboxes[i], polys[i], bboxes[j], polys[j], tol):
                derinlik[i] += 1
    return derinlik


def toplam_bosta_yol(bloklar):
    """Bloklar arasi (kesim disi) XY tasima mesafesi toplami."""
    toplam, konum = 0.0, None
    for blok in bloklar:
        bas = blok_bas_xy(blok)
        if konum is not None:
            toplam += math.hypot(bas[0] - konum[0], bas[1] - konum[1])
        konum = _blok_son_xy(blok, bas)
    return toplam


def blok_kesim_uzunlugu(blok, yay_bolut=14):
    """Bloktaki KESIM (G1/G2/G3 besleme) XY hareketlerinin arc-duyarli toplam
    uzunlugu. G0 (hizli) hareketler HARIC -> gercek talas alinan yol."""
    x = y = None
    g = None
    toplam = 0.0
    for s in blok:
        w = satir_kelimeleri(s)
        if "G" in w and w["G"] in (0.0, 1.0, 2.0, 3.0):
            g = w["G"]
        if not ("X" in w or "Y" in w):
            continue
        nx = w.get("X", x if x is not None else 0.0)
        ny = w.get("Y", y if y is not None else 0.0)
        if x is None or y is None:
            x, y = nx, ny
            continue
        if g in (1.0, 2.0, 3.0):
            if g in (2.0, 3.0) and ("I" in w or "J" in w or "R" in w):
                pts = _yay_noktalari(x, y, nx, ny, w, g, yay_bolut)
                for i in range(1, len(pts)):
                    toplam += math.hypot(pts[i][0] - pts[i - 1][0],
                                         pts[i][1] - pts[i - 1][1])
            else:
                toplam += math.hypot(nx - x, ny - y)
        x, y = nx, ny
    return toplam


def blok_dalis_uzunlugu(blok):
    """Bloktaki ASAGI yonlu Z besleme (dalis/plunge) mesafesi toplami (G1 Z).
    Ilk dalis, bloktaki EN YUKSEK Z'den (geri-cekme yuksekligi) baslar kabul
    edilir -> plunge onceki bloktaki geri-cekme yuksekliginden inse bile sayilir."""
    _, zmax = blok_z_araligi(blok)
    z = zmax                       # geri-cekme yuksekliginden basla
    g = None
    toplam = 0.0
    for s in blok:
        w = satir_kelimeleri(s)
        if "G" in w and w["G"] in (0.0, 1.0, 2.0, 3.0):
            g = w["G"]
        if "Z" in w:
            nz = w["Z"]
            if z is not None and g == 1.0 and nz < z:
                toplam += (z - nz)
            z = nz
    return toplam


def blok_z_araligi(blok):
    """Bloktaki en dusuk/en yuksek Z (kesim derinligi araligi)."""
    zs = []
    for s in blok:
        w = satir_kelimeleri(s)
        if "Z" in w:
            zs.append(w["Z"])
    return (min(zs), max(zs)) if zs else (None, None)


def kesim_feed_tespit(satirlar):
    """Kesim (G1/G2/G3) sirasinda en cok kullanilan F (besleme, birim/dk)
    degerini doner; yoksa None. Modal F takip edilir."""
    from collections import Counter
    g = None
    feed = None
    feedler = []
    for s in satirlar:
        w = satir_kelimeleri(s)
        if "G" in w and w["G"] in (0.0, 1.0, 2.0, 3.0):
            g = w["G"]
        if "F" in w:
            feed = w["F"]
        if g in (1.0, 2.0, 3.0) and feed and ("X" in w or "Y" in w or "Z" in w):
            feedler.append(feed)
    if feedler:
        return Counter(feedler).most_common(1)[0][0]
    return feed


# ----------------------------------------------------------------------
# Siralama stratejileri
# ----------------------------------------------------------------------

def _x_araliklari_cakisiyor_mu(b1, b2, x_tol):
    x1min, _, x1max, _ = b1
    x2min, _, x2max, _ = b2
    return (x1min - x_tol) <= x2max and (x2min - x_tol) <= x1max


def _dongusuz_birlestir(onc_sag, onc_ust, n):
    """Kritik (onc_sag) ve ikincil (onc_ust) oncelik kenarlarini DONGUSUZ bir
    graf (DAG) olarak birlestirir. Once TUM kritik kenarlar eklenir; sonra
    ikincil kenarlardan yalnizca DONGU YARATMAYANLAR eklenir. Doner: her dugum
    icin oncul kumesi (onculler). Boylece topolojik/acgozlu siralama asla
    kilitlenmez ve kalan kisitlar birebir uygulanir."""
    succ = [set() for _ in range(n)]     # succ[u]: u'dan SONRA gelmesi gerekenler
    onc = [set() for _ in range(n)]      # onc[v]: v'den ONCE gelmesi gerekenler

    def _yol_var(s, t):                  # s -> ... -> t yolu var mi?
        if s == t:
            return True
        yig = [s]
        gor = {s}
        while yig:
            u = yig.pop()
            for v in succ[u]:
                if v == t:
                    return True
                if v not in gor:
                    gor.add(v)
                    yig.append(v)
        return False

    def _ekle(u, v):                     # u, v'den ONCE (u -> v)
        if u == v or v in succ[u]:
            return
        if _yol_var(v, u):               # ters yol varsa -> dongu -> ATLA
            return
        succ[u].add(v)
        onc[v].add(u)

    for v in range(n):                   # 1) KRITIK kenarlar (onc_sag)
        for u in onc_sag[v]:
            _ekle(u, v)
    for v in range(n):                   # 2) dongu yaratmayan IKINCIL (onc_ust)
        for u in onc_ust[v]:
            _ekle(u, v)
    return onc


def sol_alt_sag_ust_sirala(bloklar, ebeveyn=None):
    """VARSAYILAN siralama. Bir CNC USTASI gibi dusunur: malzeme AGIRLIKLI
    olarak SAG ve UST'ten sabitlenir; dolayisiyla bir parca kesilirken
    SAGINDA (ve ustunde) daha once kesilmis bir bosluk OLMAMALIDIR ->
    destek daima korunur. Ayrica yol RASTGELE degil, DUZENLI olmalidir.

    `ebeveyn` verilirse (blok basina, kendisini DOGRUDAN iceren blogun
    indeksi ya da None) POLIGON-ICERME kisiti da eklenir: her ic kesim
    (cocuk) kendi dis konturundan (ebeveyn) ONCE kesilir. Boylece icerme
    tek bir KURESEL eniyilemede destek + ic-ice kurallariyla birlikte
    ele alinir (parca-parca post-order parcalanmasi -> gereksiz uzun yol
    sorununu onler).

    Iki asamali kurulur:

    1) DESTEK KISITI (kesin oncelik, asla bozulmaz):
         * i ve j Y'de cakisiyor ve j, i'nin SAGINDA ise -> i, j'den ONCE.
           (j kesilirken saginda -> i tarafinda- kesilmis bosluk kalmaz;
            clamp tarafi/sag en son kesilir)
         * i ve j X'te cakisiyor ve j, i'nin USTUNDE ise -> i, j'den ONCE.
           (ust destek korunur; alttan uste ilerlenir)

    2) Kisiti bozmadan DUZENLI SUPURME: her adimda kesime HAZIR (tum
       onculleri islenmis) parcalar arasindan ALTTAN-USTE / SOLDAN-SAGA
       (satir-satir raster) olani secilir. Boylece onceki 'X-sutunu'
       yaklasiminin tabaka boyunu bir kolonda bir asagi bir yukari
       tarayan sicramalari ortadan kalkar; yol pürüzsüz ilerler.

    Konumlama parcanin GERCEK govdesine (bbox merkezi) gore yapilir;
    lead-in noktasinin yerinden bagimsizdir."""
    n = len(bloklar)
    if n <= 1:
        return list(bloklar)

    bboxlar = [blok_bbox(b) for b in bloklar]
    merkez = [((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0) for b in bboxlar]

    tum_x = [v for b in bboxlar for v in (b[0], b[2])]
    tum_y = [v for b in bboxlar for v in (b[1], b[3])]
    gen_x = (max(tum_x) - min(tum_x)) if tum_x else 0.0
    gen_y = (max(tum_y) - min(tum_y)) if tum_y else 0.0
    # "Gercek" ortusme esigi: yalnizca kenardan DEGEN/temas eden parcalar ayni
    # bant sayilmasin (yoksa dusey yigin, yatay komsu sanilip yanlis siralanir).
    ort_tol = max(max(gen_x, gen_y) * 1e-3, 1e-9)
    eps = 1e-9

    alan = [max((b[2] - b[0]) * (b[3] - b[1]), 0.0) for b in bboxlar]

    # ONCELIK GRAFI. Iki parcanin konumsal iliskisine gore komsuluk turu:
    #   A) BBOX'lari IC ICE (her iki eksende de ortusuyor: bir parca digerinin
    #      govdesine/koynuna oturmus) -> KUCUK/ICTEKI once kesilir (BIRINCIL).
    #      Cunku buyuk parca kesilirse icindeki/koynundaki kucuk parca
    #      desteksiz kalir (icten-disa mantigi; poligon-icerme testi bu tur
    #      konkav yerlesimlerde tutmadigi icin bbox-ic-ice ile yakalanir).
    #      Alanlar ~esitse (kenetlenmis iki benzer parca) ALTTAKI once (ust
    #      destek) -> IKINCIL.
    #   B) Yalniz Y'de ortusuyorlar (ayni yatay bant) -> SAG kisiti (BIRINCIL):
    #      SOLDAKI once. Malzeme SAGDAN sabit; kesilen parcanin saginda
    #      kesilmis bosluk olmamali.
    #   C) Yalniz X'te ortusuyorlar (ayni dusey serit) -> UST kisiti (IKINCIL):
    #      ALTTAKI once.
    # Hicbir eksende gercek ortusme yoksa (capraz) kisit YOK.
    onc_sag = [set() for _ in range(n)]     # BIRINCIL (kritik) oncelikler
    onc_ust = [set() for _ in range(n)]     # IKINCIL oncelikler
    for i in range(n):
        bi = bboxlar[i]
        for j in range(i + 1, n):
            bj = bboxlar[j]
            yov = min(bi[3], bj[3]) - max(bi[1], bj[1])   # Y ortusme (>0 gercek)
            xov = min(bi[2], bj[2]) - max(bi[0], bj[0])   # X ortusme (>0 gercek)
            if yov > ort_tol and xov > ort_tol:           # BBOX'lar kesisiyor
                # ICE-OTURMA orani: ortusme alani / KUCUK bbox alani. ~1 ise
                # kucuk parca buyugun govdesine/koynuna oturmus (gercek
                # ic-ice); dusukse yalnizca komsu kenar cakismasi (bitisik
                # harfler) -> ic-ice DEGIL.
                ov = yov * xov
                kucuk_alan = min(alan[i], alan[j])
                icte = (kucuk_alan > eps and ov / kucuk_alan > 0.80
                        and min(alan[i], alan[j]) < 0.85 * max(alan[i], alan[j]))
                if icte:                                   # (A) GERCEK ic-ice
                    kucuk, buyuk = (i, j) if alan[i] < alan[j] else (j, i)
                    onc_sag[buyuk].add(kucuk)              # kucuk/icteki once (KRITIK)
                else:                                      # (B) kenetli/bitisik: alttaki once
                    dcy = merkez[j][1] - merkez[i][1]
                    if abs(dcy) > eps:
                        (onc_ust[j] if dcy > eps else onc_ust[i]).add(
                            i if dcy > eps else j)
            elif yov > ort_tol:                            # (C) ayni yatay bant -> SAG
                dx = merkez[j][0] - merkez[i][0]
                if abs(dx) > eps:
                    (onc_sag[j] if dx > eps else onc_sag[i]).add(
                        i if dx > eps else j)
            elif xov > ort_tol:                            # (D) ayni dusey serit -> UST
                dy = merkez[j][1] - merkez[i][1]
                if abs(dy) > eps:
                    (onc_ust[j] if dy > eps else onc_ust[i]).add(
                        i if dy > eps else j)

    # POLIGON-ICERME (varsa): cocuk (ic kesim) -> ebeveyn (dis kontur), KRITIK.
    # bbox-ic-ice kurali INCE halkalarda (alanlar cok yakin) tetiklenmeyebilir;
    # gercek poligon-icerme bunu garantiler.
    if ebeveyn is not None:
        for c, p in enumerate(ebeveyn):
            if p is not None:
                onc_sag[p].add(c)

    # KISITLARI DONGUSUZ (DAG) BIRLESTIR: once TUM kritik (onc_sag) kenarlar,
    # sonra dongu YARATMAYAN ikincil (onc_ust) kenarlar. Boylece acgozlu secim
    # asla kilitlenmez ve kalan tum kisitlar KUSURSUZ uygulanir (kritik kisit
    # asla feda edilmez; yalnizca dongu kapatan birkac ikincil kenar atlanir).
    onculler = _dongusuz_birlestir(onc_sag, onc_ust, n)

    # Her blogun GIRIS (bas / lead-in) ve CIKIS (son) noktalari; bloklar arasi
    # bosta tasima = onceki blok CIKISI -> sonraki blok GIRISI mesafesi.
    giris = [blok_bas_xy(b) for b in bloklar]
    cikis = [_blok_son_xy(b, giris[i]) for i, b in enumerate(bloklar)]

    def _uzak(a, b):
        return math.hypot(cikis[a][0] - giris[b][0], cikis[a][1] - giris[b][1])

    # TIE-BREAK: kesime hazir olanlar arasindan takima EN YAKIN olani sec
    # (nearest-neighbor). Baslangic sol-alt kose. Boylece uzun/rastgele Y
    # sicramalari kalkar; destek kisiti zaten alttan-sola -> sag-uste akisi
    # zorladigi icin yol capraz ve duzenli ilerler.
    min_x = min(b[0] for b in bboxlar)
    min_y = min(b[1] for b in bboxlar)
    konum = (min_x, min_y)

    kalan = set(range(n))
    tamam = set()
    sira = []
    while kalan:
        hazir = [i for i in kalan if onculler[i] <= tamam]
        if not hazir:                 # (DAG oldugu icin normalde olmaz) -> guvence
            hazir = list(kalan)
        sec = min(hazir, key=lambda i: (giris[i][0] - konum[0]) ** 2
                  + (giris[i][1] - konum[1]) ** 2)
        sira.append(sec)
        konum = cikis[sec]
        kalan.discard(sec)
        tamam.add(sec)

    # ---- YEREL IYILESTIRME (Or-opt): tek parcayi, DESTEK KISITINI bozmadan
    # daha iyi bir konuma tasi. NN acgozlu birakan uzun 'kurtarma' sicramalari
    # ve capraz kesismeler boylece azalir. Kisit: parca tum onculleri SONRA,
    # tum ardillari ONCE olamaz -> yalnizca uygun pencereye tasinir. Travel
    # yalnizca DUSERSE kabul edilir; ihlal uretmesi matematiksel olarak
    # imkansizdir (pencere kisiti garanti eder).
    ardil = [set() for _ in range(n)]
    for j in range(n):
        for i in onculler[j]:
            ardil[i].add(j)

    def _komsu_maliyet(dizi, k):
        v = dizi[k]
        o = dizi[k - 1] if k > 0 else None
        s = dizi[k + 1] if k + 1 < len(dizi) else None
        e = (_uzak(o, v) if o is not None else 0.0)
        e += (_uzak(v, s) if s is not None else 0.0)
        e -= (_uzak(o, s) if (o is not None and s is not None) else 0.0)
        return e

    gecti = True
    tur = 0
    while gecti and tur < 4:
        gecti = False
        tur += 1
        for k in range(len(sira)):
            v = sira[k]
            cikar = _komsu_maliyet(sira, k)          # v'yi cikarmanin kazanci
            kalanlar = sira[:k] + sira[k + 1:]
            poz = {b: p for p, b in enumerate(kalanlar)}
            lo = max((poz[u] for u in onculler[v]), default=-1) + 1
            hi = min((poz[u] for u in ardil[v]), default=len(kalanlar))
            en_iyi_delta = -1e-9
            en_iyi_p = None
            for p in range(lo, hi + 1):
                o = kalanlar[p - 1] if p > 0 else None
                s = kalanlar[p] if p < len(kalanlar) else None
                ekle = (_uzak(o, v) if o is not None else 0.0)
                ekle += (_uzak(v, s) if s is not None else 0.0)
                ekle -= (_uzak(o, s) if (o is not None and s is not None) else 0.0)
                delta = cikar - ekle                 # >0 ise iyilesme
                if delta > en_iyi_delta:
                    en_iyi_delta = delta
                    en_iyi_p = p
            if en_iyi_p is not None and en_iyi_delta > 1e-6:
                kalanlar.insert(en_iyi_p, v)
                sira = kalanlar
                gecti = True

    return [bloklar[i] for i in sira]


def destek_simulasyonu(bloklar, tol_orani=0.02):
    """ROUTER KESIM SIMULASYONU -- verilen KESIM SIRASINA gore, tabakayi
    router kesiyormus gibi adim adim ilerletip her parcanin kesildigi anda
    DESTEKSIZ kalip kalmadigini denetler.

    Fizik modeli (kullanicinin kurali): malzeme AGIRLIKLI olarak SAG ve
    UST kenardan sabitlenir. Bir parca kesilirken:
      * SAGINDA (ayni yatay bantta, Y cakismali) daha once kesilmis bir
        parca varsa -> parca SAGDAN desteksiz kalir (BIRINCIL / kritik).
      * USTUNDE (ayni dusey seritte, X cakismali, Y'de ayrik) daha once
        kesilmis parca varsa -> USTTEN desteksiz kalir (ikincil).

    Ic (nested) kesimler kendi dis konturunun icindeki dolu malzeme icinde
    olduklarindan komsu parcalarin destegini etkilemez; bu yuzden denetim
    yalnizca DIS konturlar (icerme derinligi 0) arasinda yapilir.

    Doner: ihlal sozlukleri listesi. Her biri:
      {"parca": Y_sira, "engel": X_sira, "yon": "sag"|"ust",
       "aciklama": "#X once kesilince #Y sagdan/ustten desteksiz kaliyor"}
    Bos liste => sira DOGRUDAN kesime girebilir (desteksiz parca yok).
    Sira degerleri TAM dizideki 1-tabanli konumdur (onizleme numarasiyla ayni).
    """
    n = len(bloklar)
    if n <= 1:
        return []
    der = containment_derinlik(bloklar)
    kutular = [blok_bbox(b) for b in bloklar]
    olcek = 0.0
    _tumx = [v for kk in kutular for v in (kk[0], kk[2])]
    if _tumx:
        olcek = max(_tumx) - min(_tumx)
    dejen = max(olcek * 1e-4, 1e-6)                    # sifir-alanli teknik bloklar
    # dis konturlar (icerme derinligi 0) ve GERCEK govdesi olanlar; nokta/bos
    # (or. Z-retract'siz sabit son blok) bloklar destek analizine katilmaz.
    kok = [i for i in range(n) if der[i] == 0
           and (kutular[i][2] - kutular[i][0] > dejen
                or kutular[i][3] - kutular[i][1] > dejen)]
    if len(kok) <= 1:
        return []
    bbox = [kutular[i] for i in kok]
    mz = [((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0) for b in bbox]
    tx = [v for b in bbox for v in (b[0], b[2])]
    ty = [v for b in bbox for v in (b[1], b[3])]
    olc = max(max(tx) - min(tx), max(ty) - min(ty))
    ort_tol = max(olc * 1e-3, 1e-9)                       # gercek ortusme esigi
    eps = 1e-9
    # UST (ikincil) icin 'bitisiklik' esigi: yalnizca hemen USTTE oturan
    # (kucuk bosluklu) parca gercek bir sarkma yaratir. Uzaktaki yuksek
    # parcalar SAG destek korundugu surece kritik DEGILDIR.
    y_bitisik = max((max(ty) - min(ty)) * 0.03, 1e-9)

    alan = [max((b[2] - b[0]) * (b[3] - b[1]), 0.0) for b in bbox]

    ihlaller = []
    for a in range(len(kok)):            # Y: su an kesilen dis kontur
        for b in range(a):               # X: daha once kesilmis dis kontur (engel)
            yov = min(bbox[a][3], bbox[b][3]) - max(bbox[a][1], bbox[b][1])
            xov = min(bbox[a][2], bbox[b][2]) - max(bbox[a][0], bbox[b][0])
            if yov > ort_tol and xov > ort_tol:           # BBOX'lar kesisiyor
                ov = yov * xov
                kucuk_alan = min(alan[a], alan[b])
                icte = (kucuk_alan > eps and ov / kucuk_alan > 0.80
                        and min(alan[a], alan[b]) < 0.85 * max(alan[a], alan[b]))
                if icte:                                  # (A) GERCEK ic-ice
                    if alan[b] > alan[a]:                 # BUYUK engel once kesilmis
                        ihlaller.append({
                            "parca": kok[a] + 1, "engel": kok[b] + 1,
                            "yon": "ic", "kritik": True,
                            "aciklama": f"#{kok[b] + 1} (buyuk) once kesildigi icin "
                                        f"onun koynundaki #{kok[a] + 1} desteksiz kaliyor"})
                elif mz[b][1] > mz[a][1] + eps:           # (B) kenetli, USTTEKI once
                    ihlaller.append({
                        "parca": kok[a] + 1, "engel": kok[b] + 1,
                        "yon": "ust", "kritik": False,
                        "aciklama": f"#{kok[b] + 1} ustte ve once kesildigi icin "
                                    f"#{kok[a] + 1} ust destegi zayifliyor"})
            elif yov > ort_tol:                           # (B) YATAY komsu -> SAG
                if mz[b][0] > mz[a][0] + eps:             # X, Y'nin SAGINDA, once kesilmis
                    ihlaller.append({
                        "parca": kok[a] + 1, "engel": kok[b] + 1,
                        "yon": "sag", "kritik": True,
                        "aciklama": f"#{kok[b] + 1} once kesildigi icin "
                                    f"#{kok[a] + 1} SAGDAN desteksiz kaliyor"})
            elif xov > ort_tol:                           # (C) DUSEY komsu -> UST
                bosluk = bbox[b][1] - bbox[a][3]          # X.alt - Y.ust
                if mz[b][1] > mz[a][1] + eps and -ort_tol <= bosluk <= y_bitisik:
                    ihlaller.append({
                        "parca": kok[a] + 1, "engel": kok[b] + 1,
                        "yon": "ust", "kritik": False,
                        "aciklama": f"#{kok[b] + 1} hemen ustte ve once kesildigi "
                                    f"icin #{kok[a] + 1} ust destegi zayifliyor"})
    return ihlaller


def engel_farkindalikli_sirala(bloklar):
    """Engel-farkindalikli siralama (istege bagli). Bir parcanin X araligiyla
    cakisan ve ondan daha YUKARIDA duran parcalar once islenir (uzerine
    uzanmayi onler). Esitlikte SOL-ALTTAN SAG-USTE egilimi korunur."""
    bboxlar = [blok_bbox(b) for b in bloklar]
    tum_x = [v for box in bboxlar for v in (box[0], box[2])]
    genel_x = (max(tum_x) - min(tum_x)) if tum_x else 0.0
    x_tol = genel_x * _X_CAKISMA_TOLERANSI

    n = len(bloklar)
    engelleyici = [0] * n
    for i in range(n):
        bi = bboxlar[i]
        for j in range(n):
            if i == j:
                continue
            bj = bboxlar[j]
            if _x_araliklari_cakisiyor_mu(bi, bj, x_tol) and bj[1] > bi[3] - x_tol:
                engelleyici[i] += 1

    idx = list(range(n))

    def anahtar(i):
        x, y = blok_bas_xy(bloklar[i])
        return (engelleyici[i], y, x)

    idx.sort(key=anahtar)
    return [bloklar[i] for i in idx]


def serpantin_sirala(bloklar):
    """Y bantlarina ayirip bant icinde X yonunu sirayla degistirir (zigzag).
    Bosta tasimayi azaltir; yine sol-alttan baslar."""
    sirali_y = sorted(bloklar, key=lambda b: blok_bas_xy(b)[1])
    ys = [blok_bas_xy(b)[1] for b in sirali_y]
    aralik = (max(ys) - min(ys)) if ys else 0.0
    tol = max(aralik * 0.05, 1e-9)

    bantlar, mevcut, son_y = [], [], None
    for b in sirali_y:
        y = blok_bas_xy(b)[1]
        if son_y is not None and (y - son_y) > tol and mevcut:
            bantlar.append(mevcut)
            mevcut = []
        mevcut.append(b)
        son_y = y
    if mevcut:
        bantlar.append(mevcut)

    sonuc = []
    for n, bant in enumerate(bantlar):
        bant.sort(key=lambda b: blok_bas_xy(b)[0], reverse=(n % 2 == 1))
        sonuc.extend(bant)
    return sonuc


def _strateji_uygula(bloklar, mod):
    if mod == "serpantin":
        return serpantin_sirala(bloklar)
    if mod == "engel":
        return engel_farkindalikli_sirala(bloklar)
    return sol_alt_sag_ust_sirala(bloklar)


def _direkt_ebeveyn(bloklar):
    """Her blok icin DOGRUDAN kapsayan (onu iceren EN KUCUK) blogun indeksini
    doner; kok (disaridaki) bloklar icin None. Icerme AGACI kurmak icin."""
    n = len(bloklar)
    polys = [blok_polygon(b) for b in bloklar]
    bboxes = [blok_bbox(b) for b in bloklar]
    tum = [v for box in bboxes for v in (box[0], box[2])]
    olcek = (max(tum) - min(tum)) if tum else 0.0
    tol = max(olcek * 1e-4, 1e-6)
    ebeveyn = [None] * n
    for i in range(n):
        en_kucuk, en_alan = None, None
        for j in range(n):
            if i == j:
                continue
            if _ic_ice_mi(bboxes[i], polys[i], bboxes[j], polys[j], tol):
                a = _bbox_alani(bboxes[j])
                if en_alan is None or a < en_alan:
                    en_alan, en_kucuk = a, j
        ebeveyn[i] = en_kucuk
    return ebeveyn


def sirala(bloklar, mod="sol-alt"):
    """Bloklari ICERME AGACI post-order ile siralar:
      * DIS parcalar SOL-ALTTAN SAG-USTE (secilen strateji) sirasinda,
      * her parcanin IC kesimleri kendi DIS konturundan HEMEN ONCE (yine
        sol-alt->sag-ust, en icten disa) islenir.
    Boylece kesim parca-parca ilerler ve bir parcanin ici DAIMA disindan ONCE
    kesilir -> serbest kalan/desteksiz nokta olusmaz. (Onceki davranis: TUM ic
    kesimler globalce once, sonra tum dis kesimler -> kullanici bunu istemiyordu.)"""
    n = len(bloklar)
    if n == 0:
        return []
    ebeveyn = _direkt_ebeveyn(bloklar)

    # VARSAYILAN (sol-alt): destek + ic-ice + POLIGON-ICERME kisitlarini TEK
    # kuresel eniyilemede birlikte cozer -> hem kusursuz destek hem kisa yol.
    if mod not in ("serpantin", "engel"):
        return sol_alt_sag_ust_sirala(bloklar, ebeveyn)

    cocuklar = {i: [] for i in range(n)}
    kokler = []
    for i, p in enumerate(ebeveyn):
        (cocuklar[p].append(i) if p is not None else kokler.append(i))

    def _sirali_idx(idxler):
        if not idxler:
            return []
        alt = [bloklar[i] for i in idxler]
        id2i = {id(bloklar[i]): i for i in idxler}
        return [id2i[id(b)] for b in _strateji_uygula(alt, mod)]

    sonuc = []

    def gez(i):
        for c in _sirali_idx(cocuklar[i]):     # once ic (cocuk) kesimler
            gez(c)
        sonuc.append(bloklar[i])               # sonra dis (bu parca)

    for r in _sirali_idx(kokler):
        gez(r)
    return sonuc


def _retract_ile_bitiyor(blok):
    for s in reversed(blok):
        w = satir_kelimeleri(s)
        if not w:
            continue
        return w.get("G") == 0.0 and "Z" in w and "X" not in w and "Y" not in w
    return False


# ----------------------------------------------------------------------
# Program modeli
# ----------------------------------------------------------------------

class GCodeProgram:
    """Bir G-Code dosyasini header + kesim bloklari + (sabit_son) + footer
    olarak ayristirir. `bloklar` listesinin sirasi degistirilerek yeniden
    siralama yapilir; satir icerikleri asla degismez."""

    def __init__(self, yol):
        self.yol = yol
        with open(yol, "r", encoding="utf-8", errors="replace") as f:
            self.satirlar = f.read().splitlines()
        self.guvenli = not g91_var_mi(self.satirlar)
        self.birim = birim_tespit(self.satirlar)     # "mm" | "inch" | None
        self.header = []
        self.bloklar = []
        self.footer = []
        self.sabit_son = None     # Z-retract ile bitmeyen son blok (sonda sabit)
        self.uyarilar = []
        if self.guvenli:
            self._ayristir()

    def _ayristir(self):
        satirlar = self.satirlar
        bas_idx = [i for i, s in enumerate(satirlar) if _blok_basi_mi(s)]
        if not bas_idx:
            self.uyarilar.append(
                "X-Y iceren G0 hizli hareket bulunamadi; blok tespiti yapilamadi.")
            return

        self.header = satirlar[:bas_idx[0]]
        bloklar = []
        for n, bi in enumerate(bas_idx):
            son = bas_idx[n + 1] if n + 1 < len(bas_idx) else len(satirlar)
            bloklar.append(satirlar[bi:son])

        # Program-sonu satirlarini footer'a tasi (M5/M30/% ve bos satirlar).
        footer = []
        son_blok = bloklar[-1]
        while son_blok:
            s = son_blok[-1]
            if _BITIS_RE.search(s) or not s.strip():
                footer.insert(0, son_blok.pop())
            else:
                break
        bloklar[-1] = son_blok
        self.footer = footer

        # Z-retract ile bitmeyen son blok ortaya tasinirsa kesim derinliginde
        # yatay hizli hareket olur -> bu blok en sonda sabitlenir.
        if bloklar and not _retract_ile_bitiyor(bloklar[-1]):
            self.sabit_son = bloklar.pop()
            self.uyarilar.append(
                "Son blok Z geri cekme ile bitmedigi icin konumu korundu "
                "(en sonda sabitlendi).")

        self.bloklar = bloklar

    # -- siralama ------------------------------------------------------
    def auto_sirala(self, serpantin=False, engel=False):
        """Icerme-oncelikli (en icteki once) + secilen strateji ile siralar.
        Varsayilan strateji sol-alt -> sag-ust; serpantin=zigzag, engel=golge."""
        mod = "serpantin" if serpantin else "engel" if engel else "sol-alt"
        self.bloklar = sirala(self.bloklar, mod)

    def destek_denetimi(self):
        """Mevcut kesim sirasini ROUTER gibi simule edip desteksiz kalan
        parcalari doner (bkz. destek_simulasyonu). Bos liste => dosya
        dogrudan kesime girebilir; hicbir parca desteksiz kalmaz."""
        return destek_simulasyonu(self.sirali_bloklar())

    def derinlikler(self):
        """Mevcut blok sirasindaki icerme derinlikleri."""
        return containment_derinlik(self.bloklar)

    def sirali_bloklar(self):
        return self.bloklar + ([self.sabit_son] if self.sabit_son else [])

    def bosta_yol(self):
        return toplam_bosta_yol(self.sirali_bloklar())

    def ozet(self, derinlik_hesapla=True):
        """Etkilesimli arayuz / onizleme icin blok ozetleri (poligon dahil)."""
        derinlik = containment_derinlik(self.bloklar) if derinlik_hesapla \
            else [0] * len(self.bloklar)
        out = []
        for n, blok in enumerate(self.bloklar, 1):
            bx, by = blok_bas_xy(blok)
            box = blok_bbox(blok)
            out.append({"sira": n, "x": bx, "y": by, "bbox": box,
                        "poligon": blok_yol(blok),    # yay-duyarli (onizleme)
                        "derinlik": derinlik[n - 1],
                        "satir_sayisi": len(blok)})
        return out

    def karsilastir(self):
        """Her siralama modunun toplam BOSTA (kesim disi) tasima mesafesini
        hesaplar ve en dusuk olani onerir. Mevcut sirayi bozmaz."""
        sonuc = {}
        for mod in ("sol-alt", "serpantin", "engel"):
            sirali = sirala(self.bloklar, mod)
            if self.sabit_son:
                sirali = sirali + [self.sabit_son]
            sonuc[mod] = toplam_bosta_yol(sirali)
        en_iyi = min(sonuc, key=sonuc.get) if sonuc else None
        return {"modlar": sonuc, "en_iyi": en_iyi, "birim": self.birim}

    def icerme_ihlalleri(self):
        """Mevcut sirada icerme kuralinin ihlal edildigi (bir blok, kendisini
        iceren bir bloktan SONRA kesiliyor) ciftleri doner. Elle siralamada
        uyari vermek icin."""
        polys = [blok_polygon(b) for b in self.bloklar]
        bboxes = [blok_bbox(b) for b in self.bloklar]
        tum = [v for box in bboxes for v in (box[0], box[2])]
        olcek = (max(tum) - min(tum)) if tum else 0.0
        tol = max(olcek * 1e-4, 1e-6)
        ihlaller = []
        n = len(self.bloklar)
        for i in range(n):        # ic aday
            for j in range(n):    # dis aday
                if i == j:
                    continue
                if _ic_ice_mi(bboxes[i], polys[i], bboxes[j], polys[j], tol):
                    # i, j'nin icinde; i once (kucuk sira) kesilmeli
                    if i > j:
                        ihlaller.append((i + 1, j + 1))
        return ihlaller

    # -- cikti ---------------------------------------------------------
    def yaz(self, cikti=None):
        if cikti is None:
            kok, _ = os.path.splitext(self.yol)
            cikti = f"{kok}_reordered.tap"
        with open(cikti, "w", encoding="utf-8") as f:
            for s in self.header:
                f.write(s + "\n")
            for blok in self.sirali_bloklar():
                for s in blok:
                    f.write(s + "\n")
            for s in self.footer:
                f.write(s + "\n")
        return cikti


# ----------------------------------------------------------------------
# Tek seferlik (non-interaktif) yeniden siralama
# ----------------------------------------------------------------------

def yeniden_sirala_dosya(yol, serpantin=False, engel=False):
    prog = GCodeProgram(yol)
    if not prog.guvenli:
        print("[Adim 3] GUVENLIK IPTALI: Dosyada G91 (artimli mod) tespit "
              "edildi. Dosya DEGISTIRILMEDI.")
        return None
    if not prog.bloklar and not prog.sabit_son:
        for u in prog.uyarilar:
            print(f"[Adim 3] {u}")
        print("[Adim 3] Siralanacak kesim blogu bulunamadi. Dosya degistirilmedi.")
        return None

    for u in prog.uyarilar:
        print(f"[Adim 3] GUVENLIK: {u}")

    onceki = prog.bosta_yol()
    prog.auto_sirala(serpantin=serpantin, engel=engel)
    sonraki = prog.bosta_yol()
    cikti = prog.yaz()

    mod = ("serpantin (zigzag)" if serpantin
           else "engel-farkindalikli" if engel
           else "sol-alt -> sag-ust (destek korumali)")
    sirali = prog.sirali_bloklar()
    print(f"[Adim 3] {len(sirali)} kesim blogu '{mod}' duzeninde siralandi.")
    for n, blok in enumerate(sirali, 1):
        bx, by = blok_bas_xy(blok)
        print(f"  {n}. blok -> baslangic X{bx:.2f} Y{by:.2f}")
    if onceki > 0:
        fark = (1 - sonraki / onceki) * 100
        print(f"[Adim 3] Bosta tasima mesafesi: {onceki:.1f} -> {sonraki:.1f} "
              f"({fark:+.1f}%)")

    # DESTEK DENETIMI (router simulasyonu): dosya kesime hazir mi?
    rapor = prog.destek_denetimi()
    kritik = [r for r in rapor if r["kritik"]]
    if kritik:
        print(f"[Adim 3] !! UYARI: {len(kritik)} parca desteksiz kaliyor "
              f"(dosya KESIME HAZIR DEGIL):")
        for r in kritik[:10]:
            print(f"    - {r['aciklama']}")
    else:
        print("[Adim 3] DESTEK DENETIMI: TEMIZ - hicbir parca desteksiz "
              "kalmiyor, dosya dogrudan kesime girebilir.")
        ust = [r for r in rapor if not r["kritik"]]
        if ust:
            print(f"[Adim 3] (Bilgi: {len(ust)} ikincil ust-destek uyarisi; "
                  "sag destek korundugu icin kritik degil.)")
    print(f"[Adim 3] Cikti dosyasi: {cikti}")
    return cikti
