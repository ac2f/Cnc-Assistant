#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CNC Tabaka Kesim Optimizasyon Araci
===================================
Bu dosya geriye donuk uyumluluk icin korunan ince bir giris noktasidir.
Tum islevsellik `cnc_assistant` paketine tasinmistir.

Kullanim:
    python main.py tabaka.dxf
    python main.py kesim.tap
    python main.py kesim.tap -e          # etkilesimli (canli) siralama
    python main.py --help                # tum secenekler

Daha fazlasi icin README.md dosyasina bakin.
"""

from cnc_assistant.cli import main

if __name__ == "__main__":
    main()
