#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hata raporu UC ASAMAYI tasiyor mu?

  1. ORIJINAL  : dosyadan geldigi hal
  2. ALGORITMA : algoritmanin urettigi sonuc
  3. FINAL     : kullanicinin elle duzenledikten sonraki hal
  + DOGRU      : kullanicinin "olmasi gereken" isareti
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
from cnc_assistant import rapor as R
from cnc_assistant import webapp as W


def _tap(yol, adet=6):
    satir = ["(POST BASLIK)", "G21", "G90", "G0 Z5"]
    for i in range(adet):
        x, y = 20 + (i % 3) * 60, 20 + (i // 3) * 60
        satir += [f"G0 X{x} Y{y}", "G1 Z-3 F300", f"G1 X{x+40} Y{y} F1000",
                  f"G1 X{x+40} Y{y+40}", f"G1 X{x} Y{y+40}", f"G1 X{x} Y{y}",
                  "G0 Z5"]
    satir += ["G0 Z90", "M5", "M30"]
    with open(yol, "w") as f:
        f.write("\n".join(satir) + "\n")
    return yol


def _oku(cikti):
    with open(cikti, encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------------
# Tasima / pasif kayma ayrimi
# ----------------------------------------------------------------------

def test_tek_tasima_tek_sayilir():
    """Bir blogu basa almak arkasindaki herkesin numarasini kaydirir; rapor
    bunu '8 blok degisti' diye bildirmemeli - GERCEKTEN tasinan 1 tanedir."""
    alg = [0, 1, 2, 3, 4, 5, 6, 7]
    final = [6, 0, 1, 2, 3, 4, 5, 7]
    o = R.gcode_siralama_ozeti(list(range(8)), alg, final)
    assert o["tasinan_blok"] == 1
    assert o["tasinan_idler"] == [6]
    assert o["algoritmadan_degisen"] > 1        # pasif kaymalar dahil


def test_duzenleme_turleri_ayrilir():
    alg = [0, 1, 2, 3, 4]
    final = [3, 0, 1, 2, 4]
    d = R.gcode_duzenlemeler(alg, final)
    turler = [x["tur"] for x in d]
    assert turler.count("sira") == 1            # gercek tasima
    assert turler.count("kayma") == 3           # pasif kaymalar
    assert next(x for x in d if x["tur"] == "sira")["id"] == 3


def test_degisiklik_yoksa_duzenleme_bos():
    alg = [0, 1, 2, 3]
    assert R.gcode_duzenlemeler(alg, alg) == []
    assert R.gcode_siralama_ozeti(alg, alg, alg)["tasinan_blok"] == 0


def test_baslangic_tasimalari_duzenlemede():
    d = R.gcode_duzenlemeler([0, 1], [0, 1],
                             bas_degisiklik={1: {"once": [0, 0], "sonra": [3, 4]}})
    assert len(d) == 1
    assert d[0]["tur"] == "baslangic" and d[0]["uzaklik"] == 5.0


# ----------------------------------------------------------------------
# G-code raporu: uc asama + bosta yol karsilastirmasi
# ----------------------------------------------------------------------

def test_gcode_raporu_uc_asamayi_tasir():
    yol = _tap(os.path.join(tempfile.mkdtemp(), "a.tap"), 6)
    y = W.api_gcode_yukle({"yol": yol})
    alg = y["onerilen_sira"]

    final = alg[:]                              # kullanici tek blok tasir
    b = final.pop(4)
    final.insert(0, b)
    W.api_gcode_baslangic({"yol": yol, "id": final[1], "nokta": [60, 40]})

    r = W.api_gcode_rapor({"yol": yol, "final_sira": final,
                           "adimlar": ["auto", "taşı"],
                           "secimler": [{"id": final[0], "mevcut_sira": 1,
                                         "dogru_sira": 3, "not": "once ic"}]})
    rp = _oku(r["cikti"])

    assert rp["cnc_hata_raporu"] == 2
    s = rp["siralama"]
    assert s["orijinal"] == list(range(6))       # dosyadaki sira
    assert s["algoritma"] == alg                 # algoritmanin sonucu
    assert s["final"] == final                   # kullanicinin son hali
    assert s["algoritma_modu"] == "sol-alt"
    assert s["tasinan_blok"] == 1
    assert set(s["bosta_yol"]) == {"orijinal", "algoritma", "final"}
    assert s["duzenleme_adimlari"] == ["auto", "taşı"]
    assert any(d["tur"] == "baslangic" for d in rp["duzenlemeler"])


def test_gcode_ogesi_her_asamayi_tasir():
    yol = _tap(os.path.join(tempfile.mkdtemp(), "a.tap"), 6)
    y = W.api_gcode_yukle({"yol": yol})
    alg = y["onerilen_sira"]
    final = alg[:]
    final.insert(0, final.pop(3))
    hedef = final[0]
    r = W.api_gcode_rapor({"yol": yol, "final_sira": final,
                           "secimler": [{"id": hedef, "mevcut_sira": 1,
                                         "dogru_sira": 5}]})
    o = _oku(r["cikti"])["ogeler"][0]
    assert o["blok_id"] == hedef
    assert o["orijinal_sira"] == hedef + 1        # dosyadaki 1-tabanli sira
    assert o["algoritma_sira"] == alg.index(hedef) + 1
    assert o["mevcut_sira"] == 1                  # final
    assert o["dogru_sira"] == 5


def test_gcode_baslangic_tasima_ogede_gorunur():
    yol = _tap(os.path.join(tempfile.mkdtemp(), "a.tap"), 3)
    W.api_gcode_yukle({"yol": yol})
    once = W.api_gcode_yukle({"yol": yol})["bloklar"][1]
    W.api_gcode_baslangic({"yol": yol, "id": 1, "nokta": [120, 60]})
    r = W.api_gcode_rapor({"yol": yol, "final_sira": [0, 1, 2],
                           "secimler": [{"id": 1, "mevcut_sira": 2}]})
    o = _oku(r["cikti"])["ogeler"][0]
    assert o["baslangic_tasindi"] is True
    assert o["orijinal_baslangic"] == [once["x"], once["y"]]
    assert o["baslangic"] != o["orijinal_baslangic"]


# ----------------------------------------------------------------------
# DXF raporu: orijinal -> algoritma -> dogru zinciri
# ----------------------------------------------------------------------

def _dxf(yol):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (50, 0), (50, 50), (0, 50)],
                       dxfattribs={"closed": True})
    doc.saveas(yol)
    return yol


