#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hata bildirme uclarinin (DXF + G-code) SESSIZ KALMADIGINI dogrular.

Kullanicinin gordugu "tusa bastim, hicbir sey olmadi" durumunun sunucu
tarafindaki kaynaklari: bos/eslesmeyen secimde bos dosya uretip 'hazir'
demek, ve kodlanamayan bir yanit yuzunden istemciye hic cevap gitmemesi.
"""

import json
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
from cnc_assistant import webapp as W


def _dxf(yol):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (50, 0), (50, 50), (0, 50)],
                       dxfattribs={"closed": True})
    msp.add_lwpolyline([(80, 0), (120, 0), (120, 40), (80, 40)],
                       dxfattribs={"closed": True})
    doc.saveas(yol)
    return yol


def _tap(yol):
    satir = ["G21", "G90", "G0 Z5"]
    for i in range(3):
        x = 20 + i * 60
        satir += [f"G0 X{x} Y20", "G1 Z-3 F300", f"G1 X{x+40} Y20 F1000",
                  f"G1 X{x+40} Y60", f"G1 X{x} Y60", f"G1 X{x} Y20", "G0 Z5"]
    satir.append("M30")
    with open(yol, "w") as f:
        f.write("\n".join(satir) + "\n")
    return yol


# ----------------------------------------------------------------------
# DXF hata raporu
# ----------------------------------------------------------------------

def test_dxf_rapor_bos_secimde_hata_doner():
    yol = _dxf(os.path.join(tempfile.mkdtemp(), "a.dxf"))
    W.api_dxf_onizle({"yol": yol})
    r = W.api_dxf_rapor({"yol": yol, "secimler": []})
    assert "hata" in r and "sec" in r["hata"].lower()


def test_dxf_rapor_eslesmeyen_secimde_hata_doner():
    """Bos bir rapor yazip 'hazir' demek yerine acikca soylemeli."""
    yol = _dxf(os.path.join(tempfile.mkdtemp(), "a.dxf"))
    W.api_dxf_onizle({"yol": yol})
    r = W.api_dxf_rapor({"yol": yol,
                         "secimler": [{"handle": "YOK", "not": ""}]})
    assert "hata" in r


def test_dxf_rapor_gecerli_secimde_dosya_uretir():
    yol = _dxf(os.path.join(tempfile.mkdtemp(), "a.dxf"))
    o = W.api_dxf_onizle({"yol": yol})
    h = o["sonrasi"][0]["handle"]
    r = W.api_dxf_rapor({"yol": yol, "genel_not": "deneme",
                         "secimler": [{"handle": h, "dogru_baslangic": [1, 2],
                                       "not": "yanlis kose"}]})
    assert r.get("oge_sayisi") == 1
    assert os.path.isfile(r["cikti"])
    with open(r["cikti"], encoding="utf-8") as f:
        rp = json.load(f)
    assert rp["tur"] == "dxf"
    assert rp["ogeler"][0]["id"] == h
    assert rp["ogeler"][0]["dogru_baslangic"] == [1, 2]


def test_dxf_onizle_vektor_butunluk_doner():
    yol = _dxf(os.path.join(tempfile.mkdtemp(), "a.dxf"))
    o = W.api_dxf_onizle({"yol": yol})
    assert o["butunluk"]["ok"] is True
    assert o["sapan_handlelar"] == []
    assert o["butunluk"]["kontrol"] >= 1


# ----------------------------------------------------------------------
# G-code hata raporu
# ----------------------------------------------------------------------

def test_gcode_rapor_bos_secimde_hata_doner():
    yol = _tap(os.path.join(tempfile.mkdtemp(), "a.tap"))
    W.api_gcode_yukle({"yol": yol})
    r = W.api_gcode_rapor({"yol": yol, "secimler": []})
    assert "hata" in r and "sec" in r["hata"].lower()


def test_gcode_rapor_gecerli_secimde_dosya_uretir():
    yol = _tap(os.path.join(tempfile.mkdtemp(), "a.tap"))
    W.api_gcode_yukle({"yol": yol})
    r = W.api_gcode_rapor({"yol": yol, "secimler": [
        {"id": 0, "mevcut_sira": 1, "dogru_sira": 3, "not": "once ic kesilmeli"},
        {"id": 2, "mevcut_sira": 3, "dogru_sira": 1, "not": ""}]})
    assert r["oge_sayisi"] == 2
    with open(r["cikti"], encoding="utf-8") as f:
        rp = json.load(f)
    assert rp["tur"] == "gcode"
    assert [o["dogru_sira"] for o in rp["ogeler"]] == [3, 1]


def test_gcode_rapor_eslesmeyen_secimde_hata_doner():
    yol = _tap(os.path.join(tempfile.mkdtemp(), "a.tap"))
    W.api_gcode_yukle({"yol": yol})
    r = W.api_gcode_rapor({"yol": yol, "secimler": [{"id": 999}]})
    assert "hata" in r


# ----------------------------------------------------------------------
# Yanit kodlama: her zaman GECERLI JSON gitmeli
# ----------------------------------------------------------------------

def test_json_govde_set_ve_sonsuz_degerleri_kaldirir():
    """Kodlanamayan bir deger yuzunden istisna atilirsa istemci HIC yanit
    almaz ve buton sessizce olur; bu yuzden her sey kodlanabilmeli."""
    govde = W._json_govde({"kume": {"a", "b"}, "inf": math.inf,
                           "nan": math.nan, "ic": [{"x": math.inf}]})
    geri = json.loads(govde)                  # gecerli JSON olmali
    assert sorted(geri["kume"]) == ["a", "b"]
    assert geri["inf"] is None and geri["nan"] is None
    assert geri["ic"][0]["x"] is None
