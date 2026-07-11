#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gercek NFP (No-Fit Polygon) + Genetik Algoritma nesting
=======================================================
SVGnest/Deepnest yaklasiminin bir uygulamasi:

  * Parca-parca cakisma:  NFP = A ⊕ (-B)  (Minkowski toplami, pyclipper/Clipper).
    B'nin referans noktasi NFP'nin ICINDE degilse cakisma yoktur.
  * Parca-konteyner:  IFP (Inner-Fit Polygon) = P'nin C icinde kalabildigi
    referans konumlari (cerceve - Minkowski yontemi).
  * Yerlestirme:  feasible = IFP − ∪ NFP(yerlesmis_j, P);  bu bolgenin
    KOSELERI aday konumdur (temas eden sıkı yerlesim). En sol-alt kose secilir.
  * Sira/rotasyon:  GENETIK ALGORITMA (order crossover + mutasyon + elitizm)
    ile optimize edilir; uygunluk = en cok DOLU ALAN, en az tabaka.

Not: pyclipper gereklidir (pip install pyclipper). Yoksa bu motor devre disidir
ve raster motoruna donulur.
"""

import math
import random

try:
    import pyclipper
    _VAR = True
except ImportError:
    _VAR = False

SC = 1000.0        # Clipper tamsayi olcekleme (0.001 birim hassasiyet)


def kullanilabilir():
    return _VAR


# ----------------------------------------------------------------------
# Clipper yardimcilari
# ----------------------------------------------------------------------

def _to_c(poly):
    return [[int(round(x * SC)), int(round(y * SC))] for x, y in poly]


def _from_c(path):
    return [(x / SC, y / SC) for x, y in path]


def _alan(path):
    return abs(pyclipper.Area(path))


def _clip(subj, clips, ct):
    pc = pyclipper.Pyclipper()
    pc.AddPaths(subj, pyclipper.PT_SUBJECT, True)
    if clips:
        pc.AddPaths(clips, pyclipper.PT_CLIP, True)
    return pc.Execute(ct, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)


def _dondur(poly, aci):
    a = math.radians(aci)
    ca, sa = math.cos(a), math.sin(a)
    return [(x * ca - y * sa, x * sa + y * ca) for x, y in poly]


def _bbox(poly):
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _oteleme(path_c, dx, dy):
    return [[x + dx, y + dy] for x, y in path_c]


# ----------------------------------------------------------------------
# NFP ve IFP
# ----------------------------------------------------------------------

def _nfp(A_c, B_c):
    """Parca-parca NFP: A ⊕ (-B). En buyuk alanli dis dongu doner (clipper int)."""
    negB = [[-x, -y] for x, y in B_c]
    sol = pyclipper.MinkowskiSum(negB, A_c, True)
    if not sol:
        return None
    return max(sol, key=_alan)


def _ifp(C_c, P_c):
    """Inner-Fit (referans t bolgesi): P'nin C icinde kalmasi icin P'nin HER
    vertex'i C icinde olmali -> IFP = ∩_v (C − v).  Konveks konteyner+parcada
    KESIN; konkav konteynerde 'guvenli' alt kume (disari tasmaz). Konkav kenar
    durumlari icin secilen konum ayrica birebir dogrulanir (_icinde)."""
    res = [C_c]
    for vx, vy in P_c:
        trans = [[x - vx, y - vy] for x, y in C_c]
        res = _clip(res, [trans], pyclipper.CT_INTERSECTION)
        if not res:
            return []
    return res


# ----------------------------------------------------------------------
# Tek yerlestirme (bir sira+rotasyon icin)
# ----------------------------------------------------------------------

class _Motor:
    def __init__(self, parcalar, tabakalar, ayar):
        self.rotasyonlar = ayar.get("rotasyonlar") or [0]
        self.kerf = float(ayar.get("kerf", 0))
        self.bosluk = float(ayar.get("bosluk", 0))
        self.kenar = float(ayar.get("kenar", 0))
        self.aciklik = self.kerf + self.bosluk        # parca-parca
        # Parca tipleri (rotasyon+sisirme onbellekli)
        self.ptip = parcalar
        self.tabakalar = tabakalar
        self._rot_c = {}      # (pi, aci) -> clipper poly (sisirilmis, referans min-koseli)
        self._nfp_c = {}      # (pi,ai,pj,aj) -> nfp
        self._ifp_c = {}      # (ti,pi,ai) -> ifp
        self._tab_c = [_to_c(self._sisir_tabaka(t["poly"])) for t in tabakalar]

    def _sisir_tabaka(self, poly):
        # kenar boslugu: konteyneri iceri daralt (clipper offset)
        if self.kenar <= 0:
            return poly
        co = pyclipper.PyclipperOffset()
        co.AddPath(_to_c(poly), pyclipper.JT_MITER, pyclipper.ET_CLOSEDPOLYGON)
        sol = co.Execute(-self.kenar * SC)
        if not sol:
            return poly
        return _from_c(max(sol, key=_alan))

    def rot_c(self, pi, aci):
        k = (pi, aci)
        if k in self._rot_c:
            return self._rot_c[k]
        rp = _dondur(self.ptip[pi]["poly"], aci)
        # parca-parca aciklik: parcayi aciklik/2 sisir (clipper offset)
        c = _to_c(rp)
        if self.aciklik > 0:
            co = pyclipper.PyclipperOffset()
            co.AddPath(c, pyclipper.JT_MITER, pyclipper.ET_CLOSEDPOLYGON)
            sol = co.Execute(self.aciklik / 2.0 * SC)
            if sol:
                c = max(sol, key=_alan)
        self._rot_c[k] = c
        return c

    def nfp(self, pi, ai, pj, aj):
        k = (pi, ai, pj, aj)
        if k not in self._nfp_c:
            self._nfp_c[k] = _nfp(self.rot_c(pi, ai), self.rot_c(pj, aj))
        return self._nfp_c[k]

    def ifp(self, ti, pj, aj):
        k = (ti, pj, aj)
        if k not in self._ifp_c:
            self._ifp_c[k] = _ifp(self._tab_c[ti], self.rot_c(pj, aj))
        return self._ifp_c[k]

    def yerlestir(self, sira):
        """sira: [(pi, aci)...]. Bottom-left NFP yerlesim, coklu tabaka."""
        # her tabaka icin yerlesmis parcalar: [(pi, aci, tx, ty, world_poly_c)]
        tab_yer = [[] for _ in self.tabakalar]
        yer = []
        yok = {}
        for pi, aci in sira:
            kondu = False
            for ti in range(len(self.tabakalar)):
                t = self._konum_bul(ti, pi, aci, tab_yer[ti])
                if t is None:
                    continue
                tx, ty = t
                wc = _oteleme(self.rot_c(pi, aci), tx, ty)
                tab_yer[ti].append((pi, aci, tx, ty, wc))
                wp = _dondur(self.ptip[pi]["poly"], aci)
                yer.append({"tabaka": ti, "id": self.ptip[pi]["id"], "aci": aci,
                            "poly": [(x + tx / SC, y + ty / SC) for x, y in wp]})
                kondu = True
                break
            if not kondu:
                yok[self.ptip[pi]["id"]] = yok.get(self.ptip[pi]["id"], 0) + 1
        # doluluk
        doluluk = []
        for ti, t in enumerate(self.tabakalar):
            kap = _alan(self._tab_c[ti]) or 1
            dolu = sum(_alan(w[4]) for w in tab_yer[ti])
            doluluk.append(round(100.0 * dolu / kap, 1))
        dolu_alan = sum(_alan(w[4]) for tl in tab_yer for w in tl)
        tab_kul = sum(1 for tl in tab_yer if tl)
        skor = (dolu_alan, len(yer), -tab_kul)
        return {"yerlesim": yer, "doluluk": doluluk,
                "yerlesmeyen": [{"id": k, "adet": v} for k, v in yok.items()],
                "skor": skor}

    def _konum_bul(self, ti, pi, aci, yerlesmisler):
        ifp = self.ifp(ti, pi, aci)
        if not ifp:
            return None
        # feasible = IFP - union(NFP(yerlesmis, P) + t_yerlesmis)
        yasak = []
        for (qi, qa, qx, qy, _) in yerlesmisler:
            n = self.nfp(qi, qa, pi, aci)
            if n:
                yasak.append(_oteleme(n, qx, qy))
        feas = _clip(ifp, yasak, pyclipper.CT_DIFFERENCE) if yasak else ifp
        if not feas:
            return None
        # yerlesmislerin birlesimi (cakisma dogrulamasi icin)
        birlesim = None
        if yerlesmisler:
            birlesim = _clip([w[4] for w in yerlesmisler], [], pyclipper.CT_UNION)
        # aday koseler, sol-alt sirali; ilk BIREBIR gecerli olani sec:
        # (a) konteyner icinde  (b) yerlesmislerle cakismiyor.
        adaylar = sorted({(x, y) for path in feas for x, y in path},
                         key=lambda p: (p[1], p[0]))
        C_c = self._tab_c[ti]
        P_c = self.rot_c(pi, aci)
        for (x, y) in adaylar[:400]:
            wc = _oteleme(P_c, x, y)
            if not self._icinde(wc, C_c):
                continue
            if birlesim and self._cakisiyor(wc, birlesim):
                continue
            return (x, y)
        return None

    def _icinde(self, poly_c, C_c):
        """poly_c tamamen C_c icinde mi? (fark bos ise evet)"""
        return not _clip([poly_c], [C_c], pyclipper.CT_DIFFERENCE)

    def _cakisiyor(self, poly_c, birlesim_paths):
        """poly_c yerlesmislerle (birlesim) cakisiyor mu?"""
        return bool(_clip([poly_c], birlesim_paths, pyclipper.CT_INTERSECTION))


# ----------------------------------------------------------------------
# Genetik algoritma
# ----------------------------------------------------------------------

def _ga_nest(parcalar, tabakalar, ayar):
    motor = _Motor(parcalar, tabakalar, ayar)
    rot = motor.rotasyonlar

    # gen: parca ornekleri listesi (pi tekrarli, adet kadar) + her ornek icin aci
    ornekler = []
    for pi, p in enumerate(parcalar):
        for _ in range(int(p.get("adet", 1))):
            ornekler.append(pi)
    n = len(ornekler)
    if n == 0:
        return {"yerlesim": [], "doluluk": [0] * len(tabakalar), "yerlesmeyen": []}

    pop = int(ayar.get("populasyon", 12))
    nesil = int(ayar.get("nesil", 8))
    rnd = random.Random(int(ayar.get("tohum", 42)))

    # alan azalan baslangic bireyi (iyi tohum)
    def alan(pi):
        x0, y0, x1, y1 = _bbox(parcalar[pi]["poly"])
        return (x1 - x0) * (y1 - y0)
    taban = sorted(range(n), key=lambda i: alan(ornekler[i]), reverse=True)

    def rastgele_aci():
        return rot[rnd.randrange(len(rot))]

    def birey_uret(sirali=False):
        idx = list(taban) if sirali else rnd.sample(range(n), n)
        aci = [rastgele_aci() for _ in range(n)]
        return {"idx": idx, "aci": aci}

    def uygula(birey):
        sira = [(ornekler[i], birey["aci"][i]) for i in birey["idx"]]
        return motor.yerlestir(sira)

    # baslangic populasyonu
    bireyler = [birey_uret(sirali=True)] + [birey_uret() for _ in range(pop - 1)]
    degerli = []
    for b in bireyler:
        r = uygula(b)
        degerli.append((b, r))
    degerli.sort(key=lambda br: br[1]["skor"], reverse=True)
    en_iyi = degerli[0]

    def oks(p1, p2):
        # order crossover (idx uzerinde); aci ebeveynden karisik
        a, bnd = sorted(rnd.sample(range(n), 2))
        cocuk = [None] * n
        cocuk[a:bnd] = p1["idx"][a:bnd]
        kalan = [g for g in p2["idx"] if g not in cocuk]
        j = 0
        for i in range(n):
            if cocuk[i] is None:
                cocuk[i] = kalan[j]; j += 1
        aci = [p1["aci"][i] if rnd.random() < 0.5 else p2["aci"][i] for i in range(n)]
        return {"idx": cocuk, "aci": aci}

    def mutasyon(b):
        b = {"idx": list(b["idx"]), "aci": list(b["aci"])}
        if n >= 2 and rnd.random() < 0.6:
            i, j = rnd.sample(range(n), 2)
            b["idx"][i], b["idx"][j] = b["idx"][j], b["idx"][i]
        if rnd.random() < 0.6 and len(rot) > 1:
            b["aci"][rnd.randrange(n)] = rastgele_aci()
        return b

    elit = max(1, pop // 5)
    for _ in range(nesil - 1):
        yeni = [degerli[k][0] for k in range(elit)]     # elitizm
        while len(yeni) < pop:
            p1 = _turnuva(degerli, rnd)
            p2 = _turnuva(degerli, rnd)
            yeni.append(mutasyon(oks(p1, p2)))
        degerli = []
        for b in yeni:
            degerli.append((b, uygula(b)))
        degerli.sort(key=lambda br: br[1]["skor"], reverse=True)
        if degerli[0][1]["skor"] > en_iyi[1]["skor"]:
            en_iyi = degerli[0]

    r = en_iyi[1]
    return {"yerlesim": r["yerlesim"], "doluluk": r["doluluk"],
            "yerlesmeyen": r["yerlesmeyen"]}


def _turnuva(degerli, rnd, k=3):
    aday = [degerli[rnd.randrange(len(degerli))] for _ in range(k)]
    aday.sort(key=lambda br: br[1]["skor"], reverse=True)
    return aday[0][0]


def nfp_nest(parcalar, tabakalar, ayar):
    """Gercek NFP + Genetik nesting. pyclipper yoksa None doner (cagiran raster'a
    doner)."""
    if not _VAR:
        return None
    sonuc = _ga_nest(parcalar, tabakalar, ayar)
    sonuc["hucre"] = 0
    sonuc["motor"] = "nfp"
    return sonuc
