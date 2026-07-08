#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Etkilesimli G-Code siralama editoru
==================================
Terminal arayuzu ile kesim bloklarinin sirasini canli olarak goruntuleyip
duzenlemeyi saglar. Ozellikler:

  * Numarali blok listesi (sira, baslangic X/Y).
  * Iki blogun yerini degistirme:  `59 60`  -> 59 ve 60. sira yer degistirir.
  * Bir blogu baska konuma tasima:  `tasi 12 3`
  * Otomatik siralama:  `auto`  (sol-alt -> sag-ust),  `serp` (zigzag).
  * GERI ALMA:  `geri`  (son degisikligi geri alir),  `ileri` (yinele).
  * CANLI ONIZLEME TOGGLE:  `onizleme`  -> her komutta PNG'yi otomatik
    gunceller (ac/kapa). `goster` -> simdi bir kez PNG uret.
  * `kaydet` -> .tap dosyasina yaz.   `cik` -> cikis.

Komutlar hem `input()` ile (gercek terminal) hem de programatik olarak
(`EtkilesimliEditor.komut_calistir`) calistirilabilir; bu ikincisi testleri
ve betikle surulmesini mumkun kilar.
"""

import os

from .gcode import GCodeProgram, blok_bas_xy, toplam_bosta_yol
from . import preview


YARDIM = """\
Komutlar:
  <i> <j>         i ve j. siradaki bloklarin yerini degistir (orn: 59 60)
  tasi <i> <j>    i. bloku j. konuma tasi
  auto            varsayilan siralama (sol-alt -> sag-ust, destek korumali)
  engel           engel-farkindalikli (golge) siralama
  serp            serpantin (zigzag) siralama
  liste           blok listesini goster
  geri            son degisikligi geri al
  ileri           geri alinani yinele
  onizleme        canli PNG onizleme ac/kapa (toggle)
  goster          su anki sirayla PNG onizleme uret
  kaydet [dosya]  yeniden siralanmis .tap olarak yaz
  yardim          bu yardimi goster
  cik             cikis (kaydetmeden)
