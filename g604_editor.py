#!/usr/bin/env python3
"""G604 Control — замена Logitech G HUB для мыши G604.

Возможности:
  • профили 1–5, оба слоя (обычный и G-Shift);
  • назначения кнопок: клавиша, кнопка мыши, макрос, «не назначено»;
  • макросы: чтение и создание (последовательность комбинаций с паузами);
  • пять уровней DPI, DPI-shift, активный уровень, частота опроса;
  • текущий DPI читается и ставится напрямую у мыши;
  • запись в память мыши с автоматическим бэкапом и проверкой чтением;
  • сохранение и восстановление полного дампа;
  • никакой сети: ни обновлений, ни аккаунтов, ни телеметрии.

Формат профиля (сверено с libratbag, проверено на живой мыши):
  0 — частота опроса (1000/Гц), 1 — активный уровень DPI, 2 — уровень DPI-shift,
  3..12 — пять уровней DPI (2 байта, little-endian),
  32..95 — кнопки 16×4 (слой 1), 96..159 — кнопки 16×4 (G-Shift), 160 — имя профиля.
  Запись кнопки: [вид][подвид][параметр][значение]; макросы — сектор 6.
"""
from __future__ import annotations

import base64
import json
import sys
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hidpp_g604 as hid
import macros
from bluetooth_check import bluetooth_mouse_present

SECTOR_SIZE = 255
SECTOR_MACROS = 6
PROFILE_COUNT = 5

OFF_REPORT = 0
OFF_DEFAULT_DPI = 1
OFF_SWITCHED_DPI = 2
OFF_DPI = 3
OFF_BUTTONS = 0x20
OFF_ALT_BUTTONS = 0x60

RATES = {1: 1000, 2: 500, 4: 250, 8: 125}
RATE_TO_BYTE = {v: k for k, v in RATES.items()}

MODS = {"ctrl": 0x01, "shift": 0x02, "alt": 0x04, "cmd": 0x08}
MOD_USAGE = {"ctrl": 0xE0, "shift": 0xE1, "alt": 0xE2, "cmd": 0xE3}

CONTROLS = [
    "G1 левая", "G2 правая", "G3 колесо", "G4", "G5", "G6", "G7", "G8",
    "G9", "Кнопка DPI 1", "Кнопка DPI 2", "Наклон влево", "Наклон вправо",
    "Служебная 1", "Служебная 2", "резерв",
]

KEYS: dict[str, int] = {}
for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
    KEYS[ch] = 0x04 + i
for i, ch in enumerate("1234567890"):
    KEYS[ch] = 0x1E + i
for i in range(12):
    KEYS[f"F{i + 1}"] = 0x3A + i
KEYS.update({"Enter": 0x28, "Esc": 0x29, "Backspace": 0x2A, "Tab": 0x2B, "Space": 0x2C,
             "-": 0x2D, "=": 0x2E, "[": 0x2F, "]": 0x30, "\\": 0x31, ";": 0x33, "'": 0x34,
             "`": 0x35, ",": 0x36, ".": 0x37, "/": 0x38,
             "←": 0x50, "→": 0x4F, "↑": 0x52, "↓": 0x51,
             "Home": 0x4A, "End": 0x4D, "PageUp": 0x4B, "PageDown": 0x4E, "Delete": 0x4C})
USAGE_TO_KEY = {v: k for k, v in KEYS.items()}

MOUSE_BITS = {"ЛКМ": 0x01, "ПКМ": 0x02, "СКМ": 0x04, "Назад": 0x08, "Вперёд": 0x10}
BIT_TO_MOUSE = {v: k for k, v in MOUSE_BITS.items()}

SPECIALS = {0x00: "пусто", 0x01: "переключение DPI", 0x02: "смена профиля (не работает на G604)",
            0x03: "DPI вверх", 0x04: "DPI вниз", 0x07: "не назначено", 0x0A: "неизвестный код 0A",
            0x0B: "G-Shift (второй слой)", 0x10: "частота опроса (не работает на G604)",
            0x11: "частота опроса (не работает на G604)"}


SPECIAL_OPTIONS = {
    "не назначено": 0x07,
    "DPI вниз": 0x04,
    "DPI вверх": 0x03,
    "переключение DPI": 0x01,
    "G-Shift (зажать = второй слой)": 0x0B,
}
CODE_TO_SPECIAL = {v: k for k, v in SPECIAL_OPTIONS.items()}


# ---------------------------------------------------------------- байты
def decode_entry(b: bytes) -> dict:
    kind, sub, p, v = b[0], b[1], b[2], b[3]
    if kind == 0xFF:
        return {"type": "empty"}
    if kind == 0x80 and sub == 0x01:
        return {"type": "mouse", "mask": v}
    if kind == 0x80 and sub == 0x02:
        return {"type": "key", "mods": p, "usage": v}
    if kind == 0x00 and sub == 0x06:
        return {"type": "macro", "offset": v}
    if kind == 0x90:
        return {"type": "special", "code": sub}
    return {"type": "unknown", "raw": b.hex(" ")}


