#!/usr/bin/env python3
"""
Dump / apply Logitech G604 onboard memory profiles over HID++ 2.0.

Works without G HUB. Talks to the Lightspeed/Unifying receiver (0x046d:0xc539)
using the same Onboard Profiles feature (0x8100) that libratbag uses.

Usage:
  g604-onboard info
  g604-onboard dump [path.json]
  g604-onboard apply path.json [--yes]
  g604-onboard verify path.json

Safety:
  - apply refuses unless the connected device reports as a G604
  - apply requires --yes (or interactive "yes")
  - apply writes a backup dump next to the target file first
  - CRC is recomputed per sector before write (CCITT, seed 0xFFFF)

Requires: macOS + Homebrew libhidapi (libhidapi.dylib)
"""

# HID++ 2.0 транспорт для G604. Источник: gist adamtaylor13 (g604-onboard), лицензия автора.
# Используется только чтение/запись секторов памяти + CRC. Проверено на живой мыши.
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import ctypes
import ctypes.util
from datetime import datetime, timezone
from pathlib import Path

VID = 0x046D
PID_RECEIVER = 0xC539
FEATURE_ONBOARD = 0x8100
FEATURE_NAME = 0x0005
FEATURE_FW = 0x0003
FEATURE_BATTERY = 0x1000
FEATURE_DPI = 0x2201

# HID++ 2.0 OnboardProfiles function ids (high nibble of address)
CMD_GET_PROFILES_DESCR = 0x0
CMD_SET_ONBOARD_MODE = 0x1
CMD_GET_ONBOARD_MODE = 0x2
CMD_SET_CURRENT_PROFILE = 0x3
CMD_GET_CURRENT_PROFILE = 0x4
CMD_MEMORY_READ = 0x5
CMD_MEMORY_ADDR_WRITE = 0x6
CMD_MEMORY_WRITE = 0x7
CMD_MEMORY_WRITE_END = 0x8

ONBOARD_MODE = 0x01
# Prefer libratbag/kernel SWID (0x8); fall back to 0xD which worked on this Mac earlier.
SWID_CANDIDATES = (0x8, 0xD, 0x1)
SWID = 0x8
EXPECTED_NAME = "G604 Wireless Gaming Mouse"

DEFAULT_DIR = Path.home() / ".local" / "share" / "g604-profiles"


# ---------------------------------------------------------------------------
# HID / HID++ transport
# ---------------------------------------------------------------------------

class HidError(RuntimeError):
    pass


