#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web sunucusunun OTOMATIK BASLATMAYA uygunlugu.

Windows'ta oturum acilisinda kendiliginden calistigi icin iki davranis
kritik:
  * her acilista ikinci bir kopya ACILMAMALI,
  * port baska bir program tarafindan tutuluyorsa COKMEMELI.
"""

import json
import os
import socket
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cnc_assistant import webapp as W


def _bos_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _baslat(port):
    t = threading.Thread(target=lambda: W.calistir(port=port), daemon=True)
    t.start()
    for _ in range(60):                       # hazir olmasini bekle
        if W._bizim_mi("127.0.0.1", port, zaman=0.2):
            return t
        time.sleep(0.05)
    raise AssertionError(f"sunucu {port} portunda acilmadi")


def test_surum_ucu_kendi_ornegimizi_tanitir():
    port = _bos_port()
    _baslat(port)
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/surum", timeout=2) as y:
        assert json.loads(y.read().decode())["uygulama"] == W.SURUM_IZI


def test_ikinci_kopya_acilmaz():
    """Acilista tekrar tekrar calistirilsa bile tek sunucu kalir."""
    port = _bos_port()
    _baslat(port)
    for _ in range(3):
        assert W.calistir(port=port) == f"http://127.0.0.1:{port}"


def test_port_doluysa_yedege_gecer():
    """Portu BASKA bir program tutuyorsa cokmeden sonraki porta gecmeli."""
    port = _bos_port()
    tikac = socket.socket()
    tikac.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tikac.bind(("127.0.0.1", port))
    tikac.listen(1)
    try:
        threading.Thread(target=lambda: W.calistir(port=port), daemon=True).start()
        for _ in range(60):
            if W._bizim_mi("127.0.0.1", port + 1, zaman=0.2):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("yedek porta gecilmedi")
    finally:
        tikac.close()


def test_bizim_mi_yabanci_sunucuyu_ayirt_eder():
    """Portta baska bir servis varsa 'bizim' sayilmamali."""
    port = _bos_port()
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    try:
        assert W._bizim_mi("127.0.0.1", port, zaman=0.3) is False
    finally:
        s.close()


def test_hicbir_port_bos_degilse_anlasilir_hata():
    port = _bos_port()
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    try:
        try:
            W.calistir(port=port, port_ara=1)
        except SystemExit as e:
            assert "port" in str(e).lower()
        else:
            raise AssertionError("hata bekleniyordu")
    finally:
        s.close()
