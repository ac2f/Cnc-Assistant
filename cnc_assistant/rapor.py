#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hata raporu uretimi (arayuzden secilen hatali ogeleri MAKINE-OKUNUR tek bir
JSON'a dokumler).

Amac: kullanici onizlemede HATALI vektorleri (DXF baslangic noktasi) veya
HATALI kesim bloklarini (G-code sirasi) secip, her biri icin DOGRU olmasi
gereken baslangic noktasini isaretleyip (ops.) not ekleyip tek dosya olarak
disari aktarabilsin. Bu dosya, algoritmayi gelistiren tarafin (ben) dogrudan
anlayabilecegi bir sema tasir: her ogenin govdesi (kontur), mevcut ve
istenen baslangic, bbox/merkez ve not.

Sema (surum 2):

Rapor UC ASAMAYI birden tasir; algoritmayi duzeltecek taraf boylece
"ne vardi -> algoritma ne yapti -> kullanici ne istedi" zincirini bir arada
gorur:

  1. ORIJINAL  : dosyadan geldigi hali (algoritma dokunmadan once)
  2. ALGORITMA : algoritmanin urettigi sonuc
  3. FINAL     : kullanicinin elle duzenledikten sonraki hali
  + DOGRU      : kullanicinin "olmasi gereken" diye isaretledigi

  {
    "cnc_hata_raporu": 2,
    "tur": "dxf" | "gcode",
    "dosya": "<ad>",
    "birim": "mm" | "inch" | null,
    "tabaka_bbox": [x0,y0,x1,y1],
    "genel_not": "<ops>",
    "aciklama": "<semanin insan-okunur ozeti>",
    "algoritma": { ... },            # kullanilan ayarlar + istatistikler
    "siralama": { ... },             # (gcode) orijinal/algoritma/final siralar
    "duzenlemeler": [ ... ],         # kullanicinin ALGORITMA USTUNE yaptiklari
    "ogeler": [ {
        "id": "<handle veya sira>",
        "bbox": [x0,y0,x1,y1],
        "merkez": [x,y],
        "orijinal_baslangic": [x,y],     # dosyadan geldigi hali
        "algoritma_baslangic": [x,y],    # algoritmanin koydugu
        "mevcut_baslangic": [x,y],       # = final (geriye donuk uyum)
        "dogru_baslangic": [x,y] | null, # kullanicinin isaretledigi
        "yeni_node": <bool>,             # (dxf) baslangic kontur uzerinde yeni node ise
        "orijinal_sira": <int|null>,     # (gcode) dosyadaki sira
        "algoritma_sira": <int|null>,    # (gcode) algoritmanin verdigi sira
        "mevcut_sira": <int|null>,       # (gcode) final (kullanici duzenlemesi sonrasi)
        "dogru_sira":  <int|null>,       # (gcode) istenen kesim sirasi
        "kontur": [[x,y], ...],          # govde (seyreltilmis)
        "not": "<ops>"
    } ]
  }
"""

import datetime
import math


# ----------------------------------------------------------------------
# Geometri yardimcilari (SVG 'd' komut listesi -> noktalar)
# ----------------------------------------------------------------------

def _d_noktalari(d):
    """SVG komut listesinden ([['M',x,y],['L',x,y],['C',...],...]) kontur
    noktalarini (uc noktalar) cikarir."""
    pts = []
    for c in d or []:
        k = c[0]
        if k in ("M", "L") and len(c) >= 3:
            pts.append((c[1], c[2]))
        elif k == "Q" and len(c) >= 5:
            pts.append((c[3], c[4]))
        elif k == "C" and len(c) >= 7:
            pts.append((c[5], c[6]))
    return pts


def _bbox(pts):
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return [round(min(xs), 4), round(min(ys), 4),
            round(max(xs), 4), round(max(ys), 4)]


def _seyrek(pts, n=48):
    """Kontur noktalarini en fazla n'e seyreltir (govdeyi anlamak icin yeter)."""
    if len(pts) <= n:
        return [[round(x, 3), round(y, 3)] for x, y in pts]
    adim = len(pts) / float(n)
    out = []
    i = 0.0
    while i < len(pts):
        x, y = pts[int(i)]
        out.append([round(x, 3), round(y, 3)])
        i += adim
    return out


