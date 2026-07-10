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
        return plt
    except ImportError:
        return None


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


def _kontur_ciz(ax, varliklar, riskli_handlelar, baslangic_etiketi=True):
    for v in varliklar:
        pts = v["kontur"] if "kontur" in v else _komut_flatten(v["d"])
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        riskli = v["handle"] in riskli_handlelar
        ax.plot(xs, ys, color="#d62728" if riskli else "#1f77b4",
                lw=1.6 if riskli else 0.9)
        if baslangic_etiketi and v["baslangic"] is not None:
            ax.plot(v["baslangic"][0], v["baslangic"][1], "o",
                    color="#2ca02c", ms=5, zorder=5)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.25)


def baslangic_oncesi_sonrasi(oncesi_varliklar, sonrasi_varliklar,
                             riskli_handlelar, png_yol):
    """Iki panelli ONCESI / SONRASI baslangic noktasi gorseli."""
    plt = _matplotlib()
    if plt is None:
        print("[Onizleme] matplotlib kurulu degil, PNG uretilmedi "
              "(istege bagli: pip install matplotlib)")
        return False

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
    _kontur_ciz(ax1, oncesi_varliklar, set())
    ax1.set_title("ONCESI - orijinal baslangic noktalari")
    _kontur_ciz(ax2, sonrasi_varliklar, riskli_handlelar)
    ax2.set_title("SONRASI - optimize baslangic (yesil) + riskli parca (kirmizi)")

    ax2.plot([], [], "o", color="#2ca02c", label="Yeni kesim baslangici")
    ax2.plot([], [], color="#d62728", label="Riskli parca (hold-down onerilir)")
    ax2.legend(loc="upper right", fontsize=8)

    fig.suptitle("Baslangic Noktasi Optimizasyonu (kontrol amaclidir)",
                 fontsize=13)
    fig.tight_layout()
    fig.savefig(png_yol, dpi=140)
    plt.close(fig)
    print(f"[Onizleme] Oncesi/Sonrasi gorseli: {png_yol}")
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
    fig.savefig(png_yol, dpi=140)
    plt.close(fig)
    return True