def test_dxf_raporu_orijinal_ve_algoritma_baslangicini_tasir():
    yol = _dxf(os.path.join(tempfile.mkdtemp(), "a.dxf"))
    o = W.api_dxf_onizle({"yol": yol})
    h = o["sonrasi"][0]["handle"]
    orj = o["oncesi"][0]["baslangic"]
    alg = o["sonrasi"][0]["baslangic"]

    r = W.api_dxf_rapor({"yol": yol, "secimler": [
        {"handle": h, "dogru_baslangic": [10.0, 50.0], "not": "sol-ust"}]})
    rp = _oku(r["cikti"])
    assert rp["cnc_hata_raporu"] == 2

    it = rp["ogeler"][0]
    assert it["orijinal_baslangic"] == orj        # dosyadan geldigi hal
    assert it["algoritma_baslangic"] == alg       # algoritmanin koydugu
    assert it["mevcut_baslangic"] == alg          # geriye donuk uyum
    assert it["dogru_baslangic"] == [10.0, 50.0]  # kullanicinin isareti
    assert it["kayma"]["orijinal_algoritma"] is not None
    assert it["kayma"]["algoritma_dogru"] is not None

    assert len(rp["duzenlemeler"]) == 1
    assert rp["duzenlemeler"][0]["dogru_baslangic"] == [10.0, 50.0]


def test_dxf_raporu_algoritma_ayarlarini_tasir():
    yol = _dxf(os.path.join(tempfile.mkdtemp(), "a.dxf"))
    W.api_dxf_onizle({"yol": yol, "destek_yonu": "sol-ust", "node_tol": 1e-5})
    h = W.api_dxf_onizle({"yol": yol, "destek_yonu": "sol-ust",
                          "node_tol": 1e-5})["sonrasi"][0]["handle"]
    r = W.api_dxf_rapor({"yol": yol, "secimler": [{"handle": h}]})
    a = _oku(r["cikti"])["algoritma"]
    assert a["destek_yonu"] == "sol-ust"
    assert a["node_tol"] == 1e-5
    assert a["butunluk_ok"] is True
    assert "kaydirilan" in a and "silinen_node" in a


def test_dxf_dogru_isaretlenmemisse_duzenleme_yok():
    yol = _dxf(os.path.join(tempfile.mkdtemp(), "a.dxf"))
    h = W.api_dxf_onizle({"yol": yol})["sonrasi"][0]["handle"]
    r = W.api_dxf_rapor({"yol": yol, "secimler": [{"handle": h, "not": "bozuk"}]})
    rp = _oku(r["cikti"])
    assert rp["duzenlemeler"] == []
    assert rp["ogeler"][0]["dogru_baslangic"] is None
