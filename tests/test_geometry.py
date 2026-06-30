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


def test_normal_baslangic_orta_ust_ile_sag_ust_arasi():
    # 100x100 kare -> hedef ust kenarda, x = 75 civari (orta-ust/sag-ust arasi)
    pts = [(0, 0), (100, 0), (100, 100), (0, 100)]
    hedef = G.hedef_nokta(pts, uzun_ince=False)
    assert abs(hedef[1] - 100) < 1e-9          # ust kenar
    assert 50 < hedef[0] < 100                  # orta-ust ile sag-ust arasi
    assert abs(hedef[0] - 75) < 1e-6


def test_serit_baslangic_sag_kenar():
    # Dikey serit (10 genis, 100 yuksek) -> hedef sag kenarda (x=10)
    pts = [(0, 0), (10, 0), (10, 100), (0, 100)]
    xmin, ymin, xmax, ymax, w, h = G.bbox_ve_olcu(pts)
    assert G.uzun_ince_mi(w, h)
    hedef = G.hedef_nokta(pts, uzun_ince=True)
    assert abs(hedef[0] - 10) < 1e-9            # sag kenar
    assert 0 < hedef[1] < 100                    # dikeyde icerde (destek)


def test_baslangic_indeksi_serit_dikey():
    pts = [(0, 0, 0, 0, 0), (10, 0, 0, 0, 0),
           (10, 100, 0, 0, 0), (0, 100, 0, 0, 0)]
    i, uzun, eklenen = G.baslangic_indeksi_belirle(pts)
    assert uzun is True


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