"""


class EtkilesimliEditor:
    def __init__(self, yol, png_yol=None, canli_onizleme=False):
        self.prog = GCodeProgram(yol)
        self.yol = yol
        kok, _ = os.path.splitext(yol)
        self.png_yol = png_yol or f"{kok}_sira_onizleme.png"
        self.canli_onizleme = canli_onizleme
        self.gecmis = []     # geri-al yigini (blok listelerinin kopyalari)
        self.ileri_yigin = []
        self.cikti_dosyasi = None

        if self.prog.guvenli and not self.prog.bloklar:
            for u in self.prog.uyarilar:
                print(f"[Uyari] {u}")

    # ------------------------------------------------------------------
    # Durum yonetimi
    # ------------------------------------------------------------------
    def _anlik_kaydet(self):
        """Geri-al icin mevcut blok sirasini yigina koy."""
        self.gecmis.append(list(self.prog.bloklar))
        self.ileri_yigin.clear()

    def _onizleme_guncelle(self, zorla=False):
        if self.canli_onizleme or zorla:
            ok = preview.gcode_sira_onizleme(self.prog.ozet(), self.png_yol)
            if ok:
                print(f"[Onizleme] Guncellendi -> {self.png_yol}")
            elif zorla:
                print("[Onizleme] matplotlib kurulu degil; PNG uretilemedi.")

    # ------------------------------------------------------------------
    # Liste / durum
    # ------------------------------------------------------------------
    def liste_yazdir(self):
        ozet = self.prog.ozet()
        if not ozet:
            print("(kesim blogu yok)")
            return
        print(f"{'Sira':>4}  {'X':>10}  {'Y':>10}  {'derinlik':>8}  {'satir':>6}")
        for b in ozet:
            etiket = f"ic({b['derinlik']})" if b["derinlik"] else "dis"
            print(f"{b['sira']:>4}  {b['x']:>10.2f}  {b['y']:>10.2f}  "
                  f"{etiket:>8}  {b['satir_sayisi']:>6}")
        ihlaller = self.prog.icerme_ihlalleri()
        if ihlaller:
            print(f"[UYARI] {len(ihlaller)} icerme ihlali: "
                  + ", ".join(f"{a}(ic) < {b}(dis)" for a, b in ihlaller)
                  + "  -> 'auto' ile duzeltebilirsiniz.")
        else:
            print("[OK] Icerme kurali saglaniyor (en icteki once kesiliyor).")
        print(f"Bosta tasima: {self.prog.bosta_yol():.1f} | "
              f"Canli onizleme: {'ACIK' if self.canli_onizleme else 'KAPALI'}")

    # ------------------------------------------------------------------
    # Duzenleme islemleri
    # ------------------------------------------------------------------
    def yer_degistir(self, i, j):
        n = len(self.prog.bloklar)
        if not (1 <= i <= n and 1 <= j <= n):
            print(f"[Hata] Sira numarasi 1..{n} araliginda olmali.")
            return False
        if i == j:
            print("[Bilgi] Ayni sira; degisiklik yok.")
            return False
        self._anlik_kaydet()
        b = self.prog.bloklar
        b[i - 1], b[j - 1] = b[j - 1], b[i - 1]
        print(f"[OK] {i}. ve {j}. bloklar yer degistirdi.")
        return True

    def tasi(self, i, j):
        n = len(self.prog.bloklar)
        if not (1 <= i <= n and 1 <= j <= n):
            print(f"[Hata] Sira numarasi 1..{n} araliginda olmali.")
            return False
        if i == j:
            return False
        self._anlik_kaydet()
        b = self.prog.bloklar
        blok = b.pop(i - 1)
        b.insert(j - 1, blok)
        print(f"[OK] {i}. blok {j}. konuma tasindi.")
        return True

    def auto(self, serpantin=False, engel=False):
        self._anlik_kaydet()
        self.prog.auto_sirala(serpantin=serpantin, engel=engel)
        ad = ("Serpantin" if serpantin else "Engel-farkindalikli" if engel
              else "Sol-alt -> sag-ust")
        print(f"[OK] {ad} siralama uygulandi.")
        return True

    def geri_al(self):
        if not self.gecmis:
            print("[Bilgi] Geri alinacak islem yok.")
            return False
        self.ileri_yigin.append(list(self.prog.bloklar))
        self.prog.bloklar = self.gecmis.pop()
        print("[OK] Son islem geri alindi.")
        return True

    def yinele(self):
        if not self.ileri_yigin:
            print("[Bilgi] Yinelenecek islem yok.")
            return False
        self.gecmis.append(list(self.prog.bloklar))
        self.prog.bloklar = self.ileri_yigin.pop()
        print("[OK] Islem yinelendi.")
        return True

    def onizleme_toggle(self):
        self.canli_onizleme = not self.canli_onizleme
        print(f"[OK] Canli onizleme: {'ACIK' if self.canli_onizleme else 'KAPALI'}")
        if self.canli_onizleme:
            self._onizleme_guncelle(zorla=True)

    def kaydet(self, cikti=None):
        self.cikti_dosyasi = self.prog.yaz(cikti)
        print(f"[OK] Kaydedildi -> {self.cikti_dosyasi}")
        return self.cikti_dosyasi

    # ------------------------------------------------------------------
    # Komut ayristirma (tek satir)
    # ------------------------------------------------------------------
    def komut_calistir(self, satir):
        """Bir komut satirini calistirir. Doner: True (devam) / False (cik)."""
        satir = satir.strip()
        if not satir:
            return True
        parcalar = satir.split()
        komut = parcalar[0].lower()
        degisti = False

        if komut in ("cik", "quit", "exit", "q"):
            return False
        elif komut in ("yardim", "help", "?"):
            print(YARDIM)
        elif komut in ("liste", "list", "ls", "l"):
            self.liste_yazdir()
        elif komut in ("auto", "sol-alt", "varsayilan"):
            degisti = self.auto()
        elif komut in ("engel", "golge"):
            degisti = self.auto(engel=True)
        elif komut in ("serp", "serpantin", "zigzag"):
            degisti = self.auto(serpantin=True)
        elif komut in ("tasi", "move", "mv"):
            if len(parcalar) >= 3 and _int(parcalar[1]) and _int(parcalar[2]):
                degisti = self.tasi(int(parcalar[1]), int(parcalar[2]))
            else:
                print("[Hata] Kullanim: tasi <kaynak_sira> <hedef_sira>")
        elif komut in ("geri", "undo", "u"):
            degisti = self.geri_al()
        elif komut in ("ileri", "redo"):
            degisti = self.yinele()
        elif komut in ("onizleme", "preview", "toggle"):
            self.onizleme_toggle()
        elif komut in ("goster", "show", "png"):
            self._onizleme_guncelle(zorla=True)
        elif komut in ("kaydet", "save", "w"):
            self.kaydet(parcalar[1] if len(parcalar) > 1 else None)
        elif _int(parcalar[0]) and len(parcalar) >= 2 and _int(parcalar[1]):
            # "59 60" -> yer degistir
            degisti = self.yer_degistir(int(parcalar[0]), int(parcalar[1]))
        else:
            print(f"[Hata] Bilinmeyen komut: '{satir}'  ('yardim' yazin)")

        if degisti:
            self._onizleme_guncelle()
        return True

    # ------------------------------------------------------------------
    # REPL
    # ------------------------------------------------------------------
    def calistir(self):
        if not self.prog.guvenli:
            print("[GUVENLIK] Dosyada G91 (artimli mod) var; etkilesimli "
                  "siralama kapatildi (konumlar bozulurdu).")
            return
        if not self.prog.bloklar and not self.prog.sabit_son:
            print("[Bilgi] Siralanacak kesim blogu yok.")
            return

        print("=" * 62)
        print(f"Etkilesimli G-Code Siralama  |  {os.path.basename(self.yol)}")
        print("=" * 62)
        for u in self.prog.uyarilar:
            print(f"[GUVENLIK] {u}")
        print(YARDIM)
        self.liste_yazdir()
        self._onizleme_guncelle()

        while True:
            try:
                satir = input("\ncnc> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not self.komut_calistir(satir):
                break

        if self.cikti_dosyasi is None:
            cevap = ""
            try:
                cevap = input("Cikmadan once kaydedilsin mi? [e/H] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                cevap = ""
            if cevap in ("e", "evet", "y", "yes"):
                self.kaydet()
        print("Cikildi.")


def _int(s):
    try:
        int(s)
        return True
    except (ValueError, TypeError):
        return False