class Hidpp:
    def __init__(self):
        self.lib = self._load_hidapi()
        self._setup()
        self.handle = None
        self.dev_idx = 0x01
        self.feature_cache: dict[int, int] = {}

    @staticmethod
    def _load_hidapi():
        import sys
        bundled = []
        if getattr(sys, "frozen", False):
            base = getattr(sys, "_MEIPASS", "")
            if base:
                bundled = [f"{base}/libhidapi.0.15.0.dylib", f"{base}/libhidapi.dylib"]
        for path in (
            *bundled,
            ctypes.util.find_library("hidapi"),
            "/opt/homebrew/lib/libhidapi.dylib",
            "/usr/local/lib/libhidapi.dylib",
        ):
            if not path:
                continue
            try:
                return ctypes.CDLL(path)
            except OSError:
                continue
        raise HidError("libhidapi not found (brew install hidapi)")

    def _setup(self):
        lib = self.lib

        class DeviceInfo(ctypes.Structure):
            pass

        DeviceInfo._fields_ = [
            ("path", ctypes.c_char_p),
            ("vendor_id", ctypes.c_ushort),
            ("product_id", ctypes.c_ushort),
            ("serial_number", ctypes.c_wchar_p),
            ("release_number", ctypes.c_ushort),
            ("manufacturer_string", ctypes.c_wchar_p),
            ("product_string", ctypes.c_wchar_p),
            ("usage_page", ctypes.c_ushort),
            ("usage", ctypes.c_ushort),
            ("interface_number", ctypes.c_int),
            ("next", ctypes.POINTER(DeviceInfo)),
        ]
        self.DeviceInfo = DeviceInfo

        lib.hid_init.restype = ctypes.c_int
        lib.hid_exit.restype = ctypes.c_int
        lib.hid_enumerate.argtypes = [ctypes.c_ushort, ctypes.c_ushort]
        lib.hid_enumerate.restype = ctypes.POINTER(DeviceInfo)
        lib.hid_free_enumeration.argtypes = [ctypes.POINTER(DeviceInfo)]
        lib.hid_open_path.argtypes = [ctypes.c_char_p]
        lib.hid_open_path.restype = ctypes.c_void_p
        lib.hid_close.argtypes = [ctypes.c_void_p]
        lib.hid_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.hid_write.restype = ctypes.c_int
        lib.hid_read_timeout.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_size_t,
            ctypes.c_int,
        ]
        lib.hid_read_timeout.restype = ctypes.c_int
        lib.hid_set_nonblocking.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.hid_error.argtypes = [ctypes.c_void_p]
        lib.hid_error.restype = ctypes.c_wchar_p

        if lib.hid_init() != 0:
            raise HidError("hid_init failed")

    def open(self, prefer_usage: int | None = 1):
        lib = self.lib
        devs = lib.hid_enumerate(VID, PID_RECEIVER)
        if not devs:
            raise HidError(
                f"No Logitech receiver {VID:04x}:{PID_RECEIVER:04x} found. "
                "Is the USB dongle plugged in?"
            )

        candidates = []
        cur = devs
        while cur:
            d = cur.contents
            candidates.append(
                {
                    "path": d.path,
                    "usage_page": d.usage_page,
                    "usage": d.usage,
                    "interface": d.interface_number,
                    "product": d.product_string,
                }
            )
            cur = d.next
        lib.hid_free_enumeration(devs)

        vendor = [c for c in candidates if c["usage_page"] == 0xFF00]
        if not vendor:
            raise HidError("Receiver found but no vendor (0xFF00) HID interface")

        # Prefer usage 1 (works for G604 / Lightspeed receiver)
        vendor.sort(
            key=lambda c: (
                0 if prefer_usage is not None and c["usage"] == prefer_usage else 1,
                c["usage"],
            )
        )

        global SWID
        last_err = None
        for c in vendor:
            h = lib.hid_open_path(c["path"])
            if not h:
                last_err = lib.hid_error(None)
                continue
            lib.hid_set_nonblocking(h, 0)
            self.handle = h
            self._drain()
            # Probe device indices × software-id nibbles
            for dev_idx in (0x01, 0x02, 0x03, 0x04, 0x05, 0x06):
                for swid in SWID_CANDIDATES:
                    SWID = swid
                    try:
                        self.dev_idx = dev_idx
                        self.feature_cache.clear()
                        # Root getProtocolVersion / ping
                        for short in (True, False):
                            try:
                                resp = self._request(
                                    0x00,
                                    0x1,
                                    bytes([0x00, 0x00, 0x5A]),
                                    short=short,
                                    retries=1,
                                    timeout=0.6,
                                )
                                if resp is not None:
                                    return c
                            except HidError as e:
                                last_err = str(e)
                    except HidError as e:
                        last_err = str(e)
                        continue
            lib.hid_close(h)
            self.handle = None

        raise HidError(
            "Could not open a HID++ session to the mouse. "
            "Wiggle the mouse (wake it), unplug/replug the receiver, and retry. "
            f"Last error: {last_err}"
        )

    def close(self):
        if self.handle:
            self.lib.hid_close(self.handle)
            self.handle = None
        self.lib.hid_exit()

    def _drain(self):
        rbuf = ctypes.create_string_buffer(64)
        while self.lib.hid_read_timeout(self.handle, rbuf, 64, 5) > 0:
            pass

    def _request(
        self,
        feature_index: int,
        function: int,
        params: bytes = b"",
        short: bool = False,
        timeout: float = 1.2,
        retries: int = 3,
    ) -> bytes:
        """Send HID++2 request; return parameter bytes (payload after 4-byte header)."""
        if not self.handle:
            raise HidError("device not open")

        addr = ((function & 0x0F) << 4) | (SWID & 0x0F)
        last_err = None

        for attempt in range(retries):
            self._drain()
            if short:
                payload = bytes(
                    [0x10, self.dev_idx, feature_index & 0xFF, addr]
                ) + (params + b"\x00\x00\x00")[:3]
            else:
                payload = bytes(
                    [0x11, self.dev_idx, feature_index & 0xFF, addr]
                ) + (params + bytes(16))[:16]

            n = self.lib.hid_write(self.handle, payload, len(payload))
            if n < 0:
                last_err = f"write failed: {self.lib.hid_error(self.handle)}"
                time.sleep(0.05)
                continue

            rbuf = ctypes.create_string_buffer(64)
            end = time.time() + timeout
            while time.time() < end:
                rn = self.lib.hid_read_timeout(self.handle, rbuf, 64, 80)
                if rn <= 0:
                    continue
                data = bytes(rbuf.raw[:rn])
                if not data or data[0] not in (0x10, 0x11, 0x12):
                    continue
                if len(data) < 4:
                    continue

                # HID++1-style error wrapper
                if data[2] == 0x8F:
                    # [rid, dev, 8f, feat, addr, err]
                    err = data[5] if len(data) > 5 else -1
                    last_err = f"HID++ error 0x{err:02x} for feat={feature_index} fn={function}"
                    break

                # HID++2 error: [rid, dev, 0xFF, feature, address, error_code, ...]
                if data[2] == 0xFF:
                    err = data[5] if len(data) > 5 else -1
                    last_err = (
                        f"HID++2 error 0x{err:02x} "
                        f"(feature=0x{data[3]:02x} address=0x{data[4]:02x})"
                        if len(data) > 5
                        else f"HID++2 error (short reply {data.hex(' ')})"
                    )
                    break

                # Strict match: same device, feature index, address (incl SWID)
                if data[1] == self.dev_idx and data[2] == (feature_index & 0xFF) and data[3] == addr:
                    return data[4:]

                # Loose match: some firmware returns long report with matching feat
                if data[1] == self.dev_idx and data[2] == (feature_index & 0xFF):
                    return data[4:]

            time.sleep(0.03 * (attempt + 1))

        raise HidError(last_err or "HID++ request timed out — is the mouse awake?")

    def get_feature_index(self, feature_id: int) -> int:
        if feature_id in self.feature_cache:
            return self.feature_cache[feature_id]
        if feature_id == 0:
            self.feature_cache[0] = 0
            return 0
        params = bytes([(feature_id >> 8) & 0xFF, feature_id & 0xFF, 0x00])
        # Prefer short first (worked on earlier dump), fall back to long
        try:
            resp = self._request(0x00, 0x0, params, short=True)
        except HidError:
            resp = self._request(0x00, 0x0, params, short=False)
        idx = resp[0]
        if idx == 0 and feature_id != 0:
            raise HidError(f"feature 0x{feature_id:04x} not present")
        self.feature_cache[feature_id] = idx
        return idx

    def device_name(self) -> str:
        f = self.get_feature_index(FEATURE_NAME)
        try:
            resp = self._request(f, 0x0, short=True)
        except HidError:
            resp = self._request(f, 0x0, short=False)
        nlen = resp[0]
        chars = bytearray()
        for start in range(0, nlen, 3):
            try:
                r = self._request(f, 0x1, bytes([start, 0, 0]), short=True)
            except HidError:
                r = self._request(f, 0x1, bytes([start, 0, 0]), short=False)
            chars.extend(r[:3])
        return bytes(chars[:nlen]).decode("utf-8", errors="replace")

    def battery(self) -> int | None:
        try:
            f = self.get_feature_index(FEATURE_BATTERY)
            r = self._request(f, 0x0, short=True)
            return r[0]
        except HidError:
            return None

    def onboard_info(self) -> dict:
        f = self.get_feature_index(FEATURE_ONBOARD)
        try:
            r = self._request(f, CMD_GET_PROFILES_DESCR, short=True)
        except HidError:
            r = self._request(f, CMD_GET_PROFILES_DESCR, short=False)
        # Struct (libratbag hidpp20_onboard_profiles_info):
        #   memory_model, profile_format, macro_format, profile_count,
        #   profile_count_oob, button_count, sector_count, sector_size(u16 BE), ...
        sector_count = r[6]
        sector_size = (r[7] << 8) | r[8]  # G604: 0x00FF = 255
        if sector_size < 16 or sector_size > 4096:
            sector_size = 255
        return {
            "memory_model_id": r[0],
            "profile_format_id": r[1],
            "macro_format_id": r[2],
            "profile_count": r[3],
            "profile_count_oob": r[4],
            "button_count": r[5],
            "sector_count": sector_count,
            "sector_size": sector_size,
            "raw": r[:12].hex(" "),
        }

    def get_active_profile(self) -> int:
        """Return 1-based active profile index (as device reports)."""
        f = self.get_feature_index(FEATURE_ONBOARD)
        try:
            r = self._request(f, CMD_GET_CURRENT_PROFILE, short=True)
        except HidError:
            r = self._request(f, CMD_GET_CURRENT_PROFILE, short=False)
        # Some devices: [unknown, index]; others: [index]
        # Earlier dump: active at byte0 = 1
        if len(r) > 1 and r[1] != 0:
            return r[1]
        return r[0]

    def set_onboard_mode(self):
        f = self.get_feature_index(FEATURE_ONBOARD)
        try:
            self._request(f, CMD_SET_ONBOARD_MODE, bytes([ONBOARD_MODE]), short=True)
        except HidError:
            self._request(f, CMD_SET_ONBOARD_MODE, bytes([ONBOARD_MODE]), short=False)

    # G604 MEMORY_READ rejects offset 0xF0; readable window is 240 bytes.
    READABLE_SIZE = 240

    def read_sector(self, sector: int, sector_size: int) -> bytes:
        """Read a sector. Returns sector_size bytes; unread tail padded 0xFF."""
        f = self.get_feature_index(FEATURE_ONBOARD)
        out = bytearray()
        offset = 0
        max_offset = min(sector_size, self.READABLE_SIZE)
        while offset < max_offset:
            params = bytes(
                [
                    (sector >> 8) & 0xFF,
                    sector & 0xFF,
                    (offset >> 8) & 0xFF,
                    offset & 0xFF,
                ]
            )
            r = self._request(f, CMD_MEMORY_READ, params, short=False, timeout=1.5)
            out.extend(r[:16])
            offset += 16
        if len(out) < sector_size:
            out.extend(b"\xff" * (sector_size - len(out)))
        return bytes(out[:sector_size])

    def write_sector(self, sector: int, data: bytes, sector_size: int):
        """Write a full sector including CRC. data must already be sector_size long."""
        if len(data) != sector_size:
            raise HidError(f"sector data must be {sector_size} bytes, got {len(data)}")
        f = self.get_feature_index(FEATURE_ONBOARD)

        # Firmware requires valid CRC over (sector_size-2) bytes at the end,
        # or it ignores user profiles and falls back to ROM defaults.
        data = apply_sector_crc(bytearray(data))

        params = bytes(
            [
                (sector >> 8) & 0xFF,
                sector & 0xFF,
                0x00,
                0x00,
                (sector_size >> 8) & 0xFF,
                sector_size & 0xFF,
            ]
        )
        self._request(f, CMD_MEMORY_ADDR_WRITE, params, short=False, timeout=2.0)

        offset = 0
        while offset < sector_size:
            chunk = bytearray(data[offset : offset + 16])
            if len(chunk) < 16:
                chunk.extend(b"\x00" * (16 - len(chunk)))
            self._request(f, CMD_MEMORY_WRITE, bytes(chunk), short=False, timeout=2.0)
            offset += 16
            time.sleep(0.01)

        try:
            self._request(f, CMD_MEMORY_WRITE_END, short=True, timeout=2.0, retries=1)
        except HidError:
            try:
                self._request(f, CMD_MEMORY_WRITE_END, short=False, timeout=2.0, retries=1)
            except HidError:
                pass  # G604: END often errors; data still commits

        # Verify the readable portion
        time.sleep(0.02)
        readback = self.read_sector(sector, sector_size)
        n = min(self.READABLE_SIZE, sector_size)
        if readback[:n] != data[:n]:
            diff = sum(1 for a, b in zip(readback[:n], data[:n]) if a != b)
            raise HidError(
                f"sector {sector} write verify failed ({diff}/{n} readable bytes differ)"
            )


