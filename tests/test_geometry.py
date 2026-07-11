#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""geometry modulu birim testleri."""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cnc_assistant import geometry as G


def _cevre(pts, kapali=True):
    n = len(pts)
    L = 0.0
    rng = range(n) if kapali else range(n - 1)
    for i in rng:
        a, b = pts[i], pts[(i + 1) % n]
        L += math.hypot(b[0] - a[0], b[1] - a[1])
    return L


def test_node_sadelestir_collinear_kaldirir():
    # Kenarlari uzerinde fazladan es-dogrultulu noktalar olan kare
    pts = [
        (0, 0, 0, 0, 0),
        (5, 0, 0, 0, 0),    # gereksiz (alt kenar ortasi)
        (10, 0, 0, 0, 0),
        (10, 5, 0, 0, 0),   # gereksiz (sag kenar ortasi)
        (10, 10, 0, 0, 0),
        (0, 10, 0, 0, 0),
        (0, 5, 0, 0, 0),    # gereksiz (sol kenar ortasi)
    ]
    cevre_once = _cevre(pts)
    sade, silinen = G.node_sadelestir(pts, kapali=True)
    assert silinen == 3
    assert len(sade) == 4
    # Cevre birebir korunmali
    assert abs(_cevre(sade) - cevre_once) < 1e-9


def test_node_sadelestir_yay_korunur():
    # bulge tasiyan (yay) segmentin noktasi silinmez
    pts = [
        (0, 0, 0, 0, 0),
        (5, 0, 0, 0, 0.5),   # bu noktadan giden segment yay -> komsu silinmez
        (10, 0, 0, 0, 0),
        (10, 10, 0, 0, 0),
        (0, 10, 0, 0, 0),
    ]
    sade, silinen = G.node_sadelestir(pts, kapali=True)
    # (5,0) -> giden bulge!=0; (10,0) -> gelen bulge!=0; ikisi de korunur
    assert (5, 0, 0, 0, 0.5) in sade
    assert (10, 0, 0, 0, 0) in sade


def test_node_sadelestir_genislik_korunur():
    # taper (genislik) tasiyan nokta silinmez
    pts = [
        (0, 0, 0, 0, 0),
        (5, 0, 1.0, 2.0, 0),  # genislik var -> silinmemeli
        (10, 0, 0, 0, 0),
        (10, 10, 0, 0, 0),
        (0, 10, 0, 0, 0),
    ]
    sade, silinen = G.node_sadelestir(pts, kapali=True)
    assert any(abs(p[2] - 1.0) < 1e-9 for p in sade)


def test_normal_baslangic_sol_ust():
    # 100x100 kare -> hedef ust kenarda, x = 20 civari (sol-ust bolge)
    pts = [(0, 0), (100, 0), (100, 100), (0, 100)]
    hedef = G.hedef_nokta(pts, uzun_ince=False)
    assert abs(hedef[1] - 100) < 1e-9          # ust kenar
    assert 0 <= hedef[0] < 50                    # sol yarim (sol-ust)
    assert abs(hedef[0] - 20) < 1e-6


def test_serit_baslangic_sol_kenar():
    # Dikey serit (10 genis, 100 yuksek) -> hedef sol kenarda (x=0)
    pts = [(0, 0), (10, 0), (10, 100), (0, 100)]
    xmin, ymin, xmax, ymax, w, h = G.bbox_ve_olcu(pts)
    assert G.uzun_ince_mi(w, h)
    hedef = G.hedef_nokta(pts, uzun_ince=True)
    assert abs(hedef[0] - 0) < 1e-9             # sol kenar
    assert 0 < hedef[1] < 100                    # dikeyde icerde (destek)


def test_destek_ucu_dikdortgen_sag_ust_kose():
    # Dikdortgen -> baslangic sag-ust kosede (max x+y)
    pts = [(0, 0), (100, 0), (100, 60), (0, 60)]
    i = G.destek_ucu_indeks(pts)
    assert pts[i] == (100, 60)


