"""Проверка записи макроса в мышь (тем же кодом, что и в приложении)."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hidpp_g604 as hid, macros, g604_editor as g

pp = hid.Hidpp(); pp.open()
print("устройство:", pp.device_name(), "| заряд:", pp.battery())
s1 = bytearray(pp.read_sector(g.SECTOR, g.SECTOR_SIZE))
s6 = bytearray(pp.read_sector(g.SECTOR_MACROS, g.SECTOR_SIZE))
entries = [bytes(s1[g.BASE + i*4:g.BASE + i*4 + 4]) for i in range(16)]

combos = [{"mods": 0x0F, "key": g.KEYS["0"], "delay": 60}]
blob = g.build_macro(combos)
start = macros.used_end(s6, entries, macros.parse)
print(f"макрос {len(blob)} байт → размещаю с {start:#04x}")
s6[start:start+len(blob)] = blob
if start + len(blob) < g.SECTOR_SIZE:
    s6[start + len(blob)] = macros.END

IDX = 12  # G13
s1[g.BASE + IDX*4:g.BASE + IDX*4 + 4] = g.encode_entry("macro", offset=start)
pp.write_sector(g.SECTOR_MACROS, bytes(s6), g.SECTOR_SIZE)
pp.write_sector(g.SECTOR, bytes(s1), g.SECTOR_SIZE)

s1 = pp.read_sector(g.SECTOR, g.SECTOR_SIZE); s6 = pp.read_sector(g.SECTOR_MACROS, g.SECTOR_SIZE)
ent = g.decode_entry(bytes(s1[g.BASE + IDX*4:g.BASE + IDX*4 + 4]))
print("после записи:", g.entry_text(ent, s6))
steps, end = macros.parse(s6, ent["offset"])
print("шагов в макросе:", len(steps), "| описание:", macros.describe(steps, g.USAGE_TO_KEY))
pp.close()
