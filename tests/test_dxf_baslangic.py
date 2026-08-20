#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Elle baslangic (lead-in) tasima: geometri korunur, kayda/rapora yansir."""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
from cnc_assistant import dxf_processor as D
from cnc_assistant import webapp as W


def _dxf(yay=False, insunits=4):
    yol = os.path.join(tempfile.mkdtemp(), "b.dxf")
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)],
                       dxfattribs={"closed": True})
    if yay:
        msp.add_lwpolyline([(200, 0, 0, 0, 0.5), (300, 0, 0, 0, 0),
                            (300, 100, 0, 0, 0), (200, 100, 0, 0, 0)],
                           format="xyseb", dxfattribs={"closed": True})
    if insunits is not None:
        doc.header["$INSUNITS"] = insunits
    doc.saveas(yol)
    return yol


def _olcu(yol, handle):
    for e in W._DXF_DOC[yol].modelspace():
        if e.dxf.handle == handle:
            p = D._ezpath.make_path(e)
            return D._kontur_olculeri([(v.x, v.y) for v in p.flattening(0.005)])
    return None


# ----------------------------------------------------------------------
# Birim adi (raporda ham $INSUNITS kodu cikiyordu)
# ----------------------------------------------------------------------

def test_birim_kodu_ada_cevrilir():
    assert D.birim_adi(4) == "mm"
    assert D.birim_adi(1) == "inch"
    assert D.birim_adi(0) is None
    assert D.birim_adi(None) is None
    assert D.birim_adi("bozuk") is None


def test_raporda_birim_ham_kod_degil():
    yol = _dxf()
    h = W.api_dxf_onizle({"yol": yol})["sonrasi"][0]["handle"]
    r = W.api_dxf_rapor({"yol": yol, "secimler": [{"handle": h}]})
    with open(r["cikti"], encoding="utf-8") as f:
        assert json.load(f)["birim"] == "mm"


# ----------------------------------------------------------------------
# Baslangic tasima geometriyi korur
# ----------------------------------------------------------------------

def test_baslangic_tasima_geometriyi_korur():
    yol = _dxf()
    h = W.api_dxf_onizle({"yol": yol})["sonrasi"][0]["handle"]
    once = _olcu(yol, h)
    r = W.api_dxf_baslangic({"yol": yol, "handle": h, "nokta": [50, 100]})
    assert r["degisti"] is True and r["yeni_node"] is True
    sonra = _olcu(yol, h)
    assert round(once[1], 6) == round(sonra[1], 6)          # cevre
    assert round(once[2], 4) == round(sonra[2], 4)          # alan
    assert [round(v, 6) for v in once[0]] == [round(v, 6) for v in sonra[0]]


def test_baslangic_tasima_yayi_bolmez():
    yol = _dxf(yay=True)
    h = W.api_dxf_onizle({"yol": yol})["sonrasi"][1]["handle"]
    once = _olcu(yol, h)
    r = W.api_dxf_baslangic({"yol": yol, "handle": h, "nokta": [250, -25]})
    assert r["yeni_node"] is False                          # yay bolunmedi
    assert round(_olcu(yol, h)[1], 6) == round(once[1], 6)  # cevre birebir


def test_baslangic_gecersiz_girdi():
    yol = _dxf()
    W.api_dxf_onizle({"yol": yol})
    assert "hata" in W.api_dxf_baslangic({"yol": yol, "handle": "YOK",
                                          "nokta": [0, 0]})
    assert "hata" in W.api_dxf_baslangic({"yol": yol, "handle": "1F"})


# ----------------------------------------------------------------------
# Duzeltmeler kayda ve rapora yansir
# ----------------------------------------------------------------------

def test_kaydet_duzeltmeleri_uygular():
    yol = _dxf()
    h = W.api_dxf_onizle({"yol": yol})["sonrasi"][0]["handle"]
    W.api_dxf_baslangic({"yol": yol, "handle": h, "nokta": [100, 50]})
    k = W.api_dxf_kaydet({"yol": yol})
    assert k["duzeltme_sayisi"] == 1
    doc = ezdxf.readfile(k["cikti"])
    for e in doc.modelspace():
        if e.dxf.handle == h:
            p = e.get_points("xy")[0]
            assert (round(p[0], 3), round(p[1], 3)) == (100.0, 50.0)
            break
    else:
        raise AssertionError("vektor kaydedilen dosyada yok")


def test_rapor_duzeltilmis_dxf_de_uretir():
    yol = _dxf()
    h = W.api_dxf_onizle({"yol": yol})["sonrasi"][0]["handle"]
    r = W.api_dxf_rapor({"yol": yol, "secimler": [
        {"handle": h, "dogru_baslangic": [100, 50], "not": "sag kenar"}]})
    assert r["uygulanan"] == 1
    assert os.path.isfile(r["dxf_cikti"])
    doc = ezdxf.readfile(r["dxf_cikti"])
    for e in doc.modelspace():
        if e.dxf.handle == h:
            p = e.get_points("xy")[0]
            assert (round(p[0], 3), round(p[1], 3)) == (100.0, 50.0)
            break
    else:
        raise AssertionError("duzeltilmis DXF'te vektor yok")


def test_rapor_algoritma_ciktisini_elle_duzenleme_bozmaz():
    """Elle duzenleme yapildiktan SONRA rapor alinsa bile
    'algoritma_baslangic' algoritmanin GERCEK ciktisi olmali; aksi halde
    rapor kendi kendini gecersiz kilar."""
    yol = _dxf()
    o = W.api_dxf_onizle({"yol": yol})
    h = o["sonrasi"][0]["handle"]
    alg = o["sonrasi"][0]["baslangic"]

    W.api_dxf_baslangic({"yol": yol, "handle": h, "nokta": [50, 100]})
    r = W.api_dxf_rapor({"yol": yol, "secimler": [
        {"handle": h, "dogru_baslangic": [100, 50]}]})
    with open(r["cikti"], encoding="utf-8") as f:
        it = json.load(f)["ogeler"][0]
    assert it["algoritma_baslangic"] == alg
    assert it["dogru_baslangic"] == [100, 50]


def test_yeniden_isleme_duzeltmeleri_sifirlar():
    yol = _dxf()
    h = W.api_dxf_onizle({"yol": yol})["sonrasi"][0]["handle"]
    W.api_dxf_baslangic({"yol": yol, "handle": h, "nokta": [100, 50]})
    assert len(W._DXF_DUZELTME.get(yol) or {}) == 1
    W.api_dxf_onizle({"yol": yol})               # yeniden isle
    assert not W._DXF_DUZELTME.get(yol)
