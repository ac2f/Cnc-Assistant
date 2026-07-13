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
        "destek_yonu": _DESTEK_YONU.get(args.destek_yonu, (1.0, 1.0)),
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
    g_dxf.add_argument("--destek-yonu", choices=("sag-ust", "ust", "sol-ust"),
                       default="sag-ust",
                       help="Baslangic (kopma) noktasi bolgesi: sag-ust "
                            "(VARSAYILAN), 'ust' (orta-ust) veya 'sol-ust'. "
                            "Baslangic ust kenarda secilen tarafa yakin bir "
                            "vertex'e tasinir.")
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

    g_nest = ap.add_argument_group("Nesting (dizme) secenekleri")
    g_nest.add_argument("--nest", action="store_true",
                        help="Verilen DXF('ler)deki parcalari tabakaya dizer "
                             "(nesting) ve *_nested.dxf yazar")
    g_nest.add_argument("--tabaka", default="1500x3000",
                        help="Tabaka olcusu mm: 'ENxBOY' (orn 1500x3000)")
    g_nest.add_argument("--tabaka-adet", type=int, default=10,
                        help="Kullanilabilir tabaka sayisi")
    g_nest.add_argument("--nest-motor", choices=("raster", "nfp", "raf"),
                        default="raster",
                        help="Dizme algoritmasi: raster (gercek-sekil, hizli), "
                             "nfp (NFP+genetik, pyclipper), raf (shelf/hizli)")
    g_nest.add_argument("--nest-kenar", type=float, default=15.0,
                        help="Tabaka kenar boslugu (mm)")
    g_nest.add_argument("--nest-kerf", type=float, default=4.0,
                        help="Bicak payi / kerf (mm)")
    g_nest.add_argument("--nest-bosluk", type=float, default=0.1,
                        help="Parcalar arasi ek bosluk payi (mm)")
    g_nest.add_argument("--nest-aci", default="0,90",
                        help="Denenecek rotasyonlar (derece, virgulle): orn '0,90'")
    g_nest.add_argument("--nest-oncelik", choices=("x", "y"), default="y",
                        help="Dizme onceligi: 'y' (alt satirlar once) veya "
                             "'x' (sol sutunlar once)")
    g_nest.add_argument("--nest-sure", type=float, default=25.0,
                        help="NFP genetik icin zaman butcesi (saniye)")
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


def _nest_parcalar(yol):
    """DXF'teki kapali konturlari nesting parcasi olarak dondurur."""
    doc = ezdxf.readfile(yol)
    parcalar = []
    for i, v in enumerate(D.baslangic_noktalari_ve_konturlar(doc)):
        pts = v["kontur"]
        if len(pts) < 3:
            continue
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        if max(xs) - min(xs) < 1e-6 or max(ys) - min(ys) < 1e-6:
            continue
        parcalar.append({"id": f"{os.path.basename(yol)}#{i}", "poly": pts,
                         "adet": 1})
    return parcalar


def _nest_dxf_yaz(cikti, tabakalar, yerlesim):
    """Tabakalari yan yana, yerlesmis parcalari uzerlerine yazar (*_nested.dxf)."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    ofsx = 0.0
    tab_ofset = []
    for t in tabakalar:
        xs = [p[0] for p in t["poly"]]; ys = [p[1] for p in t["poly"]]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        tab_ofset.append((ofsx - x0, -y0))
        msp.add_lwpolyline([(x + ofsx - x0, y - y0) for x, y in t["poly"]],
                           close=True, dxfattribs={"layer": "TABAKA"})
        ofsx += (x1 - x0) + max((x1 - x0), (y1 - y0)) * 0.05 + 10
    for y in yerlesim:
        dx, dy = tab_ofset[y.get("tabaka", 0)] if tab_ofset else (0.0, 0.0)
        msp.add_lwpolyline([(x + dx, y2 + dy) for x, y2 in y["poly"]],
                           close=True, dxfattribs={"layer": "PARCA"})
    doc.saveas(cikti)


def nest_isle(yollar, args):
    from . import nesting as NEST
    from . import nesting_nfp as NEST_NFP
    try:
        W, H = (float(v) for v in args.tabaka.lower().split("x"))
    except Exception:
        print(f"Hata: --tabaka 'ENxBOY' olmali (orn 1500x3000), verilen: {args.tabaka}")
        return
    aci = [float(a) for a in str(args.nest_aci).split(",") if a.strip() != ""] or [0]
    kok = os.path.splitext(yollar[0])[0]

    # RAF (shelf): gercek doc uzerinde bbox-raf paketleme (nest_doc).
    if args.nest_motor == "raf":
        doc = ezdxf.readfile(yollar[0])
        r = NEST.nest_doc(doc, tabaka_genislik=W,
                          bosluk=args.nest_kerf + args.nest_bosluk,
                          kenar=args.nest_kenar)
        cikti = f"{kok}_nested.dxf"
        doc.saveas(cikti)
        print(f"Nesting (raf/shelf): {r.get('parca_sayisi')} parca -> tabaka eni "
              f"{W:.0f} mm · cikti: {cikti}")
        return

    parcalar = []
    for yol in yollar:
        if os.path.isfile(yol) and yol.lower().endswith(".dxf"):
            parcalar += _nest_parcalar(yol)
    if not parcalar:
        print("Hata: DXF('ler)de dizilecek kapali parca bulunamadi.")
        return
    tabakalar = [{"poly": [[0, 0], [W, 0], [W, H], [0, H]]}
                 for _ in range(max(1, args.tabaka_adet))]
    ayar = {"kenar": args.nest_kenar, "kerf": args.nest_kerf,
            "bosluk": args.nest_bosluk, "rotasyonlar": aci,
            "oncelik": args.nest_oncelik, "motor": args.nest_motor,
            "sure_limiti": args.nest_sure}
    print(f"Nesting: {len(parcalar)} parca -> {W:.0f}x{H:.0f} mm tabaka · "
          f"motor={args.nest_motor} · kenar={args.nest_kenar} kerf={args.nest_kerf} "
          f"bosluk={args.nest_bosluk} · aci={aci} · oncelik={args.nest_oncelik}")
    if args.nest_motor == "nfp":
        r = NEST_NFP.nfp_nest(parcalar, tabakalar, ayar)
        if r is None:
            print("  pyclipper kurulu degil -> raster motoruna dusuldu "
                  "(NFP icin: pip install pyclipper)")
            r = NEST.raster_nest(parcalar, tabakalar, ayar)
    else:
        r = NEST.raster_nest(parcalar, tabakalar, ayar)
    yer = r.get("yerlesim", [])
    sigmayan = sum(x["adet"] for x in r.get("yerlesmeyen", []))
    cikti = f"{kok}_nested.dxf"
    _nest_dxf_yaz(cikti, tabakalar, yer)
    print(f"  Yerlesen: {len(yer)}/{len(parcalar)} · sigmayan: {sigmayan} · "
          f"doluluk: {r.get('doluluk')} · cikti: {cikti}")


def main(argv=None):
    args = kurulum_parser().parse_args(argv)

    if args.web:
        from . import webapp
        webapp.calistir(port=args.port, ac=args.tarayici_ac)
        return

    if args.nest:
        if not args.dosyalar:
            print("Hata: --nest icin en az bir DXF dosyasi verin.")
            return
        nest_isle(args.dosyalar, args)
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
