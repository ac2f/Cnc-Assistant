#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Yeni ozellikler icin testler: yay onizleme, birim, tab, karsilastirma, nesting."""

import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
from cnc_assistant import gcode as GC, geometry as G, nesting


def test_yay_flatten_yaricap_korur():
    blok = ["G0 X10 Y0", "G1 Z-1", "G3 X0 Y10 I-10 J0", "G0 Z5"]
    yol = GC.blok_yol(blok)
    assert len(yol) > 5
    assert all(abs(math.hypot(x, y) - 10) < 0.25 for x, y in yol)
    assert abs(yol[-1][0]) < 0.1 and abs(yol[-1][1] - 10) < 0.1


def test_birim_tespit():
    assert GC.birim_tespit(["G21", "G0 X0"]) == "mm"
    assert GC.birim_tespit(["G20"]) == "inch"
    assert GC.birim_tespit(["G0 X0 Y0"]) is None


def test_tab_pozisyonlari_esit_aralik():
    kare = [(0, 0), (100, 0), (100, 100), (0, 100)]
    tabs = G.tab_pozisyonlari(kare, adet=4)
    assert len(tabs) == 4
    # her nokta kenar uzerinde (x veya y sinirda)
    for x, y, _ in tabs:
        assert (abs(x) < 1e-6 or abs(x - 100) < 1e-6 or
                abs(y) < 1e-6 or abs(y - 100) < 1e-6)


def test_karsilastir_en_iyi_secer():
    g = ("G21\nG90\n"
         "G0 X90 Y90\nG1 X95 Y95\nG0 Z5\n"
         "G0 X10 Y10\nG1 X15 Y15\nG0 Z5\n"
         "G0 X10 Y90\nG1 X15 Y95\nG0 Z5\nM30\n")
    fd, p = tempfile.mkstemp(suffix=".tap"); os.close(fd)
    open(p, "w").write(g)
    try:
        prog = GC.GCodeProgram(p)
        k = prog.karsilastir()
        assert set(k["modlar"]) == {"sol-alt", "serpantin", "engel"}
        assert k["en_iyi"] in k["modlar"]
        assert k["birim"] == "mm"
        # en_iyi gercekten en dusuk olmali
        assert k["modlar"][k["en_iyi"]] == min(k["modlar"].values())
    finally:
        os.remove(p)


def test_nesting_cakismasiz_ve_cevre_korur():
    doc = ezdxf.new("R2010"); msp = doc.modelspace()
    for (x, y, s) in [(0, 0, 40), (200, 10, 30), (90, 150, 50)]:
        msp.add_lwpolyline([(x, y), (x + s, y), (x + s, y + s), (x, y + s)], close=True)
    # ic ice (tek parca)
    msp.add_lwpolyline([(300, 300), (360, 300), (360, 360), (300, 360)], close=True)
    msp.add_lwpolyline([(320, 320), (340, 320), (340, 340), (320, 340)], close=True)
    r = nesting.nest_doc(doc, tabaka_genislik=200, bosluk=5, kenar=5)
    assert r["parca_sayisi"] == 4           # O ic+dis tek parca
    assert r["cevre_korundu"] is True
    yer = [y["yeni"] for y in r["yerlesim"]]

    def cakisir(a, b):
        return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
    cak = sum(1 for i in range(len(yer)) for j in range(i + 1, len(yer))
              if cakisir(yer[i], yer[j]))
    assert cak == 0


if __name__ == "__main__":
    import traceback
    fails = 0
    for ad, fn in sorted(globals().items()):
        if ad.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS {ad}")
            except Exception:
                fails += 1; print(f"FAIL {ad}"); traceback.print_exc()
    sys.exit(1 if fails else 0)
