#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Proje yonetimi ve klasor toplu isleme
=====================================
Her sey ayri dizinlere yerlestirilir ki karisiklik olmasin:

    <proje_kok>/<proje_adi>/
        01_girdi/            <- islenen girdi dosyalarinin kopyasi
        02_dxf_optimized/    <- optimize edilmis DXF ciktilari
        03_gcode_reordered/  <- yeniden siralanmis G-Code ciktilari
        04_onizleme/         <- PNG onizleme gorselleri
        proje.json           <- proje durumu / ayarlar / islem gunlugu

Bir klasor adresi verildiginde icindeki tum .dxf ve G-Code dosyalari
isim sirasina gore otomatik islenir.
"""

import glob
import json
import os
import shutil
import time

from . import dxf_processor as D
from . import gcode as GC
from . import preview

GCODE_UZANTILAR = {".nc", ".gcode", ".tap", ".ngc", ".cnc"}

VARSAYILAN_OPTS = {
    "node_temizle": True,
    "node_tol": 1e-6,
    "bas_x_orani": 0.75,
    "serit_y_orani": 0.5,
    "alan_orani": 0.10,
    "boyut_orani": 0.50,
    "gcode_mod": "sol-alt",     # sol-alt | serpantin | engel
}


class Proje:
    ALT_DIZINLER = {
        "girdi": "01_girdi",
        "dxf": "02_dxf_optimized",
        "gcode": "03_gcode_reordered",
        "onizleme": "04_onizleme",
    }

    def __init__(self, kok, ad, opts=None):
        self.ad = ad
        self.dizin = os.path.join(kok, ad)
        self.opts = dict(VARSAYILAN_OPTS)
        if opts:
            self.opts.update(opts)
        self.gunluk = []
        self._hazirla()

    # ------------------------------------------------------------------
    def yol(self, tur):
        return os.path.join(self.dizin, self.ALT_DIZINLER[tur])

    def _hazirla(self):
        for alt in self.ALT_DIZINLER.values():
            os.makedirs(os.path.join(self.dizin, alt), exist_ok=True)
        self._durum_yaz()

    def _durum_yaz(self):
        with open(os.path.join(self.dizin, "proje.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"ad": self.ad, "opts": self.opts,
                       "guncelleme": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "gunluk": self.gunluk}, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    def dxf_isle(self, giris, onizleme=True):
        ad = os.path.splitext(os.path.basename(giris))[0]
        shutil.copy2(giris, os.path.join(self.yol("girdi"),
                                         os.path.basename(giris)))
        cikti = os.path.join(self.yol("dxf"), f"{ad}_optimized.dxf")
        opt_keys = ("node_temizle", "node_tol", "bas_x_orani", "serit_y_orani")
        sonuc = D.optimize_ve_kaydet(
            giris, cikti, {k: self.opts[k] for k in opt_keys},
            self.opts["alan_orani"], self.opts["boyut_orani"])
        if onizleme:
            png = os.path.join(self.yol("onizleme"), f"{ad}_oncesi_sonrasi.png")
            preview.baslangic_oncesi_sonrasi(
                sonuc["oncesi"], sonuc["sonrasi"],
                sonuc["riskli_handlelar"], png)
        kayit = {"tur": "dxf", "giris": giris, "cikti": cikti,
                 "silinen_node": sonuc["silinen_node"],
                 "kaydirilan": sonuc["kaydirilan"],
                 "dogrulama": sonuc["dogrulama"]}
        self.gunluk.append(kayit)
        self._durum_yaz()
        return kayit

    def gcode_isle(self, giris, mod=None, onizleme=True):
        mod = mod or self.opts["gcode_mod"]
        ad = os.path.splitext(os.path.basename(giris))[0]
        shutil.copy2(giris, os.path.join(self.yol("girdi"),
                                         os.path.basename(giris)))
        prog = GC.GCodeProgram(giris)
        if not prog.guvenli:
            kayit = {"tur": "gcode", "giris": giris, "cikti": None,
                     "hata": "G91 (artimli mod) - guvenlik iptali"}
            self.gunluk.append(kayit)
            self._durum_yaz()
            return kayit
        prog.auto_sirala(serpantin=(mod == "serpantin"), engel=(mod == "engel"))
        cikti = os.path.join(self.yol("gcode"), f"{ad}_reordered.tap")
        prog.yaz(cikti)
        if onizleme:
            png = os.path.join(self.yol("onizleme"), f"{ad}_sira.png")
            preview.gcode_sira_onizleme(prog.ozet(), png,
                                        baslik=f"{ad} - kesim sirasi")
        kayit = {"tur": "gcode", "giris": giris, "cikti": cikti,
                 "blok": len(prog.sirali_bloklar()), "mod": mod}
        self.gunluk.append(kayit)
        self._durum_yaz()
        return kayit

    # ------------------------------------------------------------------
    def klasor_isle(self, klasor, onizleme=True):
        """Klasordeki tum DXF ve G-Code dosyalarini isim sirasiyla isler."""
        dosyalar = sorted(glob.glob(os.path.join(klasor, "*")))
        sonuclar = []
        for yol in dosyalar:
            if not os.path.isfile(yol):
                continue
            uz = os.path.splitext(yol)[1].lower()
            print("=" * 62)
            print(f"Isleniyor: {yol}")
            print("=" * 62)
            if uz == ".dxf":
                sonuclar.append(self.dxf_isle(yol, onizleme))
            elif uz in GCODE_UZANTILAR:
                sonuclar.append(self.gcode_isle(yol, onizleme=onizleme))
        print("=" * 62)
        print(f"[Proje '{self.ad}'] {len(sonuclar)} dosya islendi. "
              f"Ciktilar: {self.dizin}")
        return sonuclar
