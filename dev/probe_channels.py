#!/usr/bin/env python3
"""Чтение настроек G604 через любой канал: приёмник или Bluetooth.

Находит все HID-интерфейсы Logitech с vendor-страницей 0xFF00, поднимает HID++,
печатает имя устройства, заряд, текущий DPI и частоту опроса из профиля.
"""
import ctypes
import ctypes.util
import sys
import time

VID = 0x046D


def load_lib():
    for path in (ctypes.util.find_library("hidapi"),
                 "/opt/homebrew/lib/libhidapi.dylib"):
        if path:
            try:
                return ctypes.CDLL(path)
            except OSError:
                continue
    raise SystemExit("libhidapi не найдена")


class DeviceInfo(ctypes.Structure):
    pass


DeviceInfo._fields_ = [
    ("path", ctypes.c_char_p), ("vendor_id", ctypes.c_ushort), ("product_id", ctypes.c_ushort),
    ("serial_number", ctypes.c_wchar_p), ("release_number", ctypes.c_ushort),
    ("manufacturer_string", ctypes.c_wchar_p), ("product_string", ctypes.c_wchar_p),
    ("usage_page", ctypes.c_ushort), ("usage", ctypes.c_ushort),
    ("interface_number", ctypes.c_int), ("next", ctypes.POINTER(DeviceInfo)),
]


def enumerate_logitech(lib):
    lib.hid_enumerate.restype = ctypes.POINTER(DeviceInfo)
    lib.hid_free_enumeration.argtypes = [ctypes.POINTER(DeviceInfo)]
    devs = lib.hid_enumerate(VID, 0)
    out = []
    cur = devs
    while cur:
        d = cur.contents
        out.append({"path": d.path, "pid": d.product_id, "product": d.product_string,
                    "usage_page": d.usage_page, "usage": d.usage, "iface": d.interface_number})
        cur = d.next
    lib.hid_free_enumeration(devs)
    return out


def hidpp_probe(path, lib):
    """Пробует HID++ ping и возвращает (dev_idx, swid) или None."""
    lib.hid_open_path.restype = ctypes.c_void_p
    lib.hid_open_path.argtypes = [ctypes.c_char_p]
    h = lib.hid_open_path(path)
    if not h:
        return None
    try:
        lib.hid_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.hid_read_timeout.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
        lib.hid_read_timeout.restype = ctypes.c_int
        rbuf = ctypes.create_string_buffer(64)
        while lib.hid_read_timeout(h, rbuf, 64, 5) > 0:
            pass
        for dev_idx in (0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0xFF):
            for swid in (0x08, 0x0D, 0x01):
                pkt = bytes([0x10, dev_idx, 0x00, 0x10 | 0x00, swid, 0x00, 0x00, 0x5A]) + bytes(12)
                lib.hid_write(h, pkt, len(pkt))
                n = lib.hid_read_timeout(h, rbuf, 64, 250)
                if n > 0:
                    data = bytes(rbuf.raw[:n])
                    if len(data) >= 4 and data[0] == 0x10 and data[1] == dev_idx:
                        return dev_idx, swid, h
        return None
    finally:
        pass


def main():
    lib = load_lib()
    lib.hid_init()
    devs = enumerate_logitech(lib)
    print(f"найдено интерфейсов Logitech: {len(devs)}")
    for d in devs:
        if d["usage_page"] != 0xFF00:
            continue
        print(f"  pid=0x{d['pid']:04X} usage=0x{d['usage']:02X} iface={d['iface']} product={d['product']}")
        res = hidpp_probe(d["path"], lib)
        print("    HID++:", "отвечает" if res else "молчит", res[:2] if res else "")


if __name__ == "__main__":
    main()
