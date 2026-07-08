#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gcode modulu ve etkilesimli editor birim testleri."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cnc_assistant import gcode
from cnc_assistant.interactive import EtkilesimliEditor


ORNEK = """\
G21
G90
G0 X90 Y90
G1 Z-1
G1 X95 Y95
G0 Z5
G0 X10 Y10
G1 Z-1
G1 X15 Y15
G0 Z5
G0 X10 Y90
G1 Z-1
G1 X15 Y95
G0 Z5
M30
"""


def _yaz(icerik):
    fd, yol = tempfile.mkstemp(suffix=".tap")
    os.close(fd)
    with open(yol, "w") as f:
        f.write(icerik)
    return yol


def test_program_ayristirma():
    yol = _yaz(ORNEK)
    try:
        prog = gcode.GCodeProgram(yol)
        assert prog.guvenli
        # 3 kesim blogu (M30 footer'a tasinir, son blok retract ile biter)
        assert len(prog.bloklar) == 3
        assert prog.header[:2] == ["G21", "G90"]
        assert any("M30" in s for s in prog.footer)
    finally:
        os.remove(yol)


def test_akilli_siralama_sol_alttan():
    yol = _yaz(ORNEK)
    try:
        prog = gcode.GCodeProgram(yol)
        prog.auto_sirala()
        # Ilk blok sol-altta olmali (X10 Y10)
        bx, by = gcode.blok_bas_xy(prog.bloklar[0])
        assert (bx, by) == (10.0, 10.0)
    finally:
        os.remove(yol)


def test_g91_guvenlik():
    yol = _yaz("G91\n" + ORNEK)
    try:
        prog = gcode.GCodeProgram(yol)
        assert prog.guvenli is False
    finally:
        os.remove(yol)


def test_etkilesimli_yer_degistir_ve_geri_al():
    yol = _yaz(ORNEK)
    try:
        ed = EtkilesimliEditor(yol)
        ed.prog.auto_sirala()        # 1:(10,10) 2:(10,90) 3:(90,90)
        ilk = [gcode.blok_bas_xy(b) for b in ed.prog.bloklar]
        # "1 3" -> 1. ve 3. yer degistir
        ed.komut_calistir("1 3")
        sonra = [gcode.blok_bas_xy(b) for b in ed.prog.bloklar]
        assert sonra[0] == ilk[2] and sonra[2] == ilk[0]
        # geri al
        ed.komut_calistir("geri")
        assert [gcode.blok_bas_xy(b) for b in ed.prog.bloklar] == ilk
        # ileri (yinele)
        ed.komut_calistir("ileri")
        assert [gcode.blok_bas_xy(b) for b in ed.prog.bloklar] == sonra
    finally:
        os.remove(yol)


def test_etkilesimli_kaydet_satirlari_korur():
    yol = _yaz(ORNEK)
    try:
        ed = EtkilesimliEditor(yol)
        ed.komut_calistir("1 2")
        cikti = ed.kaydet()
        with open(cikti) as f:
            yeni = f.read()
        # Satir KUMESI ayni kalmali (sadece sira degisir)
        assert sorted(yeni.split()) == sorted(ORNEK.split())
        os.remove(cikti)
    finally:
        os.remove(yol)


def test_tasi_komutu():
    yol = _yaz(ORNEK)
    try:
        ed = EtkilesimliEditor(yol)
        ed.prog.auto_sirala()
        ilk = [gcode.blok_bas_xy(b) for b in ed.prog.bloklar]
        ed.komut_calistir("tasi 3 1")   # 3. bloku basa al
        sonra = [gcode.blok_bas_xy(b) for b in ed.prog.bloklar]
        assert sonra[0] == ilk[2]
        assert sonra[1:] == ilk[:2]
    finally:
        os.remove(yol)


def _kare_blok(x0, y0, x1, y1):
    """Verilen kosegenle dikdortgen kesim blogu (kapali kontur)."""
    return [
        f"G0 X{x0} Y{y0}", "G1 Z-1",
        f"G1 X{x1} Y{y0}", f"G1 X{x1} Y{y1}",
        f"G1 X{x0} Y{y1}", f"G1 X{x0} Y{y0}",
        "G0 Z5",
    ]


def test_icerme_icteki_once_kesilir():
    # Dis kontur (0..100), ortada bir delik konturu (20..80), en icte kucuk
    # bir parca (45..55). Girdi sirasi bilerek TERS (once dis).
    from cnc_assistant.gcode import containment_derinlik, sirala
    dis = _kare_blok(0, 0, 100, 100)
    orta = _kare_blok(20, 20, 80, 80)
    ic = _kare_blok(45, 45, 55, 55)
    bloklar = [dis, orta, ic]                 # kotu sira: disi once
    d = containment_derinlik(bloklar)
    assert d == [0, 1, 2]                      # dis=0, orta=1, ic=2
    sirali = sirala(bloklar, "sol-alt")
    # En icteki once, en distaki sonra olmali
    from cnc_assistant.gcode import blok_bas_xy
    assert blok_bas_xy(sirali[0]) == (45.0, 45.0)   # en ic
    assert blok_bas_xy(sirali[1]) == (20.0, 20.0)   # orta
    assert blok_bas_xy(sirali[2]) == (0.0, 0.0)     # en dis


def test_icerme_coklu_ic_parca():
    # "O" gobegi: dis O konturu + gobekte 5 kucuk parca. Hepsi O'dan once.
    from cnc_assistant.gcode import containment_derinlik, sirala, blok_bbox
    dis = _kare_blok(0, 0, 200, 200)
    icler = [_kare_blok(10 + i * 30, 90, 30 + i * 30, 110) for i in range(5)]
    bloklar = [dis] + icler
    d = containment_derinlik(bloklar)
    assert d[0] == 0 and all(x == 1 for x in d[1:])
    sirali = sirala(bloklar, "sol-alt")
    # Son blok dis kontur olmali; ilk 5 ic parcalar
    assert blok_bbox(sirali[-1]) == (0.0, 0.0, 200.0, 200.0)
    for b in sirali[:-1]:
        bb = blok_bbox(b)
        assert bb != (0.0, 0.0, 200.0, 200.0)


if __name__ == "__main__":
    import traceback
    fails = 0
    for ad, fn in sorted(globals().items()):
        if ad.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {ad}")
            except Exception:
                fails += 1
                print(f"FAIL {ad}")
                traceback.print_exc()
    sys.exit(1 if fails else 0)