def _merkez(bbox):
    if not bbox:
        return None
    return [round((bbox[0] + bbox[2]) / 2.0, 4),
            round((bbox[1] + bbox[3]) / 2.0, 4)]


def _genel_bbox(bboxlar):
    kutu = [b for b in bboxlar if b]
    if not kutu:
        return None
    return [min(b[0] for b in kutu), min(b[1] for b in kutu),
            max(b[2] for b in kutu), max(b[3] for b in kutu)]


# ----------------------------------------------------------------------
# DXF baslangic-noktasi hata raporu
# ----------------------------------------------------------------------

_DXF_ACIKLAMA = (
    "DXF baslangic-noktasi hata raporu. Her oge bir kapali vektordur. "
    "'orijinal_baslangic' dosyadan geldigi hal; 'algoritma_baslangic' "
    "algoritmanin koydugu lead-in ('mevcut_baslangic' ile aynidir); "
    "'dogru_baslangic' kullanicinin isaretledigi olmasi gereken nokta "
    "(null ise yalnizca hatali isaretlenmis sayilir). 'kontur' govdeyi "
    "anlamak icindir. Amac: orijinal -> algoritma -> dogru zincirinden "
    "baslangic kuralini formullestirmek."
)


def _uzaklik(a, b):
    if not a or not b:
        return None
    return round(math.hypot(a[0] - b[0], a[1] - b[1]), 4)


def dxf_rapor(dosya, birim, varliklar, secimler, genel_not="",
              oncesi=None, algoritma=None):
    """varliklar: onizleme varlik listesi ({handle,d,baslangic,...}) - ALGORITMA
    sonrasi hal. oncesi: ayni bicimde ORIJINAL (algoritma oncesi) varliklar.
    algoritma: kullanilan ayarlar + istatistikler (opsiyonel).
    secimler: [{"handle":..,"dogru_baslangic":[x,y]|None,"not":str}]."""
    h2v = {v.get("handle"): v for v in varliklar}
    h2o = {v.get("handle"): v for v in (oncesi or [])}
    ogeler = []
    bboxlar = []
    duzenlemeler = []
    for sec in secimler:
        v = h2v.get(sec.get("handle"))
        if v is None:
            continue
        pts = _d_noktalari(v.get("d"))
        bb = _bbox(pts)
        bboxlar.append(bb)
        alg_bas = v.get("baslangic")
        o = h2o.get(sec.get("handle"))
        orj_bas = o.get("baslangic") if o else None
        dogru = sec.get("dogru_baslangic")
        ogeler.append({
            "id": sec.get("handle"),
            "bbox": bb,
            "merkez": _merkez(bb),
            "orijinal_baslangic": orj_bas,
            "algoritma_baslangic": alg_bas,
            "mevcut_baslangic": alg_bas,      # geriye donuk uyum
            "dogru_baslangic": dogru,
            "yeni_node": bool(sec.get("yeni_node")),
            "kayma": {
                "orijinal_algoritma": _uzaklik(orj_bas, alg_bas),
                "algoritma_dogru": _uzaklik(alg_bas, dogru),
            },
            "kontur": _seyrek(pts),
            "not": (sec.get("not") or "").strip(),
        })
        if dogru and alg_bas:
            duzenlemeler.append({
                "id": sec.get("handle"),
                "algoritma_baslangic": alg_bas,
                "dogru_baslangic": dogru,
                "uzaklik": _uzaklik(alg_bas, dogru),
                "yeni_node": bool(sec.get("yeni_node")),
            })
    return {
        "cnc_hata_raporu": 2,
        "tur": "dxf",
        "dosya": dosya,
        "birim": birim,
        "tabaka_bbox": _genel_bbox(bboxlar),
        "genel_not": (genel_not or "").strip(),
        "aciklama": _DXF_ACIKLAMA,
        "algoritma": algoritma or {},
        "duzenlemeler": duzenlemeler,
        "olusturma": datetime.datetime.now().isoformat(timespec="seconds"),
        "ogeler": ogeler,
    }


