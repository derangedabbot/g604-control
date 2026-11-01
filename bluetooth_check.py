"""Определение того, подключена ли G604 по Bluetooth.

По Bluetooth мышь видна как 0x046D:0xB024, но её служебный канал (usage page 0xFF43)
macOS не даёт открыть даже root — поэтому настройка по этому каналу невозможна.
Задача модуля — только распознать этот случай и сказать об этом пользователю.
"""
from __future__ import annotations

import ctypes


class _DeviceInfo(ctypes.Structure):
    pass


_DeviceInfo._fields_ = [
    ("path", ctypes.c_char_p), ("vendor_id", ctypes.c_ushort), ("product_id", ctypes.c_ushort),
    ("serial_number", ctypes.c_wchar_p), ("release_number", ctypes.c_ushort),
    ("manufacturer_string", ctypes.c_wchar_p), ("product_string", ctypes.c_wchar_p),
    ("usage_page", ctypes.c_ushort), ("usage", ctypes.c_ushort),
    ("interface_number", ctypes.c_int), ("next", ctypes.POINTER(_DeviceInfo)),
]

BT_PRODUCT_ID = 0xB024      # G604 LIGHTSPEED по Bluetooth
VENDOR_ID = 0x046D


def bluetooth_mouse_present(load_lib) -> bool:
    """True, если мышь видна по Bluetooth (load_lib — функция загрузки hidapi)."""
    try:
        lib = load_lib()
        lib.hid_init()
        lib.hid_enumerate.restype = ctypes.POINTER(_DeviceInfo)
        lib.hid_free_enumeration.argtypes = [ctypes.POINTER(_DeviceInfo)]
        devs = lib.hid_enumerate(VENDOR_ID, 0)
        found = False
        cur = devs
        while cur:
            d = cur.contents
            if d.product_id == BT_PRODUCT_ID:
                found = True
                break
            cur = d.next
        lib.hid_free_enumeration(devs)
        return found
    except Exception:  # noqa: BLE001
        return False