def entry_text(e: dict, sec6: bytes | None = None) -> str:
    t = e["type"]
    if t == "mouse":
        return f"кнопка мыши: {BIT_TO_MOUSE.get(e['mask'], hex(e['mask']))}"
    if t == "key":
        mods = "+".join(n for n, m in MODS.items() if e["mods"] & m)
        key = USAGE_TO_KEY.get(e["usage"], f"0x{e['usage']:02x}")
        return f"клавиша {mods}+{key}" if mods else f"клавиша {key}"
    if t == "macro":
        if sec6 is None:
            return f"макрос (смещение {e['offset']:#04x})"
        steps, _ = macros.parse(sec6, e["offset"])
        return "макрос: " + macros.describe(steps, USAGE_TO_KEY)
    if t == "special":
        return f"служебное: {SPECIALS.get(e['code'], hex(e['code']))}"
    if t == "empty":
        return "— пусто —"
    return f"неизвестно ({e['raw']})"


def encode_entry(kind: str, mods: int = 0, usage: int = 0, mask: int = 0, offset: int = 0,
                 code: int = 0) -> bytes:
    if kind == "key":
        return bytes([0x80, 0x02, mods & 0xFF, usage & 0xFF])
    if kind == "mouse":
        return bytes([0x80, 0x01, 0x00, mask & 0xFF])
    if kind == "macro":
        return bytes([0x00, 0x06, 0x00, offset & 0xFF])
    if kind == "special":
        return bytes([0x90, code & 0xFF, 0x00, 0x00])
    if kind == "none":
        return bytes([0x90, 0x07, 0x00, 0x00])
    raise ValueError(kind)


def decode_header(sector: bytes) -> dict:
    dpi = [sector[OFF_DPI + i * 2] | (sector[OFF_DPI + i * 2 + 1] << 8) for i in range(5)]
    return {"rate_byte": sector[OFF_REPORT],
            "hz": RATES.get(sector[OFF_REPORT], 0),
            "default": sector[OFF_DEFAULT_DPI],
            "switched": sector[OFF_SWITCHED_DPI],
            "dpi": dpi}


def encode_header(sector: bytearray, hz: int, default_idx: int, switched_idx: int,
                  dpi: list[int]) -> None:
    sector[OFF_REPORT] = RATE_TO_BYTE.get(hz, 1)
    sector[OFF_DEFAULT_DPI] = max(0, min(4, default_idx))
    sector[OFF_SWITCHED_DPI] = max(0, min(4, switched_idx))
    for i, value in enumerate(dpi[:5]):
        v = max(100, min(16000, int(value)))
        sector[OFF_DPI + i * 2] = v & 0xFF
        sector[OFF_DPI + i * 2 + 1] = (v >> 8) & 0xFF


def apply_profile_dpi(pp, sector: bytes) -> int | None:
    """После записи в память мышь сбрасывает DPI на первый уровень.
    Возвращаем текущий DPI к активному уровню профиля."""
    try:
        header = decode_header(sector)
        value = header["dpi"][header["default"]]
        if not value:
            return None
        feature = pp.get_feature_index(0x2201)
        pp._request(feature, 0x3, bytes([0, (value >> 8) & 0xFF, value & 0xFF]), timeout=1.5)
        return value
    except Exception:  # noqa: BLE001
        return None


def build_macro(combos: list[dict]) -> bytes:
    out = bytearray()
    for c in combos:
        mods, key, delay = c.get("mods", 0), c["key"], c.get("delay", 50)
        held = 0
        for name, bit in MODS.items():
            if mods & bit:
                held |= bit
                out += bytes([macros.PRESS, held, MOD_USAGE[name], macros.MARK,
                              (delay >> 8) & 0xFF, delay & 0xFF])
        out += bytes([macros.PRESS, mods, key, macros.MARK, (delay >> 8) & 0xFF, delay & 0xFF])
        out += bytes([macros.RELEASE, mods, key, macros.MARK, (delay >> 8) & 0xFF, delay & 0xFF])
        for name, bit in reversed(list(MODS.items())):
            if mods & bit:
                out += bytes([macros.RELEASE, held, MOD_USAGE[name], macros.MARK,
                              (delay >> 8) & 0xFF, delay & 0xFF])
                held &= ~bit
    out.append(macros.END)
    return bytes(out)