# ---------------------------------------------------------------------------
# CRC (Logitech / libratbag CCITT)
# ---------------------------------------------------------------------------

def crc_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        temp = ((crc >> 8) ^ byte) & 0xFF
        crc = ((crc << 8) & 0xFFFF)
        quick = temp ^ (temp >> 4)
        crc ^= quick
        quick = (quick << 5) & 0xFFFF
        crc ^= quick
        quick = (quick << 7) & 0xFFFF
        crc ^= quick
        crc &= 0xFFFF
    return crc


def apply_sector_crc(data: bytearray) -> bytes:
    """Write CCITT CRC (seed 0xFFFF) over data[:-2] into the last two bytes (BE)."""
    if len(data) < 2:
        return bytes(data)
    c = crc_ccitt(bytes(data[:-2]))
    data[-2] = (c >> 8) & 0xFF
    data[-1] = c & 0xFF
    return bytes(data)


def prepare_sector_image(raw: bytes, sector_size: int) -> bytes:
    """Pad/truncate dump bytes to sector_size and stamp a valid CRC."""
    buf = bytearray(raw[:sector_size])
    if len(buf) < sector_size:
        buf.extend(b"\xff" * (sector_size - len(buf)))
    return apply_sector_crc(buf)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_info(args):
    pp = Hidpp()
    try:
        iface = pp.open()
        name = pp.device_name()
        bat = pp.battery()
        info = pp.onboard_info()
        try:
            active = pp.get_active_profile()
        except HidError:
            active = None
        print(f"Receiver interface: usage=0x{iface['usage']:02x} if={iface['interface']}")
        print(f"Device index:       0x{pp.dev_idx:02x}")
        print(f"Name:               {name}")
        print(f"Battery:            {bat if bat is not None else '?'}%")
        print(f"Active profile:     {active}")
        print(f"Onboard caps:       {info}")
    finally:
        pp.close()