# ----------------------------------------------------------------------
# G-code kesim-sirasi hata raporu
# ----------------------------------------------------------------------

_GCODE_ACIKLAMA = (
    "G-code kesim-sirasi hata raporu. Her oge bir kesim blogudur. "
    "'orijinal_sira' dosyadan geldigi sira; 'algoritma_sira' algoritmanin "
    "onerdigi sira; 'mevcut_sira' kullanicinin elle duzenledikten sonraki "
    "FINAL sirasi; 'dogru_sira' kullanicinin istedigi sira (null ise "
    "yalnizca hatali isaretlenmis). 'baslangic' bloktaki lead-in/dalis "
    "noktasidir. 'siralama' bolumu ucunu birden tam liste olarak, "
    "'duzenlemeler' ise kullanicinin ALGORITMA USTUNE yaptigi degisiklikleri "
    "tasir. Amac: algoritma -> kullanici farkindan destek/siralama kuralini "
    "formullestirmek."
)


def _sira_haritasi(sira):
    """[blok_id, ...] -> {blok_id: 1-tabanli sira}"""
    return {bid: i + 1 for i, bid in enumerate(sira or [])}


def _yerinde_kalanlar(algoritma, final):
    """Algoritma sirasindan FINAL'e gecerken TASINMASI GEREKMEYEN bloklar.

    Bir blogu listede baska yere almak, arkasindaki tum bloklarin sira
    numarasini pasif olarak kaydirir. "Kac blok degisti" diye pozisyon
    karsilastirmak bu yuzden yaniltici olur (tek tasima 8 blok degismis
    gibi gorunur). Gercek olcu: en uzun ARTAN alt-dizi (LIS) yerinde
    kalabilir, geri kalanlar gercekten tasinmistir."""
    yer = {bid: i for i, bid in enumerate(algoritma or [])}
    diz = [yer[bid] for bid in (final or []) if bid in yer]
    if not diz:
        return set()
    # O(n^2) LIS - blok sayilari (birkac bin) icin fazlasiyla yeterli.
    n = len(diz)
    uzunluk = [1] * n
    onceki = [-1] * n
    for i in range(n):
        for j in range(i):
            if diz[j] < diz[i] and uzunluk[j] + 1 > uzunluk[i]:
                uzunluk[i] = uzunluk[j] + 1
                onceki[i] = j
    son = max(range(n), key=lambda i: uzunluk[i])
    idx = []
    while son >= 0:
        idx.append(son)
        son = onceki[son]
    ters = {i: bid for i, bid in enumerate(bid for bid in (final or [])
                                           if bid in yer)}
    return {ters[i] for i in idx}


def gcode_siralama_ozeti(orijinal, algoritma, final, mod=None, bosta=None):
    """Uc sirayi ve aralarindaki farki ozetler."""
    a = _sira_haritasi(algoritma)
    f = _sira_haritasi(final)
    degisen = [bid for bid in f if bid in a and a[bid] != f[bid]]
    kalan = _yerinde_kalanlar(algoritma, final)
    tasinan = [bid for bid in (final or []) if bid in a and bid not in kalan]
    return {
        "orijinal": list(orijinal or []),
        "algoritma": list(algoritma or []),
        "final": list(final or []),
        "algoritma_modu": mod,
        "blok_sayisi": len(final or []),
        # pozisyonu farkli olanlar (pasif kaymalar DAHIL)
        "algoritmadan_degisen": len(degisen),
        # kullanicinin GERCEKTEN tasidigi blok sayisi (asgari hamle)
        "tasinan_blok": len(tasinan),
        "tasinan_idler": tasinan,
        "bosta_yol": bosta or {},
    }


