#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Komut satiri arayuzu
====================
Dosya uzantisina gore mod otomatik secilir:

    cnc-assistant tabaka.dxf            DXF: node temizligi + baslangic + risk
    cnc-assistant kesim.tap             G-Code: otomatik yeniden siralama
    cnc-assistant kesim.tap -e          G-Code: ETKILESIMLI editor (canli)
    cnc-assistant a.dxf b.tap ...       Birden fazla dosya
"""

import argparse
import os
import sys

try:
    import ezdxf
except ImportError:
    print("Hata: 'ezdxf' kutuphanesi kurulu degil.  ->  pip install ezdxf")
    sys.exit(1)

from . import dxf_processor as D
from . import geometry as G
from . import preview
from . import gcode
from .interactive import EtkilesimliEditor

GCODE_UZANTILAR = {".nc", ".gcode", ".tap", ".ngc", ".cnc", ".txt"}


def dxf_isle(yol, args):
    doc = ezdxf.readfile(yol)
    msp = doc.modelspace()

    # ONIZLEME icin once orijinal baslangic noktalarini yakala
    oncesi = D.baslangic_noktalari_ve_konturlar(doc) if not args.onizleme_yok else None

    opts = {
        "node_temizle": not args.node_temizleme_yok,
        "node_tol": args.node_tol,
        "bas_x_orani": args.bas_x_orani,
        "serit_y_orani": args.serit_y_orani,
    }

    D.adim1_baslangic_optimizasyonu(msp, opts)
    print("-" * 62)
    riskli = D.adim2_riskli_parca_uyarisi(msp, args.alan_orani, args.boyut_orani)

    kok, _ = os.path.splitext(yol)
    cikti = f"{kok}_optimized.dxf"
    doc.saveas(cikti)
    print("-" * 62)
    D.butunluk_dogrula(yol, cikti)
    print(f"[Adim 1] Cikti dosyasi: {cikti}")

    if not args.onizleme_yok:
        sonrasi_doc = ezdxf.readfile(cikti)
        sonrasi = D.baslangic_noktalari_ve_konturlar(sonrasi_doc)
        preview.baslangic_oncesi_sonrasi(
            oncesi, sonrasi,
            {h for _, h, _, _, _ in riskli},
            f"{kok}_oncesi_sonrasi.png")


def gcode_isle(yol, args):
    if args.etkilesimli:
        editor = EtkilesimliEditor(yol, canli_onizleme=args.canli_onizleme)
        editor.calistir()
    else:
        gcode.yeniden_sirala_dosya(yol, serpantin=args.serpantin,
                                   engel=args.engel)


def kurulum_parser():
    ap = argparse.ArgumentParser(
        prog="cnc-assistant",
        description="CNC tabaka kesimi: DXF node temizligi + baslangic-noktasi "
                    "optimizasyonu, riskli parca uyarisi ve G-Code blok siralama "
                    "(otomatik veya etkilesimli).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("dosyalar", nargs="+",
                    help="Bir veya daha fazla .dxf ve/veya G-Code dosyasi")

    g_dxf = ap.add_argument_group("DXF secenekleri")
    g_dxf.add_argument("--alan-orani", type=float, default=0.10,
                       help="Risk esigi: parca bbox alani / tabaka alani")
    g_dxf.add_argument("--boyut-orani", type=float, default=0.50,
                       help="Risk esigi: parca eni-boyu / tabaka eni-boyu")
    g_dxf.add_argument("--bas-x-orani", type=float, default=G.BASLANGIC_X_ORANI,
                       help="Normal parca baslangic yatay konumu (0.5=orta-ust, "
                            "1.0=sag-ust; aradaki deger destek birakir)")
    g_dxf.add_argument("--serit-y-orani", type=float, default=G.SERIT_Y_ORANI,
                       help="Serit parca baslangic dikey konumu sag kenarda "
                            "(0=sag-alt, 1=sag-ust)")
    g_dxf.add_argument("--node-tol", type=float, default=G.NODE_TOL,
                       help="Node sadelestirme tolerasi (cizim birimi)")
    g_dxf.add_argument("--node-temizleme-yok", action="store_true",
                       help="Gereksiz node temizligini kapat")
    g_dxf.add_argument("--onizleme-yok", action="store_true",
                       help="DXF icin oncesi/sonrasi PNG uretme")

    g_gc = ap.add_argument_group("G-Code secenekleri")
    g_gc.add_argument("--serpantin", action="store_true",
                      help="Otomatik siralamada zigzag deseni")
    g_gc.add_argument("--engel", action="store_true",
                      help="Sol-alt->sag-ust yerine engel-farkindalikli "
                           "(golge) siralama kullan")
    g_gc.add_argument("-e", "--etkilesimli", action="store_true",
                      help="G-Code icin etkilesimli (canli) siralama editorunu ac")
    g_gc.add_argument("--canli-onizleme", action="store_true",
                      help="Etkilesimli modda PNG onizlemeyi basta ACIK baslat")
    return ap


def main(argv=None):
    args = kurulum_parser().parse_args(argv)

    for yol in args.dosyalar:
        print("=" * 62)
        print(f"Dosya: {yol}")
        print("=" * 62)
        if not os.path.isfile(yol):
            print(f"Hata: Dosya bulunamadi -> {yol}")
            continue
        uz = os.path.splitext(yol)[1].lower()
        if uz == ".dxf":
            dxf_isle(yol, args)
        elif uz in GCODE_UZANTILAR:
            gcode_isle(yol, args)
        else:
            print(f"Hata: Desteklenmeyen uzanti '{uz}'.")


if __name__ == "__main__":
    main()