def _dump_connected(pp: Hidpp) -> dict:
    name = pp.device_name()
    info = pp.onboard_info()
    sector_size = info["sector_size"]

    # Directory lives in sector 0. Read a few sectors past last profile for macros.
    # Profile directory entries: 4 bytes each → sector numbers for profiles.
    # Also dump a fixed range that covered macros in prior inspection (0..15).
    max_sector = 16
    sectors = {}
    print(f"Dumping sectors 0..{max_sector - 1} (sector_size={sector_size})...", file=sys.stderr)
    for sector in range(max_sector):
        try:
            data = pp.read_sector(sector, sector_size)
        except HidError as e:
            # Stop early if we leave mapped range
            print(f"  sector {sector}: stop ({e})", file=sys.stderr)
            break
        sectors[str(sector)] = base64.b64encode(data).decode("ascii")
        nonempty = sum(1 for b in data if b not in (0x00, 0xFF))
        print(f"  sector {sector}: {sector_size} bytes, {nonempty} non-empty", file=sys.stderr)

    try:
        active = pp.get_active_profile()
    except HidError:
        active = None

    return {
        "format": "g604-onboard-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "device_name": name,
        "receiver_pid": f"0x{PID_RECEIVER:04x}",
        "onboard": info,
        "active_profile": active,
        "sector_size": sector_size,
        "sectors": sectors,
    }


