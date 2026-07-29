#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Yeni G-code ozellikleri: baslangic (lead-in) tasima, aralik kaydi,
algoritmasiz yukleme.

En kritik guvence: baslangic tasima GEOMETRIYI DEGISTIRMEZ (cevre, bbox,
kapalilik korunur) ve aralik kaydinda HEADER/FOOTER asla kurcalanmaz."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cnc_assistant import gcode as GC
from cnc_assistant import webapp as W

KARE = ["G0 X20 Y20", "G1 Z-3 F300", "G1 X60 Y20 F1000", "G1 X60 Y60",
        "G1 X20 Y60", "G1 X20 Y20", "G0 Z5"]
# iki yarim daireden kapali cember (yay/bulge yolu)
CEMBER = ["G0 X10 Y0", "G1 Z-3 F300", "G3 X-10 Y0 I-10 J0 F1000",
          "G3 X10 Y0 I10 J0", "G0 Z5"]


def _olcu(blok):
    return (round(GC.blok_kesim_uzunlugu(blok), 6),
            tuple(round(v, 6) for v in GC.blok_bbox(blok)))


# ----------------------------------------------------------------------
# Baslangic (lead-in) tasima
# ----------------------------------------------------------------------

def test_baslangic_mevcut_koseye_tasinir():
    yeni, bilgi = GC.blok_baslangic_tasi(KARE, (60, 60))
    assert bilgi["degisti"] is True
    assert bilgi["yeni_node"] is False
    assert GC.blok_bas_xy(yeni) == (60.0, 60.0)
    assert _olcu(yeni) == _olcu(KARE)          # geometri birebir
    assert GC.blok_kapali_mi(yeni)


def test_baslangic_duz_kenari_boler():
    """Hedef kenar ortasinda: segment tam hedefte ikiye bolunur."""
    yeni, bilgi = GC.blok_baslangic_tasi(KARE, (40, 20))
    assert bilgi["yeni_node"] is True
    assert GC.blok_bas_xy(yeni) == (40.0, 20.0)
    assert _olcu(yeni) == _olcu(KARE)
    assert GC.blok_kapali_mi(yeni)


def test_baslangic_yayi_bolmez():
    """Yay (G2/G3) segmentleri bolunmez (I/J yeniden hesaplanmasi gerekirdi);
    en yakin mevcut kose kullanilir ve geometri aynen korunur."""
    yeni, bilgi = GC.blok_baslangic_tasi(CEMBER, (-10, 0))
    assert bilgi["degisti"] is True
    assert bilgi["yeni_node"] is False
    assert GC.blok_bas_xy(yeni) == (-10.0, 0.0)
    assert _olcu(yeni) == _olcu(CEMBER)


def test_baslangic_besleme_kaybolmaz():
    """Donduruldukten sonra ILK kesim hamlesi F tasimali; aksi halde makine
    modal olarak DALIS beslemesini (F300) kullanirdi."""
    yeni, _ = GC.blok_baslangic_tasi(KARE, (60, 60))
    _on, seg, _son = GC.blok_coz(yeni)
    assert "F" in GC.satir_kelimeleri(seg[0]["satir"])
    assert GC.satir_kelimeleri(seg[0]["satir"])["F"] == 1000.0


def test_baslangic_acik_yolu_reddeder():
    acik = ["G0 X0 Y0", "G1 Z-3 F300", "G1 X50 Y0 F1000", "G1 X50 Y50", "G0 Z5"]
    _yeni, bilgi = GC.blok_baslangic_tasi(acik, (50, 0))
    assert "hata" in bilgi


def test_baslangic_ayni_noktada_degismez():
    _yeni, bilgi = GC.blok_baslangic_tasi(KARE, (20, 20))
    assert bilgi["degisti"] is False


# ----------------------------------------------------------------------
# Aralik kaydi: header/footer korunur
# ----------------------------------------------------------------------

def _tap(yol, adet=6):
    satir = ["(POST BASLIK)", "G21", "G90", "G0 Z5"]
    for i in range(adet):
        x = 20 + i * 60
        satir += [f"G0 X{x} Y20", "G1 Z-3 F300", f"G1 X{x+40} Y20 F1000",
                  f"G1 X{x+40} Y60", f"G1 X{x} Y60", f"G1 X{x} Y20", "G0 Z5"]
    satir += ["G0 Z90", "M5", "M30"]
    with open(yol, "w") as f:
        f.write("\n".join(satir) + "\n")
    return yol


