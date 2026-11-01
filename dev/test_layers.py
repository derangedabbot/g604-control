"""Автотест: изменения не теряются при переключении слоя и профиля.

Работает на подставном устройстве (реальная мышь не нужна).
"""
import base64
import json
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import g604_editor as g  # noqa: E402

DUMP = json.load(open(ROOT / "backups" / "dump-20261031.json"))
SECTORS = {int(k): bytearray(base64.b64decode(v)) for k, v in DUMP["sectors"].items()}


class FakeHidpp:
    written = {}

    @staticmethod
    def _load_hidapi():
        raise RuntimeError("hidapi не нужна в тесте")

    def open(self, prefer_usage=None):
        return None

    def close(self):
        pass

    def device_name(self):
        return "G604 (тест)"

    def battery(self):
        return 55

    def read_sector(self, sector, size):
        return bytes(SECTORS.get(sector, bytearray(b"\xff" * size)))

    def write_sector(self, sector, data, size):
        SECTORS[sector] = bytearray(data)
        FakeHidpp.written[sector] = bytes(data)

    def get_feature_index(self, feature):
        return 0x0C

    def _request(self, fi, fn, params=b"", timeout=1.0, **kw):
        if fn == 0x2:      # get DPI
            return bytes([0, 0x0C, 0x1C]) + bytes(13)
        return bytes(16)


g.hid.Hidpp = FakeHidpp
g.hid._dump_connected = lambda pp: {"sectors": {}, "sector_size": 255, "device_name": "тест"}
g.messagebox.askokcancel = lambda *a, **k: True
g.messagebox.showinfo = lambda *a, **k: None
g.messagebox.showerror = lambda *a, **k: None

root = tk.Tk()
root.withdraw()
app = g.App(root)
print("прочитано кнопок:", len(app.entries))

# 1) изменение в обычном слое, профиль 1
app.tree.selection_set("5")
app.var_kind.set("key")
app.var_key.set("c")
app.mod_vars["cmd"].set(True)
app.stage()
print("после первой правки, в очереди:", len(app.pending))

# 2) переключаем слой — правка не должна пропасть
app.var_layer.set("G-Shift")
app.refresh_layer()
print("после переключения слоя, в очереди:", len(app.pending))

# 3) вторая правка в G-Shift
app.tree.selection_set("9")
app.var_kind.set("key")
app.var_key.set("x")
app.mod_vars["cmd"].set(True)
app.stage()
print("после второй правки, в очереди:", len(app.pending))

# 4) переключаем профиль (reload) — правки тоже должны сохраниться
app.var_profile.set("2")
app.reload()
print("после переключения профиля, в очереди:", len(app.pending))

# 5) запись
app.write()
print("записаны сектора:", sorted(FakeHidpp.written))

# 6) проверка содержимого
s1 = SECTORS[1]
p_s1 = g.OFF_BUTTONS + 5 * 4
p_s2 = g.OFF_ALT_BUTTONS + 9 * 4
e1 = g.decode_entry(bytes(s1[p_s1:p_s1 + 4]))
e2 = g.decode_entry(bytes(s1[p_s2:p_s2 + 4]))
print("G6 обычный слой:", g.entry_text(e1))
print("Служебная 2 слой G-Shift:", g.entry_text(e2))

ok = (e1.get("type") == "key" and e1.get("usage") == g.KEYS["c"]
      and e2.get("type") == "key" and e2.get("usage") == g.KEYS["x"])
print("ИТОГ:", "всё сохранилось" if ok else "ОШИБКА: правки потерялись")
root.destroy()
sys.exit(0 if ok else 1)
