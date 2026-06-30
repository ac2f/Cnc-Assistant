#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
G-Code blok siralama
====================
G-Code URETILMEZ. Mevcut satirlar AYNEN korunur; yalnizca bagimsiz kesim
bloklarinin SIRASI degistirilir.

Siralama hedefi: malzeme her zaman destekte kalacak sekilde SOL-ALTTAN
SAG-USTE dogru ilerlemek. Ayrica bir parcanin "uzerine uzanan / golgede
birakan" parcalar once temizlenir (engel-farkindalikli siralama).

`GCodeProgram` sinifi dosyayi header / kesim-bloklari / footer olarak ayristirir;
hem otomatik siralama hem de etkilesimli (elle) duzenleme bunu kullanir.
"""

import math
import os
import re

_WORD_RE = re.compile(r"([A-Za-z])\s*([+-]?\d+\.?\d*)")
_BITIS_RE = re.compile(r"\b(M0?2|M30|M0?5|M0?9|G28|G53)\b|^\s*%\s*$", re.I)

# X-araliklari "ayni kolonda / cakisan" sayilmasi icin tolerans orani.
_X_CAKISMA_TOLERANSI = 0.02


def satir_kelimeleri(satir):
    s = re.sub(r"\(.*?\)", "", satir)     # ( ... ) yorumlari
    s = s.split(";", 1)[0]                 # ; yorumlari
    return {h.upper(): float(v) for h, v in _WORD_RE.findall(s)}


def _blok_basi_mi(satir):
    """Yeni kesim blogunun basi: X ve Y iceren G0/G00 hizli hareket."""
    w = satir_kelimeleri(satir)
    return w.get("G") == 0.0 and "X" in w and "Y" in w


def g91_var_mi(satirlar):
    """Artimli mod (G91) kontrolu. G91.1 (yay merkezi modu) haric."""
    rx = re.compile(r"\bG91(?!\.)\b", re.I)
    for s in satirlar:
        temiz = re.sub(r"\(.*?\)", "", s).split(";", 1)[0]
        if rx.search(temiz):
            return True
    return False


# ----------------------------------------------------------------------
# Blok geometri yardimcilari
# ----------------------------------------------------------------------

def blok_bas_xy(blok):
    w = satir_kelimeleri(blok[0])
    return (w.get("X", 0.0), w.get("Y", 0.0))


def _blok_son_xy(blok, varsayilan):
    x, y = varsayilan
    for s in blok:
        w = satir_kelimeleri(s)
        if "X" in w:
            x = w["X"]
        if "Y" in w:
            y = w["Y"]
    return (x, y)


def blok_bbox(blok):
    xs, ys = [], []
    for s in blok:
        w = satir_kelimeleri(s)
        if "X" in w:
            xs.append(w["X"])
        if "Y" in w:
            ys.append(w["Y"])
    if not xs or not ys:
        bx, by = blok_bas_xy(blok)
        return (bx, by, bx, by)
    return (min(xs), min(ys), max(xs), max(ys))


def toplam_bosta_yol(bloklar):
    """Bloklar arasi (kesim disi) XY tasima mesafesi toplami."""
    toplam, konum = 0.0, None
    for blok in bloklar:
        bas = blok_bas_xy(blok)
        if konum is not None:
            toplam += math.hypot(bas[0] - konum[0], bas[1] - konum[1])
        konum = _blok_son_xy(blok, bas)
    return toplam


# ----------------------------------------------------------------------
# Siralama stratejileri
# ----------------------------------------------------------------------

def _x_araliklari_cakisiyor_mu(b1, b2, x_tol):
    x1min, _, x1max, _ = b1
    x2min, _, x2max, _ = b2
    return (x1min - x_tol) <= x2max and (x2min - x_tol) <= x1max


def sol_alt_sag_ust_sirala(bloklar):
    """VARSAYILAN siralama: malzemenin destegi her zaman korunacak sekilde
    SOL-ALTTAN SAG-USTE ilerler. Once Y (asagidan yukari), esitlikte X
    (soldan saga) kucukten buyuge. Boylece kesim her zaman henuz kesilmemis
    (destekli) malzemeye dogru ilerler."""
    # Y'yi bantlara yuvarlayarak ayni "satir"daki parcalarin soldan saga
    # gelmesini garanti et (kucuk Y farklari siralamayi bozmasin).
    ys = [blok_bas_xy(b)[1] for b in bloklar]
    aralik = (max(ys) - min(ys)) if ys else 0.0
    bant = max(aralik * 0.04, 1e-9)

    def anahtar(b):
        x, y = blok_bas_xy(b)
        return (round(y / bant), x, y)

    return sorted(bloklar, key=anahtar)


def engel_farkindalikli_sirala(bloklar):
    """Engel-farkindalikli siralama (istege bagli). Bir parcanin X araligiyla
    cakisan ve ondan daha YUKARIDA duran parcalar once islenir (uzerine
    uzanmayi onler). Esitlikte SOL-ALTTAN SAG-USTE egilimi korunur."""
    bboxlar = [blok_bbox(b) for b in bloklar]
    tum_x = [v for box in bboxlar for v in (box[0], box[2])]
    genel_x = (max(tum_x) - min(tum_x)) if tum_x else 0.0
    x_tol = genel_x * _X_CAKISMA_TOLERANSI

    n = len(bloklar)
    engelleyici = [0] * n
    for i in range(n):
        bi = bboxlar[i]
        for j in range(n):
            if i == j:
                continue
            bj = bboxlar[j]
            if _x_araliklari_cakisiyor_mu(bi, bj, x_tol) and bj[1] > bi[3] - x_tol:
                engelleyici[i] += 1

    idx = list(range(n))

    def anahtar(i):
        x, y = blok_bas_xy(bloklar[i])
        return (engelleyici[i], y, x)

    idx.sort(key=anahtar)
    return [bloklar[i] for i in idx]


def serpantin_sirala(bloklar):
    """Y bantlarina ayirip bant icinde X yonunu sirayla degistirir (zigzag).
    Bosta tasimayi azaltir; yine sol-alttan baslar."""
    sirali_y = sorted(bloklar, key=lambda b: blok_bas_xy(b)[1])
    ys = [blok_bas_xy(b)[1] for b in sirali_y]
    aralik = (max(ys) - min(ys)) if ys else 0.0
    tol = max(aralik * 0.05, 1e-9)

    bantlar, mevcut, son_y = [], [], None
    for b in sirali_y:
        y = blok_bas_xy(b)[1]
        if son_y is not None and (y - son_y) > tol and mevcut:
            bantlar.append(mevcut)
            mevcut = []
        mevcut.append(b)
        son_y = y
    if mevcut:
        bantlar.append(mevcut)

    sonuc = []
    for n, bant in enumerate(bantlar):
        bant.sort(key=lambda b: blok_bas_xy(b)[0], reverse=(n % 2 == 1))
        sonuc.extend(bant)
    return sonuc


def _retract_ile_bitiyor(blok):
    for s in reversed(blok):
        w = satir_kelimeleri(s)
        if not w:
            continue
        return w.get("G") == 0.0 and "Z" in w and "X" not in w and "Y" not in w
    return False


# ----------------------------------------------------------------------
# Program modeli
# ----------------------------------------------------------------------

class GCodeProgram:
    """Bir G-Code dosyasini header + kesim bloklari + (sabit_son) + footer
    olarak ayristirir. `bloklar` listesinin sirasi degistirilerek yeniden
    siralama yapilir; satir icerikleri asla degismez."""

    def __init__(self, yol):
        self.yol = yol
        with open(yol, "r", encoding="utf-8", errors="replace") as f:
            self.satirlar = f.read().splitlines()
        self.guvenli = not g91_var_mi(self.satirlar)
        self.header = []
        self.bloklar = []
        self.footer = []
        self.sabit_son = None     # Z-retract ile bitmeyen son blok (sonda sabit)
        self.uyarilar = []
        if self.guvenli:
            self._ayristir()

    def _ayristir(self):
        satirlar = self.satirlar
        bas_idx = [i for i, s in enumerate(satirlar) if _blok_basi_mi(s)]
        if not bas_idx:
            self.uyarilar.append(
                "X-Y iceren G0 hizli hareket bulunamadi; blok tespiti yapilamadi.")
            return

        self.header = satirlar[:bas_idx[0]]
        bloklar = []
        for n, bi in enumerate(bas_idx):
            son = bas_idx[n + 1] if n + 1 < len(bas_idx) else len(satirlar)
            bloklar.append(satirlar[bi:son])

        # Program-sonu satirlarini footer'a tasi (M5/M30/% ve bos satirlar).
        footer = []
        son_blok = bloklar[-1]
        while son_blok:
            s = son_blok[-1]
            if _BITIS_RE.search(s) or not s.strip():
                footer.insert(0, son_blok.pop())
            else:
                break
        bloklar[-1] = son_blok
        self.footer = footer

        # Z-retract ile bitmeyen son blok ortaya tasinirsa kesim derinliginde
        # yatay hizli hareket olur -> bu blok en sonda sabitlenir.
        if bloklar and not _retract_ile_bitiyor(bloklar[-1]):
            self.sabit_son = bloklar.pop()
            self.uyarilar.append(
                "Son blok Z geri cekme ile bitmedigi icin konumu korundu "
                "(en sonda sabitlendi).")

        self.bloklar = bloklar

    # -- siralama ------------------------------------------------------
    def auto_sirala(self, serpantin=False, engel=False):
        """Varsayilan: sol-alt -> sag-ust. serpantin=zigzag, engel=engel
        farkindalikli (golge) siralama."""
        if serpantin:
            self.bloklar = serpantin_sirala(self.bloklar)
        elif engel:
            self.bloklar = engel_farkindalikli_sirala(self.bloklar)
        else:
            self.bloklar = sol_alt_sag_ust_sirala(self.bloklar)

    def sirali_bloklar(self):
        return self.bloklar + ([self.sabit_son] if self.sabit_son else [])

    def bosta_yol(self):
        return toplam_bosta_yol(self.sirali_bloklar())

    def ozet(self):
        """Etkilesimli arayuz / onizleme icin blok ozetleri."""
        out = []
        for n, blok in enumerate(self.bloklar, 1):
            bx, by = blok_bas_xy(blok)
            box = blok_bbox(blok)
            out.append({"sira": n, "x": bx, "y": by, "bbox": box,
                        "satir_sayisi": len(blok)})
        return out

    # -- cikti ---------------------------------------------------------
    def yaz(self, cikti=None):
        if cikti is None:
            kok, _ = os.path.splitext(self.yol)
            cikti = f"{kok}_reordered.tap"
        with open(cikti, "w", encoding="utf-8") as f:
            for s in self.header:
                f.write(s + "\n")
            for blok in self.sirali_bloklar():
                for s in blok:
                    f.write(s + "\n")
            for s in self.footer:
                f.write(s + "\n")
        return cikti


# ----------------------------------------------------------------------
# Tek seferlik (non-interaktif) yeniden siralama
# ----------------------------------------------------------------------

def yeniden_sirala_dosya(yol, serpantin=False, engel=False):
    prog = GCodeProgram(yol)
    if not prog.guvenli:
        print("[Adim 3] GUVENLIK IPTALI: Dosyada G91 (artimli mod) tespit "
              "edildi. Dosya DEGISTIRILMEDI.")
        return None
    if not prog.bloklar and not prog.sabit_son:
        for u in prog.uyarilar:
            print(f"[Adim 3] {u}")
        print("[Adim 3] Siralanacak kesim blogu bulunamadi. Dosya degistirilmedi.")
        return None

    for u in prog.uyarilar:
        print(f"[Adim 3] GUVENLIK: {u}")

    onceki = prog.bosta_yol()
    prog.auto_sirala(serpantin=serpantin, engel=engel)
    sonraki = prog.bosta_yol()
    cikti = prog.yaz()

    mod = ("serpantin (zigzag)" if serpantin
           else "engel-farkindalikli" if engel
           else "sol-alt -> sag-ust (destek korumali)")
    sirali = prog.sirali_bloklar()
    print(f"[Adim 3] {len(sirali)} kesim blogu '{mod}' duzeninde siralandi.")
    for n, blok in enumerate(sirali, 1):
        bx, by = blok_bas_xy(blok)
        print(f"  {n}. blok -> baslangic X{bx:.2f} Y{by:.2f}")
    if onceki > 0:
        fark = (1 - sonraki / onceki) * 100
        print(f"[Adim 3] Bosta tasima mesafesi: {onceki:.1f} -> {sonraki:.1f} "
              f"({fark:+.1f}%)")
    print(f"[Adim 3] Cikti dosyasi: {cikti}")
    return cikti
