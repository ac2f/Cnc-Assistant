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
    # 100x100 kare -> hedef ust kenarda, x = 18 civari (sol-ust bolge)
    pts = [(0, 0), (100, 0), (100, 100), (0, 100)]
    hedef = G.hedef_nokta(pts, uzun_ince=False)
    assert abs(hedef[1] - 100) < 1e-9          # ust kenar
    assert 0 <= hedef[0] < 50                    # sol yarim (sol-ust)
    assert abs(hedef[0] - 22) < 1e-6


def test_serit_baslangic_sol_kenar():
    # Dikey serit (10 genis, 100 yuksek) -> hedef_nokta (legacy) sol kenarda
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
    # Sade kare: ust bolge [0,8] tum eni kaplar; baslangic bolgenin solundan
    # %22 -> x=1.76, ust kenar; hedefte vertex yok -> node eklenir (sekil korunur).
    pts = [(0, 0, 0, 0, 0), (8, 0, 0, 0, 0), (8, 8, 0, 0, 0), (0, 8, 0, 0, 0)]
    i, uzun, ekle = G.baslangic_indeksi_belirle(pts)
    bx, by = _efektif_baslangic(pts, i, ekle)
    assert abs(by - 8) < 1e-9              # gercek ust kontur
    assert abs(bx - 1.76) < 1e-6          # bolgenin solundan %22 (sol-ust)
    assert ekle is not None               # mid-edge lead-in eklendi


def test_baslangic_nokta_ekleme_kapali_sol_ust():
    # nokta_ekle=False -> ekleme yok; hedefe en yakin mevcut vertex (sol-ust)
    pts = [(0, 0, 0, 0, 0), (8, 0, 0, 0, 0), (8, 8, 0, 0, 0), (0, 8, 0, 0, 0)]
    i, uzun, ekle = G.baslangic_indeksi_belirle(pts, nokta_ekle=False)
    assert ekle is None
    assert (pts[i][0], pts[i][1]) == (0, 8)


def test_baslangic_egik_n_gercek_ustte_kalir():
    # Egik "N": ust kenar egimli. Baslangic egimin altina DEGIL, gercek ust
    # kontur uzerine (o X'teki en yuksek y'ye) oturmali.
    # Sol dik serit yuksek (y=100), sag tarafa dogru ust kenar asagi egiliyor.
    pts = [(0, 0, 0, 0, 0), (20, 0, 0, 0, 0), (20, 100, 0, 0, 0),
           (100, 100, 0, 0, 0), (100, 0, 0, 0, 0), (120, 0, 0, 0, 0),
           (120, 60, 0, 0, 0), (0, 100, 0, 0, 0)]
    # not: kapali kontur; (0,100)->(0,0) sol kenar. Ust kontur y=100 seridi.
    i, uzun, ekle = G.baslangic_indeksi_belirle(pts)
    bx, by = _efektif_baslangic(pts, i, ekle)
    # hedef X soldan %18 ~ 21.6; o X'te gercek ust kontur y=100 olmali
    assert by > 95                          # gercek uste oturdu (egime degil)


def test_baslangic_kose_payi_tam_kosede_durmaz():
    # Ust bolge yalnizca [2,10] (x<2 tarafi alcak). Baslangic bu bolgenin sol
    # ucundan (x=2 kosesi) az iceride, gercek ust kenarda (y=10) durmali.
    pts = [(0, 0, 0, 0, 0), (10, 0, 0, 0, 0), (10, 10, 0, 0, 0),
           (2, 10, 0, 0, 0), (2, 4, 0, 0, 0), (0, 4, 0, 0, 0)]
    i, uzun, ekle = G.baslangic_indeksi_belirle(pts)
    bx, by = _efektif_baslangic(pts, i, ekle)
    assert abs(by - 10) < 1e-9             # gercek ust kenar (gobekte degil)
    assert bx > 2.5                         # (2,10) kosesinden ic tarafta
    assert bx < 5.0


