#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Onizleme gorselleri (matplotlib - istege bagli)
==============================================
  * baslangic_oncesi_sonrasi(...) : DXF baslangic noktalarini ONCESI/SONRASI
    olarak yan yana iki panelde gosterir.
  * gcode_sira_onizleme(...)       : G-Code blok siralamasini, her bloga sira
    numarasi yazip aralarinda tasima oklari cizerek gosterir. Etkilesimli
    duzenlemede her guncellemede yeniden uretilebilir.

matplotlib kurulu degilse fonksiyonlar sessizce False doner (zorunlu degil).
"""


def _matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        # Kullanicinin ortaminda koyu (dark) bir stil/matplotlibrc tanimli olsa
        # bile cikti nötr kalsin: varsayilan stil + hicbir dolgu dikdortgeni
        # gomulmesin (arka plan SEFFAF kaydedilir, bkz. _kaydet).
        plt.style.use("default")
        plt.rcParams.update({
            "figure.facecolor": "none",
            "axes.facecolor": "none",
            "savefig.facecolor": "none",
            "savefig.edgecolor": "none",
            "savefig.transparent": True,
            # PDF/PS'te yazilari GERCEK gomulu TrueType (Type42) olarak yaz ->
            # Corel/CAD'de "font sec" sorusu cikmaz, yazi convertsiz kalmaz.
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            # SVG'de yazilari düz metin degil YOL (path/egri) olarak goml.
            "svg.fonttype": "path",
        })
        return plt
    except ImportError:
        return None


def _eksen_sadelestir(ax):
    """Eksen cercevesini/tik/etiketlerini gizler -> disari aktarilan vektorde
    (Corel/CAD) silinmesi gereken fazladan cizgi/dikdortgen objesi kalmaz.
    Yalnizca parca konturlari, baslangic isaretleri (ve varsa izgara) kalir."""
    ax.set_facecolor("none")
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(left=False, right=False, top=False, bottom=False,
                   labelleft=False, labelbottom=False)


def _kaydet(fig, yol, dpi=140):
    """Figuru SEFFAF arka planla kaydeder (PDF/PNG/SVG). Arka plana dolgu
    dikdortgeni (beyaz/siyah) gomulmez -> Corel/CAD'e aktarimda silinecek
    arka plan sekli olmaz; yazilar da gomulu/egri olur (font sorusu cikmaz)."""
    fig.patch.set_alpha(0.0)
    for ax in fig.get_axes():
        ax.patch.set_alpha(0.0)
    fig.savefig(yol, dpi=dpi, transparent=True)


def _komut_flatten(d, seg=18):
    """SVG yol komutlarini (M/L/Q/C/Z) matplotlib icin nokta dizisine acar."""
    pts = []
    cur = None
    for c in d:
        k = c[0]
        if k in ("M", "L"):
            cur = (c[1], c[2]); pts.append(cur)
        elif k == "Q":
            c1 = (c[1], c[2]); e = (c[3], c[4]); p0 = cur or c1
            for i in range(1, seg + 1):
                t = i / seg; u = 1 - t
                pts.append((u * u * p0[0] + 2 * u * t * c1[0] + t * t * e[0],
                            u * u * p0[1] + 2 * u * t * c1[1] + t * t * e[1]))
            cur = e
        elif k == "C":
            c1 = (c[1], c[2]); c2 = (c[3], c[4]); e = (c[5], c[6]); p0 = cur or c1
            for i in range(1, seg + 1):
                t = i / seg; u = 1 - t
                pts.append((u**3 * p0[0] + 3 * u * u * t * c1[0]
                            + 3 * u * t * t * c2[0] + t**3 * e[0],
                            u**3 * p0[1] + 3 * u * u * t * c1[1]
                            + 3 * u * t * t * c2[1] + t**3 * e[1]))
            cur = e
    return pts


def _komut_path(d):
    """SVG komut listesini (M/L/Q/C/Z) matplotlib Path'e cevirir (GERCEK
    bezier egrileri -> PDF/vektor ciktida sonsuz yaklastirmada purüzsuz)."""
    from matplotlib.path import Path
    verts, codes = [], []
    for c in d:
        k = c[0]
        if k == "M":
            verts.append((c[1], c[2])); codes.append(Path.MOVETO)
        elif k == "L":
            verts.append((c[1], c[2])); codes.append(Path.LINETO)
        elif k == "Q":
            verts += [(c[1], c[2]), (c[3], c[4])]
            codes += [Path.CURVE3, Path.CURVE3]
        elif k == "C":
            verts += [(c[1], c[2]), (c[3], c[4]), (c[5], c[6])]
            codes += [Path.CURVE4, Path.CURVE4, Path.CURVE4]
        elif k == "Z":
            verts.append((0, 0)); codes.append(Path.CLOSEPOLY)
    return Path(verts, codes) if verts else None


# Onizleme gorsel ayarlari (kullanici arayuzunden gelir; hepsi kalicidir).
VARSAYILAN_STIL = {
    "cizgi_kalinlik": 0.9,      # vektor cizgi genisligi
    "riskli_kalinlik": 1.6,     # riskli vektor cizgi genisligi
    "vektor_renk": "#1f77b4",   # normal vektor rengi
    "riskli_renk": "#d62728",   # riskli vektor rengi
    "bas_renk": "#2ca02c",      # baslangic noktasi rengi
    "bas_boyut": 5.0,           # baslangic noktasi boyutu (marker)
    "numara": False,            # parca numaralari goster
    "numara_boyut": 6.0,        # numara font boyutu
    "izgara": True,             # arka plan izgarasi
}


def _stil(stil):
    s = dict(VARSAYILAN_STIL)
    if stil:
        s.update({k: v for k, v in stil.items() if v is not None})
    return s


def _numaralandir(varliklar):
    """Parcalari okuma sirasina (ust->alt, sol->sag) gore numaralandirir.
    Doner: {id(varlik) -> numara}. Numaralar ONCESI/SONRASI'da tutarli olsun
    diye merkez konumundan uretilir (baslangic degil)."""
    merkez = []
    for v in varliklar:
        pts = _komut_flatten(v["d"]) if "d" in v else v.get("kontur") or []
        if not pts:
            merkez.append((v, 0, 0)); continue
        xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
        merkez.append((v, (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
    if not merkez:
        return {}
    ys_all = [m[2] for m in merkez]
    span = (max(ys_all) - min(ys_all)) or 1.0
    satir = span / 24.0 or 1.0
    merkez.sort(key=lambda m: (-round(m[2] / satir), m[1]))
    return {id(v): i + 1 for i, (v, _cx, _cy) in enumerate(merkez)}


def _kontur_ciz(ax, varliklar, riskli_handlelar, stil,
                baslangic_etiketi=True, numaralar=None):
    from matplotlib.patches import PathPatch
    for v in varliklar:
        riskli = v["handle"] in riskli_handlelar
        renk = stil["riskli_renk"] if riskli else stil["vektor_renk"]
        lw = stil["riskli_kalinlik"] if riskli else stil["cizgi_kalinlik"]
        if "d" in v:
            p = _komut_path(v["d"])
            if p is not None:
                ax.add_patch(PathPatch(p, fill=False, edgecolor=renk, lw=lw))
        else:
            pts = v.get("kontur") or []
            if pts:
                ax.plot([q[0] for q in pts], [q[1] for q in pts],
                        color=renk, lw=lw)
        if baslangic_etiketi and v["baslangic"] is not None:
            ax.plot(v["baslangic"][0], v["baslangic"][1], "o",
                    color=stil["bas_renk"], ms=stil["bas_boyut"], zorder=5)
        if numaralar is not None and id(v) in numaralar:
            pts = _komut_flatten(v["d"]) if "d" in v else v.get("kontur") or []
            if pts:
                xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
                ax.annotate(str(numaralar[id(v)]),
                            ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2),
                            fontsize=stil["numara_boyut"], color="#1f3d99",
                            ha="center", va="center", weight="bold", zorder=6)
    # PathPatch'ler otomatik olceklenmez -> sinirlari komut koordlarindan kur
    xs, ys = [], []
    for v in varliklar:
        for p in (_komut_flatten(v["d"]) if "d" in v else v.get("kontur") or []):
            xs.append(p[0]); ys.append(p[1])
    if xs:
        pad = max((max(xs) - min(xs)), (max(ys) - min(ys))) * 0.03 + 1
        ax.set_xlim(min(xs) - pad, max(xs) + pad)
        ax.set_ylim(min(ys) - pad, max(ys) + pad)
    ax.set_aspect("equal")
    ax.grid(bool(stil["izgara"]), alpha=0.25)
    _eksen_sadelestir(ax)


def onizleme_uret(oncesi_varliklar, sonrasi_varliklar, riskli_handlelar,
                  cikti_yol, paneller="birlikte", stil=None, baslik=True):
    """Baslangic ONCESI/SONRASI onizlemesini uretir. Cikti formati dosya
    uzantisindan belirlenir (.pdf / .png / .svg).

    paneller: "birlikte" (yan yana ikisi), "oncesi" (yalniz oncesi),
              "sonrasi" (yalniz sonrasi).
    stil    : gorsel ayarlar (bkz. VARSAYILAN_STIL); None -> varsayilan.
    Doner: basari (True/False)."""
    plt = _matplotlib()
    if plt is None:
        print("[Onizleme] matplotlib kurulu degil (pip install matplotlib).")
        return False
    s = _stil(stil)
    numaralar = _numaralandir(sonrasi_varliklar) if s["numara"] else None

    if paneller == "birlikte":
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
        _kontur_ciz(ax1, oncesi_varliklar, set(), s, numaralar=numaralar)
        ax1.set_title("ONCESI - orijinal baslangic noktalari")
        _kontur_ciz(ax2, sonrasi_varliklar, riskli_handlelar, s,
                    numaralar=numaralar)
        ax2.set_title("SONRASI - optimize baslangic + riskli parca")
        ax2.plot([], [], "o", color=s["bas_renk"], label="Yeni kesim baslangici")
        ax2.plot([], [], color=s["riskli_renk"], label="Riskli parca (hold-down)")
        ax2.legend(loc="upper right", fontsize=8)
        if baslik:
            fig.suptitle("Baslangic Noktasi Optimizasyonu", fontsize=13)
    else:
        oncesi = (paneller == "oncesi")
        fig, ax = plt.subplots(figsize=(12, 9))
        _kontur_ciz(ax, oncesi_varliklar if oncesi else sonrasi_varliklar,
                    set() if oncesi else riskli_handlelar, s,
                    numaralar=numaralar)
        ax.set_title("ONCESI - orijinal baslangic" if oncesi
                     else "SONRASI - optimize baslangic")
        if not oncesi:
            ax.plot([], [], "o", color=s["bas_renk"], label="Yeni baslangic")
            ax.plot([], [], color=s["riskli_renk"], label="Riskli parca")
            ax.legend(loc="upper right", fontsize=8)

    fig.tight_layout()
    _kaydet(fig, cikti_yol)
    plt.close(fig)
    print(f"[Onizleme] {paneller} -> {cikti_yol}")
    return True


def baslangic_oncesi_sonrasi(oncesi_varliklar, sonrasi_varliklar,
                             riskli_handlelar, png_yol, stil=None):
    """Geriye donuk uyumlu sarmalayici: iki panelli ONCESI/SONRASI gorseli."""
    return onizleme_uret(oncesi_varliklar, sonrasi_varliklar, riskli_handlelar,
                         png_yol, paneller="birlikte", stil=stil)


def vektor_pdf(varliklar, yol, baslik="Nesting", vurgu_handlelar=None):
    """Tek panelli GERCEK VEKTOREL PDF/PNG (komut formundan). Nesting sonucu
    gibi tek gorunumler icin."""
    plt = _matplotlib()
    if plt is None:
        return False
    fig, ax = plt.subplots(figsize=(12, 9))
    _kontur_ciz(ax, varliklar, vurgu_handlelar or set(), _stil(None),
                baslangic_etiketi=False)
    ax.set_title(baslik)
    fig.tight_layout()
    _kaydet(fig, yol)
    plt.close(fig)
    return True


def gcode_sira_onizleme(ozet, png_yol, baslik="G-Code Kesim Sirasi"):
    """Blok siralamasini numaralandirip tasima yolu (oklar) ile gosterir.
    `ozet`: GCodeProgram.ozet() ciktisi (sira, x, y, bbox)."""
    plt = _matplotlib()
    if plt is None:
        return False
    if not ozet:
        return False

    fig, ax = plt.subplots(figsize=(11, 9))

    # Blok bbox'lari (hafif dikdortgen) ve sira numaralari
    xs = [b["x"] for b in ozet]
    ys = [b["y"] for b in ozet]
    for b in ozet:
        x0, y0, x1, y1 = b["bbox"]
        ax.add_patch(plt.Rectangle((x0, y0), max(x1 - x0, 1e-6),
                                   max(y1 - y0, 1e-6),
                                   fill=False, edgecolor="#bbbbbb", lw=0.7))
        ax.text(b["x"], b["y"], str(b["sira"]),
                fontsize=8, color="#d62728", ha="center", va="center",
                bbox=dict(boxstyle="circle,pad=0.15", fc="white",
                          ec="#d62728", lw=0.8))

    # Tasima yolu oklari (sira boyunca)
    for i in range(len(ozet) - 1):
        ax.annotate("", xy=(xs[i + 1], ys[i + 1]), xytext=(xs[i], ys[i]),
                    arrowprops=dict(arrowstyle="->", color="#1f77b4",
                                    lw=0.8, alpha=0.7))

    if xs:
        ax.plot(xs[0], ys[0], "s", color="#2ca02c", ms=10,
                label="Baslangic (1. blok)")
        ax.plot(xs[-1], ys[-1], "^", color="#9467bd", ms=10,
                label="Bitis (son blok)")
        ax.legend(loc="upper left", fontsize=8)

    ax.set_aspect("equal")
    ax.grid(True, alpha=0.25)
    ax.set_title(baslik)
    fig.tight_layout()
    _kaydet(fig, png_yol)
    plt.close(fig)
    return True