def cmd_dump(args):
    out = Path(args.path) if args.path else DEFAULT_DIR / f"g604-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    pp = Hidpp()
    try:
        pp.open()
        name = pp.device_name()
        if "G604" not in name and not args.force:
            raise SystemExit(
                f"Connected device is {name!r}, not a G604. Pass --force to dump anyway."
            )
        try:
            pp.set_onboard_mode()
        except HidError:
            pass
        payload = _dump_connected(pp)
    finally:
        pp.close()

    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {out}")
    print(f"Device: {payload['device_name']}")
    print(f"Sectors: {len(payload['sectors'])}")
    print(f"Active profile: {payload.get('active_profile')}")


def cmd_apply(args):
    src = Path(args.path)
    if not src.exists():
        raise SystemExit(f"No such file: {src}")

    payload = json.loads(src.read_text())
    if payload.get("format") != "g604-onboard-v1":
        raise SystemExit(f"Unsupported dump format: {payload.get('format')}")

    sector_size = int(payload["sector_size"])
    sectors = {int(k): base64.b64decode(v) for k, v in payload["sectors"].items()}

    pp = Hidpp()
    try:
        pp.open()
        name = pp.device_name()
        if "G604" not in name and not args.force:
            raise SystemExit(
                f"Connected device is {name!r}, not a G604. Refusing to write. "
                "Pass --force only if you know what you're doing."
            )

        print(f"Target device: {name}")
        print(f"Source dump:   {src} ({payload.get('created_at')})")
        print(f"Source device: {payload.get('device_name')}")
        print(f"Sectors to write: {sorted(sectors)}")

        if not args.yes:
            reply = input("Type 'yes' to OVERWRITE onboard memory on the connected mouse: ").strip()
            if reply != "yes":
                raise SystemExit("Aborted.")

        # Backup current mouse first
        backup = src.with_suffix(src.suffix + f".backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
        print(f"Backing up current mouse → {backup}")
        try:
            pp.set_onboard_mode()
        except HidError:
            pass
        backup_payload = _dump_connected(pp)
        backup.write_text(json.dumps(backup_payload, indent=2) + "\n")

        # Write sectors (directory last? or first?)
        # Write profile/macro sectors first, directory (0) last so a partial
        # failure is less likely to leave a broken directory pointing at junk.
        # Use device sector_size (G604: 255). Older dumps may only have 240
        # readable bytes; prepare_sector_image pads and stamps CRC so the
        # firmware accepts user profiles instead of falling back to ROM.
        live_info = pp.onboard_info()
        sector_size = int(live_info["sector_size"])
        print(f"Device sector_size={sector_size} (dump had {payload.get('sector_size')})")

        order = sorted(sectors, key=lambda s: (s == 0, s))
        for sector in order:
            raw = sectors[sector]
            data = prepare_sector_image(raw, sector_size)
            print(f"  writing sector {sector} ({len(data)} bytes, CRC ok)...", file=sys.stderr)
            pp.write_sector(sector, data, sector_size)

        print("Done. Unplug/replug the receiver (or power-cycle the mouse) if buttons look stale.")
        print(f"Backup of previous contents: {backup}")
    finally:
        pp.close()


def cmd_verify(args):
    src = Path(args.path)
    payload = json.loads(src.read_text())
    sectors = {int(k): base64.b64decode(v) for k, v in payload["sectors"].items()}
    sector_size = int(payload["sector_size"])

    pp = Hidpp()
    try:
        pp.open()
        name = pp.device_name()
        print(f"Connected: {name}")
        mismatches = 0
        for sector, expected in sorted(sectors.items()):
            actual = pp.read_sector(sector, sector_size if len(expected) < sector_size else len(expected))
            # compare min length
            n = min(len(expected), len(actual))
            if actual[:n] != expected[:n]:
                # count differing bytes
                diff = sum(1 for i in range(n) if actual[i] != expected[i])
                print(f"  sector {sector}: MISMATCH ({diff}/{n} bytes differ)")
                mismatches += 1
            else:
                print(f"  sector {sector}: ok")
        if mismatches:
            raise SystemExit(f"{mismatches} sector(s) differ from dump")
        print("All dumped sectors match the connected mouse.")
    finally:
        pp.close()


def main(argv=None):
    p = argparse.ArgumentParser(description="Dump/apply G604 onboard profiles via HID++")
    p.add_argument("--force", action="store_true", help="Allow non-G604 devices")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="Show connected mouse info")

    d = sub.add_parser("dump", help="Dump onboard memory to JSON")
    d.add_argument("path", nargs="?", help="Output JSON path")
    d.add_argument("--force", action="store_true")

    a = sub.add_parser("apply", help="Write a dump onto the connected mouse")
    a.add_argument("path", help="Dump JSON produced by `dump`")
    a.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    a.add_argument("--force", action="store_true")

    v = sub.add_parser("verify", help="Compare dump against connected mouse")
    v.add_argument("path")
    v.add_argument("--force", action="store_true")

    args = p.parse_args(argv)
    # bubble force from sub or root
    if not getattr(args, "force", False):
        args.force = False

    try:
        if args.cmd == "info":
            cmd_info(args)
        elif args.cmd == "dump":
            cmd_dump(args)
        elif args.cmd == "apply":
            cmd_apply(args)
        elif args.cmd == "verify":
            cmd_verify(args)
    except HidError as e:
        print(f"error: {e}", file=sys.stderr)
        print(
            "\nHints:\n"
            "  • Wiggle the mouse to wake it, then retry\n"
            "  • Unplug/replug the USB receiver\n"
            "  • Quit G HUB / Logi Options+ if running\n"
            "  • brew install hidapi\n",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