def gcode_duzenlemeler(algoritma, final, bas_degisiklik=None):
    """Kullanicinin ALGORITMA CIKTISI USTUNE yaptigi degisiklikler:
    sira tasimalari + baslangic (lead-in) tasimalari.

    'tur' alani ayrimi yapar:
      "sira"      - blok gercekten baska yere tasindi (kullanici hamlesi)
      "kayma"     - blok yerinde; onundeki bir tasima yuzunden numarasi kaydi
      "baslangic" - blogun lead-in noktasi tasindi"""
    a = _sira_haritasi(algoritma)
    f = _sira_haritasi(final)
    kalan = _yerinde_kalanlar(algoritma, final)
    out = []
    for bid, yeni in sorted(f.items(), key=lambda kv: kv[1]):
        eski = a.get(bid)
        if eski is None or eski == yeni:
            continue
        out.append({"tur": "kayma" if bid in kalan else "sira", "id": bid,
                    "algoritma_sira": eski, "final_sira": yeni,
                    "fark": yeni - eski})
    for bid, d in sorted((bas_degisiklik or {}).items()):
        out.append({"tur": "baslangic", "id": bid,
                    "once": d.get("once"), "sonra": d.get("sonra"),
                    "uzaklik": _uzaklik(d.get("once"), d.get("sonra"))})
    return out


def gcode_rapor(dosya, birim, bloklar_ozet, secimler, genel_not="",
                siralama=None, duzenlemeler=None, bas_degisiklik=None):
    """bloklar_ozet: _ozet_bloklar ciktisi ({id,x,y,bbox,komut,...}), 'id'
    0-tabanli blok indeksi. secimler: [{"id":int,"mevcut_sira":int,
    "dogru_sira":int|None,"not":str}] (mevcut_sira/dogru_sira 1-tabanli).
    siralama: gcode_siralama_ozeti ciktisi (orijinal/algoritma/final)."""
    id2b = {b["id"]: b for b in bloklar_ozet}
    orj = _sira_haritasi((siralama or {}).get("orijinal"))
    alg = _sira_haritasi((siralama or {}).get("algoritma"))
    bas_d = bas_degisiklik or {}
    ogeler = []
    bboxlar = []
    for sec in secimler:
        b = id2b.get(sec.get("id"))
        if b is None:
            continue
        bid = sec.get("id")
        bb = [round(v, 4) for v in b["bbox"]]
        bboxlar.append(bb)
        pts = _d_noktalari(b.get("komut"))
        final_bas = [round(b["x"], 4), round(b["y"], 4)]
        d = bas_d.get(bid) or {}
        ogeler.append({
            "id": sec.get("mevcut_sira", b["id"] + 1),
            "blok_id": bid,
            "bbox": bb,
            "merkez": _merkez(bb),
            "orijinal_baslangic": d.get("once") or final_bas,
            "baslangic": final_bas,
            "baslangic_tasindi": bool(d),
            "orijinal_sira": orj.get(bid),
            "algoritma_sira": alg.get(bid),
            "mevcut_sira": sec.get("mevcut_sira"),
            "dogru_sira": sec.get("dogru_sira"),
            "kontur": _seyrek(pts),
            "not": (sec.get("not") or "").strip(),
        })
    return {
        "cnc_hata_raporu": 2,
        "tur": "gcode",
        "dosya": dosya,
        "birim": birim,
        "tabaka_bbox": _genel_bbox(bboxlar),
        "genel_not": (genel_not or "").strip(),
        "aciklama": _GCODE_ACIKLAMA,
        "siralama": siralama or {},
        "duzenlemeler": duzenlemeler or [],
        "olusturma": datetime.datetime.now().isoformat(timespec="seconds"),
        "ogeler": ogeler,
    }
