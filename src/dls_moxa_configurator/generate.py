"""Build an NPort configuration file from global settings and per-channel devices.

Everything not set here comes from a bundled template exported from a working
unit (``templates/NP6650-16.ini``), with its channels reset to unused. The
per-port TCP/UDP port numbers in the template already follow the unit's fixed
numbering (channel n listens on 7000+n), so a channel only needs its alias and
serial settings.

The template has no password lines (``User Pass #1``, ``Console Password``), so
generated files carry no credentials.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from importlib.resources import files

from . import __version__
from .devices import CUSTOM_NAME, UNUSED_NAME, Device, DeviceError
from .nport_ini import NPortIni

__all__ = [
    "Channel",
    "Settings",
    "generate",
    "load_template",
    "read_record",
    "read_settings",
    "MODEL",
    "N_PORTS",
]

MODEL = "NP6650-16"
N_PORTS = 16

# What an unused channel is set to: the value the template unit ships on every
# spare port (9600 8E1, RS-232, FIFO on, no alias).
_UNUSED = Device(UNUSED_NAME, parity="even")


@dataclass
class Channel:
    """One serial port: the device on it (None if unused) and its alias."""

    device: Device | None = None
    alias: str = ""


@dataclass
class Settings:
    """Unit-wide settings."""

    name: str
    location: str = ""
    ip: str = "192.168.127.254"  # the NPort factory default
    netmask: str = "255.255.255.0"
    gateway: str = ""  # blank = none (the NPort stores 255.255.255.255)
    channels: list[Channel] = field(
        default_factory=lambda: [Channel() for _ in range(N_PORTS)]
    )


def load_template() -> NPortIni:
    text = (
        files("dls_moxa_configurator")
        .joinpath("templates", f"{MODEL}.ini")
        .read_text("utf-8")
    )
    return NPortIni(text)


def _check_ip(label: str, value: str) -> str:
    try:
        return str(ipaddress.IPv4Address(value))
    except ValueError:
        raise ValueError(f"{label} {value!r} is not an IPv4 address") from None


def generate(settings: Settings) -> NPortIni:
    """The template with ``settings`` applied. Raises ValueError for a bad
    address or a wrong number of channels."""
    if len(settings.channels) != N_PORTS:
        raise ValueError(f"{MODEL} has {N_PORTS} ports, got {len(settings.channels)}")
    ip = _check_ip("IP address", settings.ip)
    netmask = _check_ip("Netmask", settings.netmask)
    gateway = (
        _check_ip("Gateway", settings.gateway)
        if settings.gateway.strip()
        else "255.255.255.255"
    )

    ini = load_template()
    ini.set("Overview", "IP Address", ip)
    ini.set("Basic Settings", "Server Name", settings.name)
    ini.set("Basic Settings", "Server Location", settings.location)
    ini.set("Network Settings", "IPv4 Address", ip)
    ini.set("Network Settings", "IPv4 Netmask", netmask)
    ini.set("Network Settings", "IPv4 Gateway", gateway)

    for n, ch in enumerate(settings.channels, start=1):
        section = f"Communication Parameters @Port #{n}"
        ini.set(section, "Port Alias", ch.alias)
        values = _UNUSED.port_values() if ch.device is None else ch.device.port_values()
        for key, value in values.items():
            ini.set(section, key, value)
    ini.lines.append("")
    ini.add_comments(_record_lines(settings))
    return ini


# --- channel record -------------------------------------------------------
# generate() appends a comment block naming the device on each port, e.g.
#
#   ; dls-moxa-configurator 0.1.0: channel devices
#   ; port 1: MKS937A
#   ; port 2: custom
#   ; port 3: unused
#
# read_settings() uses it to restore the device choices. A unit's own export
# won't carry it, so without one the device is inferred from the serial
# settings.

RECORD_HEADER = "dls-moxa-configurator"
_RECORD_LINE = re.compile(r"^port (?P<n>\d+): (?P<device>.+)$")


def _record_lines(settings: Settings) -> list[str]:
    lines = [f"{RECORD_HEADER} {__version__}: channel devices"]
    for n, ch in enumerate(settings.channels, start=1):
        lines.append(f"port {n}: {ch.device.name if ch.device else UNUSED_NAME}")
    return lines


def read_record(ini: NPortIni) -> dict[int, str]:
    """Port number -> device name ("custom", "unused" or a library name), or
    empty if the file has no record."""
    comments = ini.comments()
    if not any(c.startswith(RECORD_HEADER) for c in comments):
        return {}
    record: dict[int, str] = {}
    for c in comments:
        m = _RECORD_LINE.match(c)
        if m:
            record[int(m.group("n"))] = m.group("device").strip()
    return record


def _is_unused(alias: str, wire: Device) -> bool:
    return alias == "" and wire.same_serial(_UNUSED)


def read_settings(
    ini: NPortIni, devices: dict[str, Device]
) -> tuple[Settings, list[str]]:
    """Settings for the window from an NPort ini, plus notes on any port whose
    device could not be restored exactly.

    The port's actual serial settings always win: a recorded device is used
    only if it still matches them, otherwise the port becomes custom."""
    model = ini.get("Overview", "Model Name")
    if model != MODEL:
        raise ValueError(f"{model} is not supported, only {MODEL}")
    gateway = ini.get("Network Settings", "IPv4 Gateway")
    record = read_record(ini)
    notes: list[str] = []
    channels: list[Channel] = []
    for n in range(1, N_PORTS + 1):
        s = ini.section(f"Communication Parameters @Port #{n}")
        alias = s["Port Alias"]
        try:
            wire = Device.from_port(CUSTOM_NAME, s)
        except DeviceError as exc:
            notes.append(f"port {n}: {exc}; left unused")
            channels.append(Channel(None, alias))
            continue
        if _is_unused(alias, wire) and record.get(n, UNUSED_NAME) == UNUSED_NAME:
            channels.append(Channel(None, alias))
        else:
            device = _port_device(n, wire, record.get(n), devices, notes)
            channels.append(Channel(device, alias))
    settings = Settings(
        name=ini.get("Basic Settings", "Server Name"),
        location=ini.get("Basic Settings", "Server Location"),
        ip=ini.get("Network Settings", "IPv4 Address"),
        netmask=ini.get("Network Settings", "IPv4 Netmask"),
        gateway="" if gateway == "255.255.255.255" else gateway,
        channels=channels,
    )
    return settings, notes


def _port_device(
    n: int,
    wire: Device,
    recorded: str | None,
    devices: dict[str, Device],
    notes: list[str],
) -> Device:
    """The device for a port in use, given its settings and recorded name."""
    if recorded == CUSTOM_NAME:
        return wire
    if recorded in devices:
        if devices[recorded].same_serial(wire):
            return devices[recorded]
        notes.append(
            f"port {n}: recorded as {recorded} but set to {wire.summary}, not "
            f"{devices[recorded].summary}; opened as custom"
        )
        return wire
    if recorded == UNUSED_NAME:
        notes.append(f"port {n}: recorded as unused but configured")
    elif recorded is not None:
        notes.append(f"port {n}: {recorded} is not in the device library")
    # no usable record: infer from the serial settings
    matches = sorted(d.name for d in devices.values() if d.same_serial(wire))
    if len(matches) == 1:
        notes.append(f"port {n}: {wire.summary} matched {matches[0]}")
        return devices[matches[0]]
    if matches:
        notes.append(
            f"port {n}: {wire.summary} matches {', '.join(matches)}; opened as custom"
        )
    return wire
