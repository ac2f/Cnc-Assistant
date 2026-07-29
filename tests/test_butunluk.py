#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vektor-bazli butunluk denetimi + optimizasyonun koordinat korumasi.

Buradaki testler iki seyi garanti eder:
  1. Optimizasyon HICBIR koordinati degistirmez (Z/elevation ve genislik
     dahil) -- yalnizca vertex sirasini/sayisini degistirir.
  2. Bir koordinat yine de degisirse butunluk denetimi bunu YAKALAR
     (dokuman geneli toplam cevre/bbox kontrolu tek basina kacirabilir).
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
from cnc_assistant import dxf_processor as D

OPTS = {"node_temizle": True, "node_tol": 1e-6, "destek_yonu": (1.0, 1.0)}


def _kare(x, y, kenar, ara=3):
    """Her kenarinda fazladan es-dogrultulu node'lar olan kapali kare."""
    pts = []
    kose = [(x, y), (x + kenar, y), (x + kenar, y + kenar), (x, y + kenar)]
    for i in range(4):
        a, b = kose[i], kose[(i + 1) % 4]
        pts.append((a[0], a[1], 0, 0, 0))
        for k in range(1, ara + 1):
            t = k / (ara + 1)
            pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, 0, 0, 0))
    return pts


def _yaz(doc):
    yol = os.path.join(tempfile.mkdtemp(), "t.dxf")
    doc.saveas(yol)
    return yol


def _ornek_doc():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_lwpolyline(_kare(10, 10, 40), format="xyseb", dxfattribs={"closed": True})
    msp.add_lwpolyline(_kare(80, 10, 30), format="xyseb", dxfattribs={"closed": True})
    msp.add_circle((150, 40), radius=15)
    return doc


# ----------------------------------------------------------------------
# 1) Optimizasyon koordinatlari korur
# ----------------------------------------------------------------------

def test_polyline2d_z_yuksekligi_korunur():
    """Klasik 2D POLYLINE optimize edilirken vertex Z'si (elevation) DUSMEZ.

    Regresyon: eskiden vertex konumu (x, y, 0.0) olarak yazildigindan z=12
    duzlemindeki parcalar sessizce z=0'a iniyordu; dokuman geneli kontrol
    (bbox+cevre yalnizca XY) bunu goremiyordu."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_polyline2d([(0, 0, 12), (25, 0, 12), (50, 0, 12),
                        (50, 50, 12), (0, 50, 12)],
                       dxfattribs={"closed": True})
    s = D.optimize_doc(_yaz(doc), OPTS)
    pl = [e for e in s["doc"].modelspace() if e.dxftype() == "POLYLINE"][0]
    assert [v.dxf.location.z for v in pl.vertices] == [12.0] * len(pl.vertices)
    assert s["dogrulama"] is True


def test_polyline2d_node_temizligi_coksuz_calisir():
    """Regresyon: ezdxf 1.x'te Polyline.delete_vertices yok; eskiden
    AttributeError atiyordu ve 2D POLYLINE'li her dosya patliyordu."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_polyline2d([(0, 0), (25, 0), (50, 0), (50, 50), (25, 50), (0, 50)],
                       dxfattribs={"closed": True})
    s = D.optimize_doc(_yaz(doc), OPTS)
    assert s["silinen_node"] > 0
    assert s["dogrulama"] is True


