#!/usr/bin/env python3
"""Меняет одно назначение кнопки в дампе памяти G604.

Пример: set_entry.py dump.json out.json --sector 1 --layer 1 --index 12 --hex 80020f26
"""
import argparse
import base64
import json

BASE = 0x20          # начало таблицы кнопок в секторе профиля
LAYER_SIZE = 64      # 16 кнопок × 4 байта


def main():
    p = argparse.ArgumentParser()
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--sector", type=int, required=True, help="номер сектора профиля (обычно 1)")
    p.add_argument("--layer", type=int, default=1, choices=[1, 2], help="1 = обычный, 2 = G-Shift")
    p.add_argument("--index", type=int, required=True, help="0..15 — номер кнопки в таблице")
    p.add_argument("--hex", required=True, help="4 байта, например 80020f26")
    a = p.parse_args()

    data = json.load(open(a.src))
    raw = bytearray(base64.b64decode(data["sectors"][str(a.sector)]))
    new = bytes.fromhex(a.hex.replace(" ", ""))
    if len(new) != 4:
        raise SystemExit("нужно ровно 4 байта")

    off = BASE + (a.layer - 1) * LAYER_SIZE + a.index * 4
    old = raw[off:off + 4]
    raw[off:off + 4] = new
    data["sectors"][str(a.sector)] = base64.b64encode(bytes(raw)).decode()
    json.dump(data, open(a.dst, "w"), indent=2)

    print(f"сектор {a.sector}, {'G-Shift' if a.layer == 2 else 'слой 1'}, кнопка #{a.index}")
    print(f"  смещение {off:#04x}: {old.hex(' ')} -> {new.hex(' ')}")
    print(f"  записано в {a.dst}")


if __name__ == "__main__":
    main()
