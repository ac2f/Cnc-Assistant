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

Sema (surum 1):
  {
    "cnc_hata_raporu": 1,
    "tur": "dxf" | "gcode",
    "dosya": "<ad>",
    "birim": "mm" | "inch" | null,
    "tabaka_bbox": [x0,y0,x1,y1],
    "genel_not": "<ops>",
    "aciklama": "<semanin insan-okunur ozeti>",
    "ogeler": [ {
        "id": "<handle veya sira>",
        "bbox": [x0,y0,x1,y1],
        "merkez": [x,y],
        "mevcut_baslangic": [x,y],       # algoritmanin koydugu
        "dogru_baslangic": [x,y] | null, # kullanicinin isaretledigi
        "yeni_node": <bool>,             # (dxf) baslangic kontur uzerinde yeni node ise
        "mevcut_sira": <int|null>,       # (gcode) mevcut kesim sirasi
        "dogru_sira":  <int|null>,       # (gcode) istenen kesim sirasi
        "kontur": [[x,y], ...],          # govde (seyreltilmis)
        "not": "<ops>"
    } ]
  }
"""

import datetime


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
    "'mevcut_baslangic' algoritmanin koydugu lead-in; 'dogru_baslangic' "
    "kullanicinin isaretledigi olmasi gereken nokta (null ise yalnizca "
    "isaretlenmis/hatali sayilir). 'kontur' govdeyi anlamak icindir. "
    "Amac: mevcut->dogru farkindan baslangic kuralini formullestirmek."
)


def dxf_rapor(dosya, birim, varliklar, secimler, genel_not=""):
    """varliklar: onizleme varlik listesi ({handle,d,baslangic,...}).
    secimler: [{"handle":..,"dogru_baslangic":[x,y]|None,"not":str}]."""
    h2v = {v.get("handle"): v for v in varliklar}
    ogeler = []
    bboxlar = []
    for sec in secimler:
        v = h2v.get(sec.get("handle"))
        if v is None:
            continue
        pts = _d_noktalari(v.get("d"))
        bb = _bbox(pts)
        bboxlar.append(bb)
        ogeler.append({
            "id": sec.get("handle"),
            "bbox": bb,
            "merkez": _merkez(bb),
            "mevcut_baslangic": v.get("baslangic"),
            "dogru_baslangic": sec.get("dogru_baslangic"),
            "yeni_node": bool(sec.get("yeni_node")),
            "kontur": _seyrek(pts),
            "not": (sec.get("not") or "").strip(),
        })
    return {
        "cnc_hata_raporu": 1,
        "tur": "dxf",
        "dosya": dosya,
        "birim": birim,
        "tabaka_bbox": _genel_bbox(bboxlar),
        "genel_not": (genel_not or "").strip(),
        "aciklama": _DXF_ACIKLAMA,
        "olusturma": datetime.datetime.now().isoformat(timespec="seconds"),
        "ogeler": ogeler,
    }


# ----------------------------------------------------------------------
# G-code kesim-sirasi hata raporu
# ----------------------------------------------------------------------

_GCODE_ACIKLAMA = (
    "G-code kesim-sirasi hata raporu. Her oge bir kesim blogudur. "
    "'mevcut_sira' algoritmanin verdigi 1-tabanli sira; 'dogru_sira' "
    "kullanicinin istedigi sira (null ise yalnizca hatali isaretlenmis). "
    "'baslangic' bloktaki lead-in/dalis noktasidir. Amac: mevcut->dogru "
    "sira farkindan destek/siralama kuralini formullestirmek."
)


def gcode_rapor(dosya, birim, bloklar_ozet, secimler, genel_not=""):
    """bloklar_ozet: _ozet_bloklar ciktisi ({id,x,y,bbox,komut,...}), 'id'
    0-tabanli blok indeksi. secimler: [{"id":int,"mevcut_sira":int,
    "dogru_sira":int|None,"not":str}] (mevcut_sira/dogru_sira 1-tabanli)."""
    id2b = {b["id"]: b for b in bloklar_ozet}
    ogeler = []
    bboxlar = []
    for sec in secimler:
        b = id2b.get(sec.get("id"))
        if b is None:
            continue
        bb = [round(v, 4) for v in b["bbox"]]
        bboxlar.append(bb)
        pts = _d_noktalari(b.get("komut"))
        ogeler.append({
            "id": sec.get("mevcut_sira", b["id"] + 1),
            "bbox": bb,
            "merkez": _merkez(bb),
            "baslangic": [round(b["x"], 4), round(b["y"], 4)],
            "mevcut_sira": sec.get("mevcut_sira"),
            "dogru_sira": sec.get("dogru_sira"),
            "kontur": _seyrek(pts),
            "not": (sec.get("not") or "").strip(),
        })
    return {
        "cnc_hata_raporu": 1,
        "tur": "gcode",
        "dosya": dosya,
        "birim": birim,
        "tabaka_bbox": _genel_bbox(bboxlar),
        "genel_not": (genel_not or "").strip(),
        "aciklama": _GCODE_ACIKLAMA,
        "olusturma": datetime.datetime.now().isoformat(timespec="seconds"),
        "ogeler": ogeler,
    }