def test_destek_ucu_saga_bakan_ucgen():
    # Saga bakan ucgen -> baslangic sag ucta (destek yonundeki extremum)
    pts = [(0, 20), (0, -20), (60, 0)]
    i = G.destek_ucu_indeks(pts)
    assert pts[i] == (60, 0)


def test_destek_ucu_yon_ayarlanabilir():
    # Destek yonu 'ust' verilirse en ust nokta secilir
    pts = [(0, 0), (100, 0), (100, 60), (0, 60), (50, 90)]
    i = G.destek_ucu_indeks(pts, d=(0.2, 1.0))
    assert pts[i] == (50, 90)


def _efektif_baslangic(pts, i, ekle):
    """Test yardimcisi: (i, ekle) sonucundan efektif baslangic (x, y)."""
    if i is None and ekle is not None:
        return (ekle[1][0], ekle[1][1])
    return (pts[i][0], pts[i][1])


def test_baslangic_kucuk_parca_sol_ust_kenar_ekler():
    # Sade kare: ust kenarda hedefe (soldan %20) vertex yok -> tam hedefte
    # (x=1.6, ust kenar) baslangic node'u eklenir (sekil korunur).
    pts = [(0, 0, 0, 0, 0), (8, 0, 0, 0, 0), (8, 8, 0, 0, 0), (0, 8, 0, 0, 0)]
    i, uzun, ekle = G.baslangic_indeksi_belirle(pts)
    bx, by = _efektif_baslangic(pts, i, ekle)
    assert abs(by - 8) < 1e-9              # ust kenar
    assert abs(bx - 1.6) < 1e-6            # soldan %20 (sol-ust)
    assert ekle is not None               # mid-edge lead-in eklendi


def test_baslangic_nokta_ekleme_kapali_sol_ust_kose():
    # nokta_ekle=False -> ekleme yok; mevcut en yakin vertex (sol-ust kose)
    pts = [(0, 0, 0, 0, 0), (8, 0, 0, 0, 0), (8, 8, 0, 0, 0), (0, 8, 0, 0, 0)]
    i, uzun, ekle = G.baslangic_indeksi_belirle(pts, nokta_ekle=False)
    assert ekle is None
    assert (pts[i][0], pts[i][1]) == (0, 8)


def test_baslangic_mevcut_vertex_hedefte_snap():
    # Ust kenarda hedefe (x=2.0) tam oturan vertex varsa yeni node EKLENMEZ.
    pts = [(0, 0, 0, 0, 0), (10, 0, 0, 0, 0), (10, 10, 0, 0, 0),
           (2, 10, 0, 0, 0), (0, 10, 0, 0, 0)]
    i, uzun, ekle = G.baslangic_indeksi_belirle(pts)
    assert ekle is None
    assert (pts[i][0], pts[i][1]) == (2, 10)


def test_baslangic_sag_ust_secenegi():
    # destek_yonu saga bakarsa baslangic sag-ust bolgede (soldan %80)
    pts = [(0, 0, 0, 0, 0), (8, 0, 0, 0, 0), (8, 8, 0, 0, 0), (0, 8, 0, 0, 0)]
    i, uzun, ekle = G.baslangic_indeksi_belirle(pts, destek_yonu=(1.0, 1.0))
    bx, by = _efektif_baslangic(pts, i, ekle)
    assert abs(by - 8) < 1e-9              # ust kenar
    assert abs(bx - 6.4) < 1e-6            # soldan %80 (sag-ust)


def test_baslangic_indeksi_serit_dikey():
    # Dikey serit: sol kenarda, ucundan iceride; yeni node EKLENMEZ.
    pts = [(0, 0, 0, 0, 0), (10, 0, 0, 0, 0),
           (10, 100, 0, 0, 0), (0, 100, 0, 0, 0)]
    i, uzun, eklenen = G.baslangic_indeksi_belirle(pts)
    assert uzun is True
    assert eklenen is None
    assert pts[i][0] == 0                   # sol kenar


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
