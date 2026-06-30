#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test/demo amacli ornek DXF ve G-Code dosyalari uretir.

    python examples/ornek_uret.py

Uretilenler:
    examples/ornek_tabaka.dxf   - gereksiz node'lu, cesitli parcali tabaka
    examples/ornek_kesim.tap    - dagitik kesim bloklu G-Code
"""

import os
import ezdxf

BURASI = os.path.dirname(os.path.abspath(__file__))


def kare_collinear(x, y, kenar, ara_nokta=2):
    """Her kenarinda fazladan es-dogrultulu node'lar olan kapali kare."""
    pts = []
    kose = [(x, y), (x + kenar, y), (x + kenar, y + kenar), (x, y + kenar)]
    for i in range(4):
        a = kose[i]
        b = kose[(i + 1) % 4]
        pts.append((a[0], a[1], 0, 0, 0))
        for k in range(1, ara_nokta + 1):
            t = k / (ara_nokta + 1)
            pts.append((a[0] + (b[0] - a[0]) * t,
                        a[1] + (b[1] - a[1]) * t, 0, 0, 0))
    return pts


def dxf_uret(yol):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # 1) Normal parca (gereksiz node'larla) - sol alt
    msp.add_lwpolyline(kare_collinear(10, 10, 40, ara_nokta=3),
                       format="xyseb", dxfattribs={"closed": True})

    # 2) Baska normal parca - sag ust
    msp.add_lwpolyline(kare_collinear(120, 120, 30, ara_nokta=2),
                       format="xyseb", dxfattribs={"closed": True})

    # 3) Dikey serit (uzun-ince) - ortada
    msp.add_lwpolyline(kare_collinear(70, 20, 8, ara_nokta=1)[:0] +
                       [(70, 20, 0, 0, 0), (78, 20, 0, 0, 0),
                        (78, 120, 0, 0, 0), (70, 120, 0, 0, 0)],
                       format="xyseb", dxfattribs={"closed": True})

    # 4) Cember (es-geometrik polyline'a cevrilecek)
    msp.add_circle((150, 40), radius=15)

    # 5) Buyuk (riskli) parca
    msp.add_lwpolyline(kare_collinear(10, 80, 70, ara_nokta=2),
                       format="xyseb", dxfattribs={"closed": True})

    doc.saveas(yol)
    print(f"Uretildi: {yol}")


GCODE = """\
G21
G90
G0 X150 Y150
G1 Z-2
G1 X160 Y160
G0 Z5
G0 X12 Y12
G1 Z-2
G1 X40 Y40
G0 Z5
G0 X12 Y150
G1 Z-2
G1 X40 Y170
G0 Z5
G0 X150 Y12
G1 Z-2
G1 X170 Y40
G0 Z5
G0 X80 Y80
G1 Z-2
G1 X100 Y100
G0 Z5
M30
"""


def gcode_uret(yol):
    with open(yol, "w") as f:
        f.write(GCODE)
    print(f"Uretildi: {yol}")


if __name__ == "__main__":
    dxf_uret(os.path.join(BURASI, "ornek_tabaka.dxf"))
    gcode_uret(os.path.join(BURASI, "ornek_kesim.tap"))
