import ctypes

lib = ctypes.CDLL("/opt/homebrew/lib/libhidapi.dylib")


class DI(ctypes.Structure):
    pass


DI._fields_ = [("path", ctypes.c_char_p), ("vendor_id", ctypes.c_ushort), ("product_id", ctypes.c_ushort),
               ("serial_number", ctypes.c_wchar_p), ("release_number", ctypes.c_ushort),
               ("manufacturer_string", ctypes.c_wchar_p), ("product_string", ctypes.c_wchar_p),
               ("usage_page", ctypes.c_ushort), ("usage", ctypes.c_ushort),
               ("interface_number", ctypes.c_int), ("next", ctypes.POINTER(DI))]

lib.hid_init()
lib.hid_enumerate.restype = ctypes.POINTER(DI)
lib.hid_free_enumeration.argtypes = [ctypes.POINTER(DI)]
lib.hid_open_path.restype = ctypes.c_void_p
lib.hid_open_path.argtypes = [ctypes.c_char_p]
lib.hid_error.restype = ctypes.c_wchar_p
lib.hid_error.argtypes = [ctypes.c_void_p]

devs = lib.hid_enumerate(0x046D, 0)
cur = devs
opened = 0
while cur:
    d = cur.contents
    if d.product_id == 0xB024 and d.usage_page == 0xFF43:
        h = lib.hid_open_path(d.path)
        if h:
            opened += 1
            lib.hid_close(h)
            print("RESULT: opened")
        else:
            print("RESULT: failed:", lib.hid_error(None))
    cur = d.next
lib.hid_free_enumeration(devs)
if not opened:
    print("RESULT: not opened")
