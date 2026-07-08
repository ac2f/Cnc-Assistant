#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cnc_assistant
=============
CNC tabaka kesimi icin DXF baslangic-noktasi optimizasyonu, gereksiz node
temizligi, riskli parca uyarisi ve G-Code blok siralama (otomatik +
etkilesimli) araci.
"""

__version__ = "1.1.0"

from . import (geometry, dxf_processor, gcode, preview, interactive,  # noqa: F401
               project, cli)

__all__ = ["geometry", "dxf_processor", "gcode", "preview", "interactive",
           "project", "cli", "__version__"]
