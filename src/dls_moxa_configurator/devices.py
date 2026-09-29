"""The library of serial devices a terminal-server channel can be set up for.

Devices live in TOML (the bundled ``devices.toml`` plus any user files passed
with ``--devices``) in plain serial terms: ``baud = 9600``, ``parity = "even"``.
This module turns those into the index values the NPort ini stores.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

__all__ = [
    "BAUD_RATES",
    "DATA_BITS",
    "FLOW_CONTROLS",
    "INTERFACES",
    "PARITIES",
    "STOP_BITS",
    "CUSTOM_NAME",
    "OTHER",
    "UNUSED_NAME",
    "Device",
    "DeviceError",
    "by_category",
    "load_devices",
]

# ``Baud Rate=`` is an index into the NPort's list of standard rates. Checked
# against the site configs: 12 (9600) on the gauge and ion-pump controllers.
BAUD_RATES = [
    50, 75, 110, 134, 150, 300, 600, 1200, 1800, 2400, 4800, 7200,
    9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600,
]  # fmt: skip

# ``Mode=`` packs the data format into one number, like a 16550 UART's line
# control register: bits 0-1 data bits (5-8), bit 2 two stop bits, bits 3-5
# parity. The site configs use 3 (8N1) and 27 (8E1).
_DATA_BITS = {5: 0, 6: 1, 7: 2, 8: 3}
_STOP_BITS = {1: 0, 2: 4}
_PARITY = {"none": 0, "odd": 8, "even": 24, "mark": 40, "space": 56}

# ``Flow Control=`` index. Only "none" (0) appears in the site configs; the
# rest follow the order in the NPort web UI.
_FLOW_CONTROL = {"none": 0, "rts/cts": 1, "xon/xoff": 2, "dtr/dsr": 3}

# ``Interface=`` index. 0 (RS-232) and 2 (RS-485 2-wire) are confirmed from
# exported configs; 1 and 3 follow the order in the NPort web UI.
_INTERFACE = {"rs232": 0, "rs422": 1, "rs485-2w": 2, "rs485-4w": 3}


# Category for devices that don't name one; always listed last.
OTHER = "Other"

# Names the ini record uses for a port without a library device; reserved.
CUSTOM_NAME = "custom"
UNUSED_NAME = "unused"


class DeviceError(ValueError):
    """A device definition is invalid."""


@dataclass(frozen=True)
class Device:
    """A serial device and the channel settings it needs."""

    name: str
    description: str = ""
    category: str = OTHER
    baud: int = 9600
    data_bits: int = 8
    parity: str = "none"
    stop_bits: int = 1
    flow_control: str = "none"
    interface: str = "rs232"
    fifo: bool = True

    def __post_init__(self) -> None:
        checks: list[tuple[str, object, Any]] = [
            ("baud", self.baud, BAUD_RATES),
            ("data_bits", self.data_bits, _DATA_BITS),
            ("parity", self.parity, _PARITY),
            ("stop_bits", self.stop_bits, _STOP_BITS),
            ("flow_control", self.flow_control, _FLOW_CONTROL),
            ("interface", self.interface, _INTERFACE),
        ]
        for field, value, allowed in checks:
            if value not in allowed:
                raise DeviceError(
                    f"device {self.name!r}: {field} = {value!r} is not one of "
                    f"{list(allowed)}"
                )
        if not isinstance(self.fifo, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise DeviceError(f"device {self.name!r}: fifo must be true or false")

    @property
    def baud_index(self) -> int:
        return BAUD_RATES.index(self.baud)

    @property
    def mode(self) -> int:
        return (
            _DATA_BITS[self.data_bits]
            | _STOP_BITS[self.stop_bits]
            | _PARITY[self.parity]
        )

    def port_values(self) -> dict[str, int]:
        """The ``Communication Parameters @Port #n`` values this device sets."""
        return {
            "Baud Rate": self.baud_index,
            "Mode": self.mode,
            "Flow Control": _FLOW_CONTROL[self.flow_control],
            "FIFO": int(self.fifo),
            "Interface": _INTERFACE[self.interface],
        }

    @property
    def summary(self) -> str:
        """e.g. ``9600 8E1``, ``38400 8N1 rs485-2w no-FIFO``"""
        extras = [
            self.flow_control if self.flow_control != "none" else "",
            self.interface if self.interface != "rs232" else "",
            "" if self.fifo else "no-FIFO",
        ]
        return " ".join(
            [
                f"{self.baud} {self.data_bits}{self.parity[0].upper()}{self.stop_bits}",
                *filter(None, extras),
            ]
        )

    def same_serial(self, other: Device) -> bool:
        """True if both set the port up the same way (name, category and
        description aside)."""
        return self.port_values() == other.port_values()

    @classmethod
    def from_port(cls, name: str, port: dict[str, str]) -> Device:
        """Decode a ``Communication Parameters @Port #n`` section. Raises
        DeviceError for a value this tool can't represent."""

        def lookup(table: dict[Any, int], key: str, value: int) -> Any:
            for k, v in table.items():
                if v == value:
                    return k
            raise DeviceError(f"unsupported {key}={port[key]}")

        raw: dict[str, int] = {}
        for key in _PORT_KEYS:
            try:
                raw[key] = int(port[key])
            except KeyError:
                raise DeviceError(f"no {key}") from None
            except ValueError:
                raise DeviceError(f"unsupported {key}={port[key]}") from None
        baud, mode = raw["Baud Rate"], raw["Mode"]
        if not 0 <= baud < len(BAUD_RATES):
            raise DeviceError(f"unsupported Baud Rate={baud}")
        if mode & ~0b111111:
            raise DeviceError(f"unsupported Mode={mode}")
        if raw["FIFO"] not in (0, 1):
            raise DeviceError(f"unsupported FIFO={raw['FIFO']}")
        return cls(
            name=name,
            baud=BAUD_RATES[baud],
            data_bits=lookup(_DATA_BITS, "Mode", mode & 0b11),
            stop_bits=lookup(_STOP_BITS, "Mode", mode & 0b100),
            parity=lookup(_PARITY, "Mode", mode & 0b111000),
            flow_control=lookup(_FLOW_CONTROL, "Flow Control", raw["Flow Control"]),
            interface=lookup(_INTERFACE, "Interface", raw["Interface"]),
            fifo=bool(raw["FIFO"]),
        )