def _yukle(adet=6):
    yol = _tap(os.path.join(tempfile.mkdtemp(), "a.tap"), adet)
    W.api_gcode_yukle({"yol": yol})
    return yol


def _blok_sayisi(yol):
    prog = GC.GCodeProgram(yol)
    return len(prog.bloklar) + (1 if prog.sabit_son else 0)


def test_aralik_sadece_secili_yazilir():
    yol = _yukle(6)
    prog = GC.GCodeProgram(yol)
    r = W.api_gcode_kaydet({"yol": yol, "sira": list(range(6)),
                            "bas": 2, "son": 4, "mod": "sadece"})
    assert r["kismi"] is True and r["yazilan"] == 3
    yeni = GC.GCodeProgram(r["cikti"])
    assert len(yeni.bloklar) == 3
    # HEADER ve FOOTER aynen korunmali
    assert yeni.header == prog.header
    assert yeni.footer == prog.footer


def test_aralik_cikar_modu():
    yol = _yukle(6)
    r = W.api_gcode_kaydet({"yol": yol, "sira": list(range(6)),
                            "bas": 2, "son": 4, "mod": "cikar"})
    assert r["yazilan"] == 3
    assert _blok_sayisi(r["cikti"]) == 3


def test_aralik_verilmezse_tumu_yazilir():
    yol = _yukle(5)
    r = W.api_gcode_kaydet({"yol": yol, "sira": list(range(5))})
    assert r["kismi"] is False and r["yazilan"] == 5
    assert _blok_sayisi(r["cikti"]) == 5


def test_aralik_tasarsa_kirpilir():
    yol = _yukle(4)
    r = W.api_gcode_kaydet({"yol": yol, "sira": list(range(4)),
                            "bas": 0, "son": 99, "mod": "sadece"})
    assert r["yazilan"] == 4


def test_aralik_bos_kalirsa_hata():
    yol = _yukle(4)
    r = W.api_gcode_kaydet({"yol": yol, "sira": list(range(4)),
                            "bas": 1, "son": 4, "mod": "cikar"})
    assert "hata" in r


# ----------------------------------------------------------------------
# Algoritmasiz yukleme
# ----------------------------------------------------------------------

def test_otomatik_kapali_orijinal_sira_doner():
    yol = _tap(os.path.join(tempfile.mkdtemp(), "a.tap"), 6)
    r = W.api_gcode_yukle({"yol": yol, "otomatik": False})
    assert r["otomatik"] is False
    assert r["onerilen_sira"] == list(range(6))     # dosyadaki sira
    assert r["karsilastir"] is None                 # algoritma hic calismadi
    assert len(r["bloklar"]) == 6                   # diger her sey hazir


def test_otomatik_acik_varsayilan():
    yol = _tap(os.path.join(tempfile.mkdtemp(), "a.tap"), 6)
    r = W.api_gcode_yukle({"yol": yol})
    assert r["otomatik"] is True
    assert r["karsilastir"] is not None
    assert sorted(r["onerilen_sira"]) == list(range(6))


# ----------------------------------------------------------------------
# Baslangic tasima API ucu
# ----------------------------------------------------------------------

def test_api_baslangic_blogu_gunceller():
    yol = _tap(os.path.join(tempfile.mkdtemp(), "a.tap"), 3)
    y0 = W.api_gcode_yukle({"yol": yol})
    eski = y0["bloklar"][1]
    r = W.api_gcode_baslangic({"yol": yol, "id": 1, "nokta": [120, 60]})
    assert r["degisti"] is True
    assert r["blok"]["x"] != eski["x"] or r["blok"]["y"] != eski["y"]
    # kesim uzunlugu ve bbox korunmali
    assert abs(r["blok"]["kesim_uz"] - eski["kesim_uz"]) < 1e-6
    assert [round(v, 4) for v in r["blok"]["bbox"]] == \
           [round(v, 4) for v in eski["bbox"]]


def test_api_baslangic_gecersiz_blok():
    yol = _tap(os.path.join(tempfile.mkdtemp(), "a.tap"), 3)
    W.api_gcode_yukle({"yol": yol})
    assert "hata" in W.api_gcode_baslangic({"yol": yol, "id": 99, "nokta": [0, 0]})
    assert "hata" in W.api_gcode_baslangic({"yol": yol, "id": 0})
