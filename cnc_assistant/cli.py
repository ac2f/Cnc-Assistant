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
from . import project as P
from .interactive import EtkilesimliEditor

GCODE_UZANTILAR = {".nc", ".gcode", ".tap", ".ngc", ".cnc", ".txt"}


_DESTEK_YONU = {"sol-ust": (-1.0, 1.0), "ust": (0.0, 1.0), "sag-ust": (1.0, 1.0)}


def dxf_opts(args):
    return {
        "node_temizle": not args.node_temizleme_yok,
        "node_tol": args.node_tol,
        "destek_yonu": _DESTEK_YONU.get(args.destek_yonu, (-1.0, 1.0)),
    }


def dxf_isle(yol, args):
    kok, _ = os.path.splitext(yol)
    cikti = f"{kok}_optimized.dxf"
    sonuc = D.optimize_ve_kaydet(yol, cikti, dxf_opts(args),
                                 args.alan_orani, args.boyut_orani)
    if not args.onizleme_yok:
        preview.baslangic_oncesi_sonrasi(
            sonuc["oncesi"], sonuc["sonrasi"],
            sonuc["riskli_handlelar"], f"{kok}_oncesi_sonrasi.png")


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
    ap.add_argument("dosyalar", nargs="*",
                    help="Bir veya daha fazla .dxf / G-Code dosyasi ya da "
                         "KLASOR (klasor verilirse icindekiler otomatik islenir)")

    g_genel = ap.add_argument_group("Genel / arayuz")
    g_genel.add_argument("--web", action="store_true",
                         help="Web arayuzunu baslat (tarayicida acilir)")
    g_genel.add_argument("--port", type=int, default=8000,
                         help="Web arayuzu portu")
    g_genel.add_argument("--tarayici-ac", action="store_true",
                         help="Web arayuzunu otomatik olarak tarayicida ac")
    g_genel.add_argument("--proje", default=None,
                         help="Proje adi (ciktiler ayri dizinlere yerlesir)")
    g_genel.add_argument("--proje-kok", default=None,
                         help="Proje kok dizini (varsayilan: ./cnc_ciktilar)")

    g_dxf = ap.add_argument_group("DXF secenekleri")
    g_dxf.add_argument("--alan-orani", type=float, default=0.10,
                       help="Risk esigi: parca bbox alani / tabaka alani")
    g_dxf.add_argument("--boyut-orani", type=float, default=0.50,
                       help="Risk esigi: parca eni-boyu / tabaka eni-boyu")
    g_dxf.add_argument("--destek-yonu", choices=("sol-ust", "ust", "sag-ust"),
                       default="sol-ust",
                       help="Baslangic (kopma) noktasi bolgesi: sol-ust "
                            "(varsayilan; elle-optimize yerlesimine en yakin), "
                            "'ust' (orta-ust) veya 'sag-ust'. Baslangic ust "
                            "kenarda secilen tarafa yakin bir vertex'e tasinir.")
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


def _proje_opts(args):
    return {
        "node_temizle": not args.node_temizleme_yok,
        "node_tol": args.node_tol,
        "destek_yonu": _DESTEK_YONU.get(args.destek_yonu, (1.0, 1.0)),
        "alan_orani": args.alan_orani,
        "boyut_orani": args.boyut_orani,
        "gcode_mod": ("serpantin" if args.serpantin
                      else "engel" if args.engel else "sol-alt"),
    }


def klasor_isle(klasor, args):
    kok = args.proje_kok or os.path.join(klasor, "cnc_ciktilar")
    ad = args.proje or os.path.basename(os.path.normpath(klasor)) or "proje"
    proje = P.Proje(kok, ad, _proje_opts(args))
    proje.klasor_isle(klasor, onizleme=not args.onizleme_yok)


def main(argv=None):
    args = kurulum_parser().parse_args(argv)

    if args.web:
        from . import webapp
        webapp.calistir(port=args.port, ac=args.tarayici_ac)
        return

    if not args.dosyalar:
        kurulum_parser().print_help()
        return

    # Proje modu: cikti dosyalari ayri dizinlere yerlesir
    proje = None
    if args.proje or args.proje_kok:
        kok = args.proje_kok or os.path.join(os.getcwd(), "cnc_ciktilar")
        proje = P.Proje(kok, args.proje or "proje", _proje_opts(args))

    for yol in args.dosyalar:
        if os.path.isdir(yol):
            klasor_isle(yol, args)
            continue
        print("=" * 62)
        print(f"Dosya: {yol}")
        print("=" * 62)
        if not os.path.isfile(yol):
            print(f"Hata: Dosya bulunamadi -> {yol}")
            continue
        uz = os.path.splitext(yol)[1].lower()
        if uz == ".dxf":
            if proje:
                proje.dxf_isle(yol, onizleme=not args.onizleme_yok)
            else:
                dxf_isle(yol, args)
        elif uz in GCODE_UZANTILAR:
            if proje and not args.etkilesimli:
                proje.gcode_isle(yol, onizleme=not args.onizleme_yok)
            else:
                gcode_isle(yol, args)
        else:
            print(f"Hata: Desteklenmeyen uzanti '{uz}'.")


if __name__ == "__main__":
    main()