def resource_path(name: str) -> Path:
    """Путь к файлу ресурса: рядом со скриптом или внутри собранного .app."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent
    return base / name


# ---------------------------------------------------------------- диалог макроса
class MacroDialog(tk.Toplevel):
    """Редактор макроса. Заменяет прежнюю простую версию (см. выше)."""

    def __init__(self, master, combos: list[dict]):
        super().__init__(master)
        self.title("Макрос для кнопки")
        self.geometry("680x560")
        self.minsize(640, 520)
        self.result: list[dict] | None = None
        self.combos = [dict(c) for c in combos]

        ttk.Label(self, wraplength=640, foreground="#555",
                  text="Макрос — последовательность нажатий. Мышь выполнит их по порядку, "
                       "когда вы нажмёте кнопку, к которой он привязан.").pack(anchor="w", padx=14, pady=(12, 8))

        self.tree = ttk.Treeview(self, columns=("n", "step", "pause"), show="headings", height=8)
        for cid, title, width in (("n", "№", 46), ("step", "комбинация", 380),
                                  ("pause", "пауза после, мс", 150)):
            self.tree.heading(cid, text=title)
            self.tree.column(cid, width=width, anchor="w", stretch=(cid == "step"))
        self.tree.pack(fill="both", expand=True, padx=14)
        self.tree.bind("<<TreeviewSelect>>", self._on_pick)

        edit = ttk.LabelFrame(self, text="Шаг", padding=10)
        edit.pack(fill="x", padx=14, pady=(10, 0))
        row = ttk.Frame(edit)
        row.pack(fill="x")
        ttk.Label(row, text="Клавиша:").pack(side="left")
        self.var_key = tk.StringVar(value="c")
        ttk.Combobox(row, textvariable=self.var_key, values=sorted(KEYS), width=10,
                     state="readonly").pack(side="left", padx=(6, 14))
        self.mod_vars = {}
        for name in ("ctrl", "shift", "alt", "cmd"):
            v = tk.BooleanVar(value=False)
            self.mod_vars[name] = v
            ttk.Checkbutton(row, text=name, variable=v).pack(side="left", padx=(0, 6))
        row2 = ttk.Frame(edit)
        row2.pack(fill="x", pady=(8, 0))
        ttk.Label(row2, text="пауза после нажатия, мс:").pack(side="left")
        self.var_delay = tk.StringVar(value="50")
        ttk.Spinbox(row2, from_=0, to=5000, increment=10, textvariable=self.var_delay,
                    width=6).pack(side="left", padx=6)
        ttk.Button(row2, text="Добавить такой шаг", command=self.add).pack(side="left", padx=12)
        ttk.Button(row2, text="Заменить выбранный", command=self.replace).pack(side="left")

        prev = ttk.Frame(self)
        prev.pack(fill="x", padx=14, pady=(10, 0))
        ttk.Label(prev, text="Что получится:").pack(side="left")
        self.lbl_preview = ttk.Label(prev, text="", font=("Helvetica", 12, "bold"))
        self.lbl_preview.pack(side="left", padx=8)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=14, pady=12)
        ttk.Button(btns, text="Удалить", command=self.remove).pack(side="left")
        ttk.Button(btns, text="Выше", command=lambda: self.move(-1)).pack(side="left", padx=6)
        ttk.Button(btns, text="Ниже", command=lambda: self.move(1)).pack(side="left")
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="Сохранить в кнопку", command=self.ok).pack(side="right", padx=6)

        ttk.Label(self, wraplength=640, foreground="#777",
                  text="Пауза — сколько миллисекунд ждать после нажатия, прежде чем выполнять "
                       "следующий шаг. Для обычных действий хватает 50 мс.").pack(anchor="w", padx=14, pady=(0, 10))

        self._refresh()

    @staticmethod
    def _combo_text(c: dict) -> str:
        mods = "+".join(n for n, m in MODS.items() if c["mods"] & m)
        return f"{mods}+{c['key']}" if mods else str(c["key"])

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        for i, c in enumerate(self.combos):
            self.tree.insert("", "end", iid=str(i), values=(i + 1, self._combo_text(c), c["delay"]))
        self.lbl_preview.config(text=" → ".join(self._combo_text(c) for c in self.combos) or "(пока пусто)")

    def _on_pick(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            return
        c = self.combos[int(sel[0])]
        self.var_key.set(c["key"])
        for name, var in self.mod_vars.items():
            var.set(bool(c["mods"] & MODS[name]))
        self.var_delay.set(str(c["delay"]))

    def _fields(self) -> dict:
        mods = sum(m for n, m in MODS.items() if self.mod_vars[n].get())
        try:
            delay = int(self.var_delay.get())
        except ValueError:
            delay = 50
        return {"mods": mods, "key": self.var_key.get(), "delay": max(0, delay)}

    def add(self):
        self.combos.append(self._fields())
        self._refresh()
        self.tree.selection_set(str(len(self.combos) - 1))

    def replace(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Макрос", "Сначала выберите шаг в таблице.", parent=self)
            return
        self.combos[int(sel[0])] = self._fields()
        self._refresh()
        self.tree.selection_set(sel[0])

    def remove(self):
        for i in reversed(self.tree.selection()):
            del self.combos[int(i)]
        self._refresh()

    def move(self, delta):
        sel = self.tree.selection()
        if not sel:
            return
        i = int(sel[0])
        j = i + delta
        if 0 <= j < len(self.combos):
            self.combos[i], self.combos[j] = self.combos[j], self.combos[i]
            self._refresh()
            self.tree.selection_set(str(j))

    def ok(self):
        self.result = self.combos
        self.destroy()


# ---------------------------------------------------------------- приложение
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.pp: hid.Hidpp | None = None
        self.sector = bytearray(b"\xff" * SECTOR_SIZE)
        self.sector6 = bytearray(b"\xff" * SECTOR_SIZE)
        self.pending: dict[tuple[int, int], dict] = {}
        self.entries: list[dict] = []
        self.current_macro: list[dict] = []
        self.battery = None
        self.header_dirty = False

        root.title("G604 Control")
        root.geometry("1000x690")
        root.minsize(940, 640)

        self._build()
        self.connect()
        self.reload()

    # ---------- интерфейс
    def _build(self):
        top = ttk.Frame(self.root, padding=(10, 8))
        top.pack(fill="x")
        self.lbl_dev = ttk.Label(top, text="Устройство: —", font=("Helvetica", 13, "bold"))
        self.lbl_dev.pack(side="left")
        ttk.Button(top, text="Схема кнопок", command=self.show_diagram).pack(side="left", padx=12)
        ttk.Button(top, text="Перечитать", command=self.reload).pack(side="right", padx=4)
        ttk.Button(top, text="Сохранить дамп…", command=self.save_dump).pack(side="right", padx=4)
        ttk.Button(top, text="Восстановить из дампа…", command=self.restore_dump).pack(side="right", padx=4)

        nav = ttk.Frame(self.root, padding=(10, 0))
        nav.pack(fill="x")
        ttk.Label(nav, text="Профиль:").pack(side="left")
        self.var_profile = tk.StringVar(value="1")
        cmb = ttk.Combobox(nav, textvariable=self.var_profile, width=3, state="readonly",
                           values=[str(i) for i in range(1, PROFILE_COUNT + 1)])
        cmb.pack(side="left", padx=(4, 12))
        cmb.bind("<<ComboboxSelected>>", lambda _e: self.reload())
        ttk.Label(nav, text="Слой:").pack(side="left")
        self.var_layer = tk.StringVar(value="обычный")
        cmb2 = ttk.Combobox(nav, textvariable=self.var_layer, width=10, state="readonly",
                            values=["обычный", "G-Shift"])
        cmb2.pack(side="left", padx=4)
        cmb2.bind("<<ComboboxSelected>>", lambda _e: self.refresh_layer())
        ttk.Label(nav, text="   Текущий DPI:").pack(side="left")
        self.lbl_live_dpi = ttk.Label(nav, text="—", font=("Helvetica", 12, "bold"))
        self.lbl_live_dpi.pack(side="left", padx=4)
        self.var_live_dpi = tk.StringVar(value="")
        ttk.Entry(nav, textvariable=self.var_live_dpi, width=6).pack(side="left")
        ttk.Button(nav, text="Поставить", command=self.apply_live_dpi).pack(side="left", padx=4)

        dpi = ttk.LabelFrame(self.root, text="Уровни DPI и частота опроса (в памяти профиля)", padding=8)
        dpi.pack(fill="x", padx=10, pady=(8, 0))
        row1 = ttk.Frame(dpi)
        row1.pack(fill="x")
        self.dpi_vars = []
        for i in range(5):
            ttk.Label(row1, text=f"{i + 1}:").pack(side="left")
            v = tk.StringVar()
            self.dpi_vars.append(v)
            ttk.Entry(row1, textvariable=v, width=6).pack(side="left", padx=(2, 12))
        row2 = ttk.Frame(dpi)
        row2.pack(fill="x", pady=(8, 0))
        ttk.Label(row2, text="активный:").pack(side="left")
        self.var_default = tk.StringVar(value="1")
        ttk.Combobox(row2, textvariable=self.var_default, width=3, state="readonly",
                     values=[str(i) for i in range(1, 6)]).pack(side="left", padx=(2, 12))
        ttk.Label(row2, text="DPI-shift:").pack(side="left")
        self.var_switched = tk.StringVar(value="1")
        ttk.Combobox(row2, textvariable=self.var_switched, width=3, state="readonly",
                     values=[str(i) for i in range(1, 6)]).pack(side="left", padx=(2, 12))
        ttk.Label(row2, text="опрос:").pack(side="left")
        self.var_hz = tk.StringVar(value="1000")
        ttk.Combobox(row2, textvariable=self.var_hz, width=6, state="readonly",
                     values=["125", "250", "500", "1000"]).pack(side="left", padx=2)
        ttk.Button(row2, text="Применить", command=self.apply_header).pack(side="right")
        ttk.Label(dpi, foreground="#777",
                  text="При включении мыши (и после замены батарейки) она берёт уровень 1, "
                       "а не активный — держите в первом уровне рабочий DPI.").pack(anchor="w", pady=(6, 0))

        body = ttk.Frame(self.root, padding=(10, 8))
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(left, columns=("c", "a"), show="headings", height=13)
        self.tree.heading("c", text="Кнопка")
        self.tree.heading("a", text="Назначение в памяти мыши")
        self.tree.column("c", width=150, stretch=False)
        self.tree.column("a", width=380)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        right = ttk.LabelFrame(body, text="Назначить действие", padding=10)
        right.pack(side="left", fill="both", padx=(12, 0))
        self.sel_lbl = ttk.Label(right, text="Кнопка не выбрана", font=("Helvetica", 12, "bold"))
        self.sel_lbl.pack(anchor="w")

        self.var_kind = tk.StringVar(value="key")
        for val, txt in (("key", "Клавиша"), ("mouse", "Кнопка мыши"),
                         ("macro", "Макрос"), ("special", "Служебное"),
                         ("none", "Не назначено")):
            ttk.Radiobutton(right, text=txt, value=val, variable=self.var_kind,
                            command=self._sync_kind).pack(anchor="w", pady=1)

        self.frm_key = ttk.LabelFrame(right, text="клавиша", padding=8)
        mods_frame = ttk.Frame(self.frm_key)
        mods_frame.pack(fill="x")
        self.mod_vars = {}
        for name in ("ctrl", "shift", "alt", "cmd"):
            v = tk.BooleanVar(value=False)
            self.mod_vars[name] = v
            ttk.Checkbutton(mods_frame, text=name, variable=v).pack(side="left", padx=(0, 8))
        self.var_key = tk.StringVar(value="a")
        ttk.Combobox(self.frm_key, textvariable=self.var_key, values=sorted(KEYS),
                     state="readonly", width=16).pack(anchor="w", pady=(6, 0))

        self.frm_mouse = ttk.LabelFrame(right, text="кнопка мыши", padding=8)
        self.var_mouse = tk.StringVar(value="Назад")
        ttk.Combobox(self.frm_mouse, textvariable=self.var_mouse, values=list(MOUSE_BITS),
                     state="readonly", width=16).pack(anchor="w")

        self.frm_special = ttk.LabelFrame(right, text="служебное действие", padding=8)
        self.var_special = tk.StringVar(value="G-Shift")
        ttk.Combobox(self.frm_special, textvariable=self.var_special,
                     values=list(SPECIAL_OPTIONS), state="readonly", width=20).pack(anchor="w")
        ttk.Label(self.frm_special, text="G-Shift — это второй слой кнопок:\nпока кнопка зажата, боковые\nкнопки делают «сдвинутое» действие",
                  foreground="#777").pack(anchor="w", pady=(6, 0))

        self.frm_macro = ttk.LabelFrame(right, text="макрос", padding=8)
        self.lbl_macro = ttk.Label(self.frm_macro, text="не задан", wraplength=260)
        self.lbl_macro.pack(anchor="w")
        ttk.Button(self.frm_macro, text="Изменить макрос…",
                   command=self.edit_macro).pack(anchor="w", pady=(6, 0))

        ttk.Button(right, text="Запомнить для этой кнопки", command=self.stage).pack(fill="x", pady=(10, 4))
        ttk.Button(right, text="ЗАПИСАТЬ В МЫШЬ", command=self.write).pack(fill="x", pady=(6, 0))

        self.status = ttk.Label(self.root, text="", padding=(10, 6), foreground="#555")
        self.status.pack(fill="x")
        self._sync_kind()

    def _sync_kind(self):
        for w in (self.frm_key, self.frm_mouse, self.frm_macro, self.frm_special):
            w.pack_forget()
        k = self.var_kind.get()
        if k == "key":
            self.frm_key.pack(fill="x", pady=(6, 0))
        elif k == "mouse":
            self.frm_mouse.pack(fill="x", pady=(6, 0))
        elif k == "macro":
            self.frm_macro.pack(fill="x", pady=(6, 0))
        elif k == "special":
            self.frm_special.pack(fill="x", pady=(6, 0))

    def show_diagram(self):
        path = resource_path("diagram.png")
        win = tk.Toplevel(self.root)
        win.title("Схема кнопок G604")
        if path.exists():
            img = tk.PhotoImage(file=str(path))
            factor = max(1, round(img.width() / 980))
            if factor > 1:
                img = img.subsample(factor, factor)
            lbl = ttk.Label(win, image=img)
            lbl.image = img  # держим ссылку, иначе картинка пропадёт
            lbl.pack(padx=10, pady=10)
        else:
            ttk.Label(win, text=f"Не найден файл схемы:\n{path}").pack(padx=16, pady=16)
        ttk.Button(win, text="Закрыть", command=win.destroy).pack(pady=(0, 12))

    def say(self, text: str):
        self.status.config(text=text)
        self.root.update_idletasks()

    # ---------- DPI напрямую
    def _dpi_feature(self):
        return self.pp.get_feature_index(0x2201)

    def read_live_dpi(self) -> int | None:
        if not self.pp:
            return None
        try:
            r = self.pp._request(self._dpi_feature(), 0x2, bytes([0]), timeout=1.2)
            return (r[1] << 8) | r[2]
        except Exception:  # noqa: BLE001
            return None

    def apply_live_dpi(self):
        if not self.pp:
            messagebox.showerror("G604 Control", "Мышь не найдена.")
            return
        try:
            value = max(100, min(16000, int(self.var_live_dpi.get())))
        except ValueError:
            messagebox.showerror("G604 Control", "DPI должен быть числом.")
            return
        try:
            self.pp._request(self._dpi_feature(), 0x3,
                             bytes([0, (value >> 8) & 0xFF, value & 0xFF]), timeout=1.5)
            actual = self.read_live_dpi()
            self.lbl_live_dpi.config(text=str(actual))
            self.say(f"Текущий DPI: {actual}")
        except Exception as e:  # noqa: BLE001
            self.say(f"Не удалось поставить DPI: {e}")

    # ---------- устройство
    def connect(self):
        last = None
        bt_only = bluetooth_mouse_present(hid.Hidpp._load_hidapi)
        attempts = 1 if bt_only else 3
        for attempt in range(attempts):
            try:
                self.pp = hid.Hidpp()
                self.pp.open()
                name = self.pp.device_name()
                self.battery = self.pp.battery()
                self.lbl_dev.config(text=f"{name} | заряд {self.battery}%" if self.battery is not None else name)
                dpi = self.read_live_dpi()
                if dpi is not None:
                    self.lbl_live_dpi.config(text=str(dpi))
                    self.var_live_dpi.set(str(dpi))
                self.say("Мышь на связи.")
                return
            except Exception as e:  # noqa: BLE001
                last = e
                self.pp = None
                self.say(f"Подключение, попытка {attempt + 1} из 3…")
                self.root.update_idletasks()
                time.sleep(1.0)
        self.lbl_dev.config(text="Устройство: не найдено")
        if bluetooth_mouse_present(hid.Hidpp._load_hidapi):
            self.lbl_dev.config(text="G604 подключена по Bluetooth — настройка недоступна")
            self.say("Настройка по Bluetooth запрещена macOS. Подключите приёмник или кабель.")
        else:
            self.say(f"Мышь не найдена — пошевелите её и нажмите «Перечитать». Причина: {last}")

    @property
    def profile(self) -> int:
        try:
            return int(self.var_profile.get())
        except ValueError:
            return 1

    @property
    def layer_offset(self) -> int:
        return OFF_BUTTONS if self.var_layer.get() == "обычный" else OFF_ALT_BUTTONS

    def reload(self):
        current = self.profile
        mine = [k for k in self.pending if k[0] == current]
        if mine and not messagebox.askokcancel(
                "Есть несохранённые изменения",
                f"Для профиля {current} не записано изменений: {len(mine)}.\n"
                "Перечитать и потерять их? (изменения других профилей сохранятся)"):
            return
        if not self.pp:
            self.connect()
        if not self.pp:
            return
        try:
            self.sector = bytearray(self.pp.read_sector(self.profile, SECTOR_SIZE))
            self.sector6 = bytearray(self.pp.read_sector(SECTOR_MACROS, SECTOR_SIZE))
            for key in mine:
                self.pending.pop(key, None)
            self.header_dirty = False
            self._fill_header()
            self._fill_tree()
            self.say(f"Прочитано: профиль {self.profile}, слой «{self.var_layer.get()}».")
        except Exception as e:  # noqa: BLE001
            self.say(f"Ошибка чтения: {e}")

    def _fill_header(self):
        h = decode_header(self.sector)
        for i, v in enumerate(h["dpi"]):
            self.dpi_vars[i].set(str(v))
        self.var_default.set(str(h["default"] + 1))
        self.var_switched.set(str(h["switched"] + 1))
        self.var_hz.set(str(h["hz"] or 1000))

    def refresh_layer(self):
        self._fill_tree()
        pending = len(self.pending)
        tail = f" Не записано изменений: {pending}." if pending else ""
        self.say(f"Слой «{self.var_layer.get()}» профиля {self.profile}.{tail}")

    def parse_layer(self, sector: bytes, offset: int) -> list[dict]:
        return [decode_entry(bytes(sector[offset + i * 4:offset + i * 4 + 4])) for i in range(16)]

    def _fill_tree(self):
        self.entries = self.parse_layer(self.sector, self.layer_offset)
        self.tree.delete(*self.tree.get_children())
        for i, name in enumerate(CONTROLS):
            key = (self.profile, self.layer_offset, i)
            if key in self.pending and self.pending[key]["type"] == "macro":
                act = "★ макрос: " + self._combos_text(self.pending[key]["combos"])
            elif key in self.pending:
                act = "★ " + entry_text(decode_entry(self.pending[key]["bytes"]), self.sector6)
            else:
                act = entry_text(self.entries[i], self.sector6) if i < len(self.entries) else "—"
            self.tree.insert("", "end", iid=str(i), values=(name, act))
        n = len(self.pending)
        self.root.title(f"G604 Control — не записано изменений: {n}" if n else "G604 Control")

    @staticmethod
    def _combos_text(combos: list[dict]) -> str:
        parts = []
        for c in combos:
            mods = "+".join(n for n, m in MODS.items() if c["mods"] & m)
            parts.append(f"{mods + '+' if mods else ''}{c['key']}")
        return " → ".join(parts) or "(пусто)"

    # ---------- правка кнопки
    def on_select(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            return
        i = int(sel[0])
        self.sel_lbl.config(text=CONTROLS[i])
        key = (self.profile, self.layer_offset, i)
        if key in self.pending and self.pending[key]["type"] == "macro":
            self.var_kind.set("macro")
            self.current_macro = list(self.pending[key]["combos"])
            self.lbl_macro.config(text=self._combos_text(self.current_macro))
            self._sync_kind()
            return
        e = self.entries[i] if i < len(self.entries) else {"type": "empty"}
        self.current_macro = []
        if e["type"] == "key":
            self.var_kind.set("key")
            for name, var in self.mod_vars.items():
                var.set(bool(e["mods"] & MODS[name]))
            self.var_key.set(USAGE_TO_KEY.get(e["usage"], "a"))
        elif e["type"] == "mouse":
            self.var_kind.set("mouse")
            self.var_mouse.set(BIT_TO_MOUSE.get(e["mask"], "Назад"))
        elif e["type"] == "special":
            self.var_kind.set("special")
            self.var_special.set(CODE_TO_SPECIAL.get(e["code"], "G-Shift"))
        elif e["type"] == "macro":
            self.var_kind.set("macro")
            steps, _ = macros.parse(self.sector6, e["offset"])
            self.current_macro = [{"mods": s["mods"], "key": USAGE_TO_KEY.get(s["key"], "?"),
                                   "delay": s["delay"]}
                                  for s in steps
                                  if s["op"] == macros.PRESS and s["key"] not in MOD_USAGE.values()]
            self.lbl_macro.config(text=self._combos_text(self.current_macro))
        else:
            self.var_kind.set("none")
        self._sync_kind()

    def edit_macro(self):
        dlg = MacroDialog(self.root, self.current_macro)
        self.root.wait_window(dlg)
        if dlg.result is not None:
            self.current_macro = dlg.result
            self.lbl_macro.config(text=self._combos_text(self.current_macro))
            self.var_kind.set("macro")
            if self.tree.selection():
                self.stage()  # сразу привязываем к выбранной кнопке
                self.say(f"Макрос: {self._combos_text(self.current_macro)} — нажмите «ЗАПИСАТЬ В МЫШЬ».")

    def stage(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("G604 Control", "Сначала выберите кнопку в списке.")
            return
        i = int(sel[0])
        key = (self.profile, self.layer_offset, i)
        k = self.var_kind.get()
        if k == "key":
            mods = sum(m for n, m in MODS.items() if self.mod_vars[n].get())
            self.pending[key] = {"type": "entry",
                                 "bytes": encode_entry("key", mods=mods, usage=KEYS[self.var_key.get()])}
        elif k == "mouse":
            self.pending[key] = {"type": "entry",
                                 "bytes": encode_entry("mouse", mask=MOUSE_BITS[self.var_mouse.get()])}
        elif k == "special":
            self.pending[key] = {"type": "entry",
                                 "bytes": encode_entry("special",
                                                       code=SPECIAL_OPTIONS[self.var_special.get()])}
        elif k == "macro":
            if not self.current_macro:
                messagebox.showinfo("G604 Control",
                                    "Макрос пустой — добавьте комбинации кнопкой «Изменить макрос…».")
                return
            self.pending[key] = {"type": "macro", "combos": list(self.current_macro)}
        else:
            self.pending[key] = {"type": "entry", "bytes": encode_entry("none")}
        self._fill_tree()
        self.tree.selection_set(str(i))
        self.say(f"{CONTROLS[i]}: изменение запомнено, в мышь ещё не записано.")

    # ---------- DPI/частота в профиле
    def apply_header(self):
        if not self.pp:
            messagebox.showerror("G604 Control", "Мышь не найдена.")
            return
        try:
            dpi = [int(v.get()) for v in self.dpi_vars]
        except ValueError:
            messagebox.showerror("G604 Control", "Уровни DPI должны быть числами.")
            return
        encode_header(self.sector, int(self.var_hz.get()), int(self.var_default.get()) - 1,
                      int(self.var_switched.get()) - 1, dpi)
        self.header_dirty = True
        self._fill_header()
        self.say("Уровни DPI и частота обновлены в памяти — нажмите «ЗАПИСАТЬ В МЫШЬ».")

    # ---------- запись
    @staticmethod
    def _rotate_backups(keep: int = 20) -> int:
        """Оставляет последние keep авто-бэкапов, старые удаляет."""
        folder = Path.home() / "Cursor" / "g604-control" / "backups"
        files = sorted(folder.glob("backup-before-write-*.json"))
        removed = 0
        for old in files[:-keep] if len(files) > keep else []:
            try:
                old.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def write(self):
        if not self.pp:
            messagebox.showerror("G604 Control", "Мышь не найдена — запись невозможна.")
            return
        if not self.pending and not self.header_dirty:
            messagebox.showinfo("G604 Control", "Нет изменений для записи.")
            return
        if not messagebox.askokcancel("Запись в мышь",
                                      "Записать изменения в память мыши?\n"
                                      "Перед записью сохранится полный дамп."):
            return
        try:
            self.say("Сохраняю дамп-бэкап…")
            dump = hid._dump_connected(self.pp)
            backup_dir = Path.home() / "Cursor" / "g604-control" / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            bk = backup_dir / f"backup-before-write-{datetime.now():%Y%m%d-%H%M%S}.json"
            bk.write_text(json.dumps(dump, indent=2))
            removed = self._rotate_backups()

            raw6 = bytearray(self.sector6)
            buffers: dict[int, bytearray] = {}

            def buffer_for(prof: int) -> bytearray:
                if prof not in buffers:
                    buffers[prof] = (bytearray(self.sector) if prof == self.profile
                                     else bytearray(self.pp.read_sector(prof, SECTOR_SIZE)))
                return buffers[prof]

            for (prof, offset, i), change in self.pending.items():
                raw1 = buffer_for(prof)
                pos = offset + i * 4
                if change["type"] == "macro":
                    entries = [bytes(raw1[OFF_BUTTONS + j * 4:OFF_BUTTONS + j * 4 + 4]) for j in range(16)]
                    combos = [{"mods": c["mods"], "key": KEYS[c["key"]], "delay": c["delay"]}
                              for c in change["combos"]]
                    blob = build_macro(combos)
                    start = macros.used_end(raw6, entries, macros.parse)
                    if start + len(blob) > SECTOR_SIZE - 1:
                        raise RuntimeError("в секторе макросов не хватает места")
                    raw6[start:start + len(blob)] = blob
                    if start + len(blob) < SECTOR_SIZE:
                        raw6[start + len(blob)] = macros.END
                    raw1[pos:pos + 4] = encode_entry("macro", offset=start)
                    self.say(f"Макрос для профиля {prof}, {CONTROLS[i]} размещён с {start:#04x}")
                else:
                    raw1[pos:pos + 4] = change["bytes"]

            if bytes(raw6) != bytes(self.sector6):
                self.say("Пишу сектор макросов…")
                self.pp.write_sector(SECTOR_MACROS, bytes(raw6), SECTOR_SIZE)

            for prof in sorted(buffers):
                self.say(f"Пишу профиль {prof}…")
                self.pp.write_sector(prof, bytes(buffers[prof]), SECTOR_SIZE)

            self.sector = bytearray(self.pp.read_sector(self.profile, SECTOR_SIZE))
            self.sector6 = bytearray(self.pp.read_sector(SECTOR_MACROS, SECTOR_SIZE))
            self.pending.clear()
            self.header_dirty = False
            dpi_now = apply_profile_dpi(self.pp, bytes(self.sector))
            if dpi_now is not None:
                self.lbl_live_dpi.config(text=str(dpi_now))
                self.var_live_dpi.set(str(dpi_now))
            self._fill_header()
            self._fill_tree()
            tail = f" Удалено старых бэкапов: {removed}." if removed else ""
            self.say(f"Записано и проверено. DPI возвращён на {dpi_now}.{tail}")
        except Exception as e:  # noqa: BLE001
            self.say(f"Ошибка записи: {e}")
            messagebox.showerror("G604 Control", f"Запись не удалась:\n{e}")

    # ---------- дампы
    def save_dump(self):
        if not self.pp:
            messagebox.showerror("G604 Control", "Мышь не найдена.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            initialfile=f"g604-dump-{datetime.now():%Y%m%d-%H%M}.json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(hid._dump_connected(self.pp), indent=2))
            self.say(f"Дамп сохранён: {path}")
        except Exception as e:  # noqa: BLE001
            self.say(f"Ошибка дампа: {e}")

    def restore_dump(self):
        if not self.pp:
            messagebox.showerror("G604 Control", "Мышь не найдена.")
            return
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        if not messagebox.askokcancel("Восстановление", "Записать в мышь ВСЕ сектора из файла?"):
            return
        try:
            payload = json.loads(Path(path).read_text())
            size = int(payload["sector_size"])
            for k, v in sorted(payload["sectors"].items(), key=lambda kv: int(kv[0])):
                self.say(f"Пишу сектор {k}…")
                self.pp.write_sector(int(k), hid.prepare_sector_image(base64.b64decode(v), size), size)
            self.reload()
            dpi_now = apply_profile_dpi(self.pp, bytes(self.sector))
            if dpi_now is not None:
                self.lbl_live_dpi.config(text=str(dpi_now))
                self.var_live_dpi.set(str(dpi_now))
            self.say(f"Восстановлено из {Path(path).name}. DPI возвращён на {dpi_now}.")
        except Exception as e:  # noqa: BLE001
            self.say(f"Ошибка восстановления: {e}")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