def test_baslangic_sag_ust_secenegi():
    # destek_yonu saga bakarsa baslangic sag-ust bolgede (soldan %82)
    pts = [(0, 0, 0, 0, 0), (8, 0, 0, 0, 0), (8, 8, 0, 0, 0), (0, 8, 0, 0, 0)]
    i, uzun, ekle = G.baslangic_indeksi_belirle(pts, destek_yonu=(1.0, 1.0))
    bx, by = _efektif_baslangic(pts, i, ekle)
    assert abs(by - 8) < 1e-9              # ust kenar
    assert abs(bx - 6.24) < 1e-6          # bolgenin solundan %78 (sag-ust)


def test_baslangic_dikey_serit_destek_kenarinda():
    # Dikey ince serit: baslangic destek tarafi (varsayilan SOL) kenarda,
    # alttan ~%25 (elle-optimize dosyasi bu yonde).
    pts = [(0, 0, 0, 0, 0), (10, 0, 0, 0, 0),
           (10, 100, 0, 0, 0), (0, 100, 0, 0, 0)]
    i, uzun, ekle = G.baslangic_indeksi_belirle(pts)
    bx, by = _efektif_baslangic(pts, i, ekle)
    assert uzun is True
    assert abs(bx - 0) < 1e-6             # sol kenar (destek tarafi)
    assert 10 < by < 45                    # alttan ~%25
    # Saga bakan destek istenirse sag kenar
    i2, _u, e2 = G.baslangic_indeksi_belirle(pts, destek_yonu=(1.0, 1.0))
    bx2, _by = _efektif_baslangic(pts, i2, e2)
    assert abs(bx2 - 10) < 1e-6           # sag kenar


def test_baslangic_uzun_yatay_serit_orta_sag():
    # Cok uzun (riskli) yatay serit: baslangic ust-orta ile sag-ust arasi.
    # tabaka_w verilir; w/tabaka_w > boyut_orani -> riskli.
    pts = [(0, 0, 0, 0, 0), (900, 0, 0, 0, 0),
           (900, 25, 0, 0, 0), (0, 25, 0, 0, 0)]
    i, uzun, ekle = G.baslangic_indeksi_belirle(
        pts, tabaka_w=1500.0, boyut_orani=0.50)
    bx, by = _efektif_baslangic(pts, i, ekle)
    assert abs(by - 25) < 1e-9             # ust kenar
    assert bx / 900 > 0.55                  # ust-orta ile sag-ust arasi


def test_baslangic_ayakli_dusey_govde_stem_kenarinda():
    # "Raptiye"/⊥: genis tabana oturan ince dusey govde. Serit degildir (genis
    # ayak) ama ust govde ince -> baslangic govdenin ucundaki sivri tepede
    # DEGIL, govde kenarinda, alttan ~%40. Taban y[0,20], govde x[40,60].
    pts = [(0, 0, 0, 0, 0), (100, 0, 0, 0, 0), (100, 20, 0, 0, 0),
           (60, 20, 0, 0, 0), (60, 100, 0, 0, 0), (40, 100, 0, 0, 0),
           (40, 20, 0, 0, 0), (0, 20, 0, 0, 0)]
    assert G.ayakli_dusey_govde_mi(pts, 100.0, 100.0) is True
    i, uzun, ekle = G.baslangic_indeksi_belirle(pts)
    bx, by = _efektif_baslangic(pts, i, ekle)
    assert abs(bx - 40) < 1e-6              # govdenin sol (destek) kenari
    assert by < 60                          # sivri tepede degil, alt-govdede
    assert by > 20                          # ayagin uzerinde
    # Saga bakan destek istenirse govdenin sag kenari
    i2, _u, e2 = G.baslangic_indeksi_belirle(pts, destek_yonu=(1.0, 1.0))
    bx2, _by = _efektif_baslangic(pts, i2, e2)
    assert abs(bx2 - 60) < 1e-6            # govdenin sag kenari


def test_ayakli_dusey_govde_normal_parcayi_yakalamaz():
    # Genis/dolu dikdortgen ayakli-govde SAYILMAZ (ust govde ince degil).
    pts = [(0, 0, 0, 0, 0), (100, 0, 0, 0, 0),
           (100, 120, 0, 0, 0), (0, 120, 0, 0, 0)]
    assert G.ayakli_dusey_govde_mi(pts, 100.0, 120.0) is False


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