_PORT_KEYS = list(Device("x").port_values())


def _parse(text: str, source: str) -> list[Device]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise DeviceError(f"{source}: {exc}") from exc
    devices: list[Device] = []
    for entry in data.get("device", []):
        try:
            devices.append(Device(**entry))
        except TypeError as exc:  # unknown or missing key
            raise DeviceError(f"{source}: {exc}") from exc
        except DeviceError as exc:
            raise DeviceError(f"{source}: {exc}") from exc
        if devices[-1].name.casefold() in (CUSTOM_NAME, UNUSED_NAME):
            raise DeviceError(f"{source}: device name {devices[-1].name!r} is reserved")
    return devices


def load_devices(extra: list[Path] | None = None) -> dict[str, Device]:
    """The bundled devices, then each file in ``extra`` in turn. A device in a
    later file replaces an earlier one of the same name."""
    bundled = files("dls_moxa_configurator").joinpath("devices.toml").read_text("utf-8")
    result = {d.name: d for d in _parse(bundled, "devices.toml")}
    for path in extra or []:
        for d in _parse(path.read_text("utf-8"), str(path)):
            result[d.name] = d
    return result


# The choices each Device field accepts, in display order (for editors).
DATA_BITS = list(_DATA_BITS)
PARITIES = list(_PARITY)
STOP_BITS = list(_STOP_BITS)
FLOW_CONTROLS = list(_FLOW_CONTROL)
INTERFACES = list(_INTERFACE)


def by_category(devices: dict[str, Device]) -> list[tuple[str, list[Device]]]:
    """Devices grouped by category for display: categories A-Z with
    :data:`OTHER` last, devices A-Z within each (both case-insensitive)."""
    groups: dict[str, list[Device]] = {}
    for d in devices.values():
        groups.setdefault(d.category, []).append(d)
    order = sorted(groups, key=lambda c: (c == OTHER, c.casefold()))
    return [(c, sorted(groups[c], key=lambda d: d.name.casefold())) for c in order]