def test_lwpolyline_genislik_taperi_korunur():
    """Lead-in node'u genislik tasiyan bir segmenti bolerse, bolme
    noktasindaki genislik INTERPOLE edilir (0'a dusurulmez)."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0, 2.0, 4.0, 0.0), (60, 0, 2.0, 4.0, 0.0),
                        (60, 60, 2.0, 4.0, 0.0), (0, 60, 2.0, 4.0, 0.0)],
                       format="xyseb", dxfattribs={"closed": True})
    s = D.optimize_doc(_yaz(doc), OPTS)
    pl = [e for e in s["doc"].modelspace() if e.dxftype() == "LWPOLYLINE"][0]
    for p in pl.get_points("xyseb"):
        assert 2.0 - 1e-9 <= p[2] <= 4.0 + 1e-9      # start_width araligi icinde
        assert 2.0 - 1e-9 <= p[3] <= 4.0 + 1e-9      # end_width araligi icinde


def test_optimize_her_vektoru_birebir_korur():
    s = D.optimize_doc(_yaz(_ornek_doc()), OPTS)
    vb = s["vektor_butunluk"]
    assert vb["ok"] is True
    assert vb["sapan"] == []
    assert vb["kontrol"] >= 3          # her dokunulan vektor denetlendi


# ----------------------------------------------------------------------
# 2) Denetim gercek bir sapmayi yakalar
# ----------------------------------------------------------------------

def _harita(doc):
    return D._kontur_haritasi(doc)


def test_kayan_koordinat_yakalanir():
    yol = _yaz(_ornek_doc())
    once = _harita(ezdxf.readfile(yol))
    doc = ezdxf.readfile(yol)
    hedef = [e for e in doc.modelspace() if e.dxftype() == "LWPOLYLINE"][0]
    p = list(hedef.get_points("xyseb"))
    p[1] = (p[1][0], p[1][1] + 0.9, p[1][2], p[1][3], p[1][4])   # konturdan disari
    hedef.set_points(p, format="xyseb")

    r = D.varlik_butunluk(once, _harita(doc), dokunulan={hedef.dxf.handle})
    assert r["ok"] is False
    assert r["sapan"][0]["handle"] == hedef.dxf.handle
    assert r["sapan"][0]["sapma"] > 0.5


def test_kucuk_kayma_da_yakalanir():
    """Toplam cevreyi neredeyse hic degistirmeyen 0.05 birimlik kayma bile
    yakalanmali (dokuman geneli kontrol bunu goremez)."""
    yol = _yaz(_ornek_doc())
    once = _harita(ezdxf.readfile(yol))
    doc = ezdxf.readfile(yol)
    hedef = [e for e in doc.modelspace() if e.dxftype() == "LWPOLYLINE"][0]
    p = list(hedef.get_points("xyseb"))
    p[1] = (p[1][0], p[1][1] + 0.05, p[1][2], p[1][3], p[1][4])
    hedef.set_points(p, format="xyseb")

    r = D.varlik_butunluk(once, _harita(doc), dokunulan={hedef.dxf.handle})
    assert r["ok"] is False


def test_kaybolan_vektor_yakalanir():
    yol = _yaz(_ornek_doc())
    once = _harita(ezdxf.readfile(yol))
    doc = ezdxf.readfile(yol)
    msp = doc.modelspace()
    kayip = [e for e in msp if e.dxftype() == "LWPOLYLINE"][0]
    h = kayip.dxf.handle
    msp.delete_entity(kayip)

    r = D.varlik_butunluk(once, _harita(doc), dokunulan=set())
    assert r["ok"] is False
    assert any(s["handle"] == h and "kayboldu" in s["neden"] for s in r["sapan"])


def test_baslangic_dondurme_sapma_sayilmaz():
    """Baslangic noktasini dondurmek geometriyi DEGISTIRMEZ; denetim bunu
    yanlis alarm olarak bildirmemeli (isin tamami buna dayaniyor)."""
    yol = _yaz(_ornek_doc())
    once = _harita(ezdxf.readfile(yol))
    doc = ezdxf.readfile(yol)
    hedef = [e for e in doc.modelspace() if e.dxftype() == "LWPOLYLINE"][0]
    p = list(hedef.get_points("xyseb"))
    hedef.set_points(p[5:] + p[:5], format="xyseb")

    r = D.varlik_butunluk(once, _harita(doc), dokunulan={hedef.dxf.handle})
    assert r["ok"] is True


def test_node_silme_sapma_sayilmaz():
    """Es-dogrultulu (gereksiz) node silmek de sekli degistirmez."""
    yol = _yaz(_ornek_doc())
    once = _harita(ezdxf.readfile(yol))
    doc = ezdxf.readfile(yol)
    hedef = [e for e in doc.modelspace() if e.dxftype() == "LWPOLYLINE"][0]
    p = list(hedef.get_points("xyseb"))
    del p[1]                                  # kenar ortasindaki ara node
    hedef.set_points(p, format="xyseb")

    r = D.varlik_butunluk(once, _harita(doc), dokunulan={hedef.dxf.handle})
    assert r["ok"] is True


def test_butunluk_sonuclari_json_uyumlu():
    """Sapma degeri her zaman SONLU olmali; Infinity/NaN tarayicida
    JSON.parse'i patlatir ve arayuz sessizce olur."""
    yol = _yaz(_ornek_doc())
    once = _harita(ezdxf.readfile(yol))
    doc = ezdxf.readfile(yol)
    hedef = [e for e in doc.modelspace() if e.dxftype() == "LWPOLYLINE"][0]
    p = list(hedef.get_points("xyseb"))
    p[1] = (p[1][0], p[1][1] + 25.0, p[1][2], p[1][3], p[1][4])   # cok buyuk kayma
    hedef.set_points(p, format="xyseb")

    import json
    import math
    r = D.varlik_butunluk(once, _harita(doc), dokunulan={hedef.dxf.handle})
    assert math.isfinite(r["sapan"][0]["sapma"])
    json.dumps(r, allow_nan=False)            # atmadan kodlanabilmeli
