#!/usr/bin/env python3
"""Читалка памяти G604: печатает профили и назначения кнопок из дампа.

Формат (проверен на G604, profile_format_id=3):
  Профиль занимает сектор, у него: заголовок (16 байт), таблица кнопок,
  имя профиля в UTF-16LE.
  Таблица: 2 слоя × 16 кнопок × 4 байта. Слой 1 — обычный, слой 2 — G-Shift.
  Запись кнопки: [вид][подвид][параметр][значение]
"""
import base64
import json
import sys

MODS = {0x01: "ctrl", 0x02: "shift", 0x04: "alt", 0x08: "cmd"}

# HID usage -> читаемое имя (0x04..0x2c — буквы/цифры по порядку клавиатуры)
HID_LETTERS = ("a b c d e f g h i j k l m n o p q r s t u v w x y z "
               "1 2 3 4 5 6 7 8 9 0").split()
HID_NAMES = {0x28: "Enter", 0x29: "Esc", 0x2a: "Backspace", 0x2b: "Tab",
             0x2c: "Space", 0x2d: "-", 0x2e: "=", 0x2f: "[", 0x30: "]",
             0x31: "\\", 0x33: ";", 0x34: "'", 0x35: "`", 0x36: ",", 0x37: ".",
             0x38: "/", 0x39: "CapsLock", 0x4f: "→", 0x50: "←", 0x51: "↓", 0x52: "↑"}
HID_NAMES.update({0x04 + i: n for i, n in enumerate(HID_LETTERS)})
for i in range(12):  # F1..F12
    HID_NAMES.setdefault(0x3a + i, f"F{i + 1}")

BUTTON_BITS = {0x01: "ЛКМ", 0x02: "ПКМ", 0x04: "СКМ", 0x08: "Назад", 0x10: "Вперёд",
               0x20: "Кнопка 6", 0x40: "Кнопка 7"}

SPECIAL = {
    0x00: "— пусто —",
    0x01: "CPI/DPI переключение",
    0x02: "Смена профиля",
    0x03: "DPI вверх",
    0x04: "DPI вниз",
    0x07: "не назначено (по умолчанию)",
    0x0a: "G-Shift",
    0x0b: "системное действие",
    0x10: "частота опроса",
    0x11: "частота опроса",
}

BUTTON_ORDER = ["G1 ЛКМ", "G2 ПКМ", "G3 СКМ", "G4", "G5", "G6", "G7", "G8", "G9",
                "G10", "G11", "G12", "G13", "Колесо ↑↓", "Наклон колеса", "резерв"]


def decode_entry(b: bytes) -> str:
    kind, sub, p, v = b[0], b[1], b[2], b[3]
    if kind == 0xFF:
        return "— пусто —"
    if kind == 0x80 and sub == 0x01:
        return f"кнопка мыши: {BUTTON_BITS.get(v, hex(v))}"
    if kind == 0x80 and sub == 0x02:
        mods = "+".join(n for m, n in MODS.items() if p & m) or "-"
        key = HID_NAMES.get(v, f"usage {v:#04x}")
        return f"клавиша {mods}+{key}" if mods != "-" else f"клавиша {key}"
    if kind == 0x00 and sub == 0x06:
        return f"макрос (сектор 6, смещение {v:#04x})"
    if kind == 0x90:
        return f"служебное: {SPECIAL.get(sub, hex(sub))}"
    return f"неизвестно: {b.hex(' ')}"


def profile_name(sec: bytes) -> str:
    raw = sec[0xa1:0xe1]
    try:
        name = raw.decode("utf-16-le", errors="ignore").split("\x00")[0].strip()
    except Exception:
        name = ""
    return name or "(без имени)"


def main(path: str):
    d = json.load(open(path))
    sectors = {int(k): base64.b64decode(v) for k, v in d["sectors"].items()}
    print(f"Дамп: {path} | устройство: {d.get('device', '?')} | секторов: {d.get('sector_count')}")

    for s in sorted(sectors):
        sec = sectors[s]
        if s == 0 or not any(sec):
            continue
        table = sec[0x20:0xa0]
        if len(table) < 128:
            print(f"\n=== сектор {s}: не профиль (данные вне таблицы) ===")
            continue
        print(f"\n=== сектор {s} | профиль «{profile_name(sec)}» ===")
        print(f"    заголовок: {sec[0:16].hex(' ')}")
        for layer, label in ((0, "слой 1"), (1, "G-Shift")):
            entries = [table[layer * 64 + i * 4: layer * 64 + i * 4 + 4] for i in range(16)]
            out = []
            for idx, e in enumerate(entries):
                act = decode_entry(e)
                if "не назначено" in act or "— пусто —" in act:
                    continue
                out.append(f"{BUTTON_ORDER[idx]:<14} {act}")
            if out:
                print(f"  {label}:")
                for line in out:
                    print("    " + line)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dump-20261031.json")
