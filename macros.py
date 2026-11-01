#!/usr/bin/env python3
"""Макросы G604: разбор и сборка.

Формат (проверено на дампе живой мыши):
  шаг = 6 байт: [операция][модификаторы][HID-код клавиши][0x40][пауза, 2 байта]
    операция 0x43 — нажать, 0x44 — отпустить
    модификаторы: 0x01 ctrl, 0x02 shift, 0x04 alt, 0x08 cmd
    пауза — в миллисекундах, старший байт вперёд
  последний шаг макроса может быть без хвоста «0x40 + пауза» (3 байта)
  макрос заканчивается байтом 0xFF
  кнопка ссылается на макрос записью [0x00][0x06][0x00][смещение в секторе 6]
"""
from __future__ import annotations

PRESS = 0x43
RELEASE = 0x44
END = 0xFF
MARK = 0x40
MODS = {"ctrl": 0x01, "shift": 0x02, "alt": 0x04, "cmd": 0x08}


def mods_names(mask: int) -> str:
    return "+".join(n for n, m in MODS.items() if mask & m)


def parse(sec6: bytes, offset: int) -> tuple[list[dict], int]:
    """Читает макрос. Возвращает (шаги, позиция после 0xFF)."""
    steps: list[dict] = []
    i = offset
    while i < len(sec6) and sec6[i] != END:
        op, mods, key = sec6[i], sec6[i + 1], sec6[i + 2]
        if i + 3 < len(sec6) and sec6[i + 3] == MARK and i + 5 < len(sec6):
            delay = (sec6[i + 4] << 8) | sec6[i + 5]
            i += 6
        else:
            delay = 0
            i += 3
        steps.append({"op": op, "mods": mods, "key": key, "delay": delay})
    return steps, min(i + 1, len(sec6))


def describe(steps: list[dict], key_names: dict[int, str]) -> str:
    held = 0
    out = []
    mod_bit = {0xE0: 0x01, 0xE1: 0x02, 0xE2: 0x04, 0xE3: 0x08,
               0xE4: 0x01, 0xE5: 0x02, 0xE6: 0x04, 0xE7: 0x08}
    for s in steps:
        bit = mod_bit.get(s["key"])
        if bit is not None:  # это шаг нажатия/отпускания самого модификатора
            if s["op"] == PRESS:
                held |= bit
            else:
                held &= ~bit
            continue
        if s["op"] != PRESS:
            continue
        mods = mods_names(s["mods"] | held)
        key = key_names.get(s["key"], f"0x{s['key']:02x}")
        combo = f"{mods}+{key}" if mods else key
        out.append(f"{combo}({s['delay']}мс)" if s["delay"] else combo)
    return " → ".join(out) or "(пустой макрос)"


def build(combo_list: list[dict]) -> bytes:
    """Собирает макрос из списка комбинаций: [{'mods':int,'key':int,'delay':int}, …]."""
    out = bytearray()
    for c in combo_list:
        mods, key, delay = c.get("mods", 0), c["key"], c.get("delay", 50)
        out += bytes([PRESS, mods, key, MARK, (delay >> 8) & 0xFF, delay & 0xFF])
        out += bytes([RELEASE, mods, key, MARK, (delay >> 8) & 0xFF, delay & 0xFF])
    out.append(END)
    return bytes(out)


def used_end(sec6: bytes, profile_entries: list[bytes], parse_fn) -> int:
    """Конец занятой области: максимальный конец макросов, на которые ссылается профиль."""
    end = 0
    for e in profile_entries:
        if len(e) == 4 and e[0] == 0x00 and e[1] == 0x06:
            _, e_end = parse_fn(sec6, e[3])
            end = max(end, e_end)
    return end
