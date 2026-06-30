#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cnc_assistant
=============
CNC tabaka kesimi icin DXF baslangic-noktasi optimizasyonu, gereksiz node
temizligi, riskli parca uyarisi ve G-Code blok siralama (otomatik +
etkilesimli) araci.
"""

__version__ = "1.0.0"

from . import geometry, dxf_processor, gcode, preview, interactive, cli  # noqa: F401

__all__ = ["geometry", "dxf_processor", "gcode", "preview", "interactive",
           "cli", "__version__"]
