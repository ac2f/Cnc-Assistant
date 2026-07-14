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


def test_destek_sirasi_sag_ust_korunur():
    """CNC-ustasi kurali: malzeme SAG + UST'ten sabit. Siralamada bir parca
    kesilirken SAGINDA (Y cakismali) veya USTUNDE (X cakismali) daha once
    kesilmis parca OLMAMALI. 3x3 kare izgara ile ihlal=0 dogrulanir."""
    from cnc_assistant.gcode import sol_alt_sag_ust_sirala, blok_bbox
    bloklar = []
    for r in range(3):            # satir (Y)
        for c in range(3):        # sutun (X)
            x0, y0 = c * 100, r * 100
            bloklar.append(_kare_blok(x0, y0, x0 + 60, y0 + 60))
    sirali = sol_alt_sag_ust_sirala(list(bloklar))
    bx = [blok_bbox(b) for b in sirali]
    mz = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in bx]
    for i in range(len(sirali)):          # i su an kesiliyor
        for k in range(i):                # k daha once kesildi
            yc = min(bx[i][3], bx[k][3]) > max(bx[i][1], bx[k][1])
            xc = min(bx[i][2], bx[k][2]) > max(bx[i][0], bx[k][0])
            # k, i'nin saginda ve once kesilmis -> ihlal
            assert not (yc and mz[k][0] > mz[i][0]), f"sag destek ihlali {k}->{i}"
            # k, i'nin ustunde ve once kesilmis -> ihlal
            assert not (xc and mz[k][1] > mz[i][1]), f"ust destek ihlali {k}->{i}"
    # ilk kesilen sol-alt kose olmali
    assert blok_bbox(sirali[0])[:2] == (0.0, 0.0)


def test_destek_simulasyonu_temiz():
    """destek_simulasyonu, guvenli bir siralamada KRITIK ihlal dondurmemeli;
    bozuk bir siralamada ise ihlali yakalamali."""
    from cnc_assistant.gcode import sirala, destek_simulasyonu
    # yan yana iki parca: sag olan once kesilirse sol desteksiz kalir
    sol = _kare_blok(0, 0, 40, 40)
    sag = _kare_blok(100, 0, 140, 40)
    guvenli = sirala([sol, sag], "sol-alt")     # sol once
    assert not [r for r in destek_simulasyonu(guvenli) if r["kritik"]]
    # elle boz: sag'i basa al -> sol SAGDAN desteksiz
    bozuk = [sag, sol]
    krit = [r for r in destek_simulasyonu(bozuk) if r["kritik"]]
    assert krit and krit[0]["yon"] == "sag"


def test_ic_ice_kucuk_once_kesilir():
    """BBOX'i buyuk parcanin icinde kalan (fakat poligon-icerme testinin
    tutmadigi konkav yerlesim) KUCUK parca, buyuk parcadan ONCE kesilmeli.
    Buyuk parca 'L' (konkav): bbox 0..100 ama poligonu kucugu icermez."""
    from cnc_assistant.gcode import sirala, destek_simulasyonu, blok_bbox
    L = ["G0 X0 Y0", "G1 Z-1", "G1 X100 Y0", "G1 X100 Y40", "G1 X40 Y40",
         "G1 X40 Y100", "G1 X0 Y100", "G1 X0 Y0", "G0 Z5"]      # L, bbox 0..100
    kucuk = _kare_blok(60, 60, 80, 80)                          # L'nin koynunda
    srt = sirala([L, kucuk], "sol-alt")
    # kucuk parca (20x20) once, buyuk 'L' sonra
    assert blok_bbox(srt[0]) == (60.0, 60.0, 80.0, 80.0)
    # ters sira -> KRITIK ihlal (buyuk once -> kucuk desteksiz)
    krit = [r for r in destek_simulasyonu([L, kucuk]) if r["kritik"]]
    assert krit and krit[0]["yon"] == "ic"


def test_destek_dinamik_stres():
    """Cesitli rasgele yerlesimlerde (izgara, dagynik, dusey yigin, yatay
    sira) siralama SONRASI hicbir parca desteksiz (KRITIK) kalmamali."""
    import random
    from cnc_assistant.gcode import sirala, destek_simulasyonu

    def rnd(seed, tur):
        random.seed(seed)
        p = []
        if tur == "izgara":
            for i in range(random.randint(3, 6)):
                for j in range(random.randint(3, 6)):
                    x = j * 100 + random.uniform(0, 15)
                    y = i * 100 + random.uniform(0, 15)
                    p.append(_kare_blok(x, y, x + random.uniform(20, 70),
                                        y + random.uniform(20, 70)))
        elif tur == "dagynik":
            for _ in range(random.randint(10, 30)):
                x = random.uniform(0, 800); y = random.uniform(0, 800)
                p.append(_kare_blok(x, y, x + random.uniform(15, 80),
                                    y + random.uniform(15, 80)))
        elif tur == "yigin":                        # dusey yigin (temas eden)
            for c in range(random.randint(2, 5)):
                x = c * 120.0; y = 0.0
                for _ in range(random.randint(2, 5)):
                    h = random.uniform(30, 80)
                    p.append(_kare_blok(x, y, x + random.uniform(40, 90), y + h))
                    y += h
        else:                                       # yatay sira (temas eden)
            for r in range(random.randint(2, 5)):
                y = r * 120.0; x = 0.0
                for _ in range(random.randint(2, 5)):
                    w = random.uniform(30, 80)
                    p.append(_kare_blok(x, y, x + w, y + random.uniform(40, 90)))
                    x += w
        random.shuffle(p)
        return p

    for tur in ("izgara", "dagynik", "yigin", "sira"):
        for s in range(25):
            srt = sirala(rnd(s, tur), "sol-alt")
            krit = [r for r in destek_simulasyonu(srt) if r["kritik"]]
            assert not krit, f"KRITIK ihlal: {tur}/{s}: {krit[:2]}"


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
