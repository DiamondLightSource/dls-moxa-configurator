"""Regenerate real SR vacuum terminal-server configs and compare.

tests/data holds configs exported from working units (passwords blanked). The
device on each port comes from the SR-BUILDER IOC XML (asyn port
192.168.<cell>.11/12:700n -> gaugeSet / gaugeSetA / digitelMpc / QPC / rga).
"""

from pathlib import Path

import pytest

from dls_moxa_configurator.devices import CUSTOM_NAME, Device, load_devices
from dls_moxa_configurator.generate import (
    N_PORTS,
    Channel,
    Settings,
    generate,
    load_template,
    read_record,
    read_settings,
)
from dls_moxa_configurator.nport_ini import NPortIni

DATA = Path(__file__).parent / "data"
DEVICES = load_devices()
PASSWORDS = {"User Pass #1", "Console Password"}

# fixture -> {port: device}, from the SR-BUILDER XML. SR10C ports 5-6 are
# declared with digitelMpcq.proto but are really MPCe (so DigitelMPC).
# MPC ports in cells 5-7, 10 and 13-18 are set to 8E1 on the units, not the
# 8N1 the manuals give; they work only because the MPC ignores parity. Those
# misconfigured ports are left out.
PORTS = {
    "sr03c_8026": {2: "MKS937A", 3: "MKS937A", 4: "DigitelMPC", 5: "DigitelMPC",
                   6: "DigitelMPC"},
    "sr03c_8027": {1: "rgaPC", 3: "MKS937A", 4: "MKS937A", 5: "DigitelMPC",
                   6: "DigitelMPC", 7: "DigitelMPC", 8: "DigitelMPC",
                   9: "DigitelMPC", 10: "DigitelMPC"},
    "sr04c_8026": {1: "MKS937B", 2: "MKS937A", 3: "MKS937A", 4: "DigitelMPC",
                   5: "DigitelMPC", 6: "DigitelMPC"},
    "sr07c_8027": {1: "rgaPC", 2: "MKS937B", 3: "MKS937B", 4: "MKS937B",
                   6: "DigitelQPC"},
    "sr10c_8026": {1: "MKS937B", 2: "MKS937A", 3: "MKS937A"},
    "sr19c_8026": {4: "DigitelMPC", 5: "DigitelMPC", 6: "DigitelMPC"},
}  # fmt: skip


def settings_from(real: NPortIni, ports: dict[int, str]) -> Settings:
    channels: list[Channel] = []
    for n in range(1, N_PORTS + 1):
        alias = real.get(f"Communication Parameters @Port #{n}", "Port Alias")
        channels.append(Channel(DEVICES.get(ports.get(n, "")), alias))
    return Settings(
        name=real.get("Basic Settings", "Server Name"),
        location=real.get("Basic Settings", "Server Location"),
        ip=real.get("Network Settings", "IPv4 Address"),
        channels=channels,
    )


@pytest.mark.parametrize("fixture", PORTS)
def test_device_ports_match_real_unit(fixture: str):
    real = NPortIni.load(DATA / f"{fixture}.ini")
    ours = generate(settings_from(real, PORTS[fixture]))
    for n in PORTS[fixture]:
        section = f"Communication Parameters @Port #{n}"
        assert ours.section(section) == real.section(section), (fixture, n)


def test_whole_file_matches_real_unit():
    """SR04C unit 1 regenerated from name/IP/devices alone is the real export,
    except the Overview (serial no., MAC, firmware: read-only on import) and the
    password lines the template leaves out. That unit runs firmware 2.2; the
    template is from 2.3, which adds a few keys."""
    real = NPortIni.load(DATA / "sr04c_8026.ini")
    ours = generate(settings_from(real, PORTS["sr04c_8026"]))
    assert ours.sections() == real.sections()
    for section in real.sections():
        if section == "Overview":
            continue
        theirs = {k: v for k, v in real.section(section).items() if k not in PASSWORDS}
        mine = {k: v for k, v in ours.section(section).items() if k in theirs}
        assert mine == theirs, section
    assert ours.get("Overview", "IP Address") == "192.168.4.11"


def test_output_is_crlf():
    text = generate(Settings(name="X", ip="10.0.0.1")).dumps()
    assert text.count("\r\n") == text.count("\n")
    assert text.startswith("\r\n[NPort Configuration File]\r\n")


def test_output_has_no_password_lines():
    lines = generate(Settings(name="X", ip="10.0.0.1")).lines
    assert not [x for x in lines if x.split("=", 1)[0] in PASSWORDS]


def test_gateway_applied():
    ini = generate(Settings(name="X", ip="10.0.0.1", gateway="10.0.0.254"))
    assert ini.get("Network Settings", "IPv4 Gateway") == "10.0.0.254"
    blank = generate(Settings(name="X", ip="10.0.0.1"))
    assert blank.get("Network Settings", "IPv4 Gateway") == "255.255.255.255"


def test_custom_device_applied():
    dev = Device("custom", baud=115200, data_bits=7, parity="odd", stop_bits=2,
                 flow_control="rts/cts")  # fmt: skip
    channels = [Channel(dev, "C1")] + [Channel() for _ in range(N_PORTS - 1)]
    ini = generate(Settings(name="X", ip="10.0.0.1", channels=channels))
    port1 = ini.section("Communication Parameters @Port #1")
    assert (port1["Baud Rate"], port1["Mode"], port1["Flow Control"]) == (
        "16",
        str(2 | 4 | 8),
        "1",
    )


@pytest.mark.parametrize("field", ["ip", "netmask", "gateway"])
def test_bad_address_rejected(field: str):
    s = Settings(name="X", ip="10.0.0.1")
    setattr(s, field, "10.0.0.300")
    with pytest.raises(ValueError, match="not an IPv4 address"):
        generate(s)


def test_wrong_channel_count_rejected():
    with pytest.raises(ValueError, match="16 ports"):
        generate(Settings(name="X", channels=[Channel()]))


def test_save_roundtrip(tmp_path: Path):
    path = tmp_path / "out.ini"
    ini = generate(Settings(name="X", ip="10.0.0.1"))
    ini.save(path)
    assert path.read_bytes() == ini.dumps().encode()
    assert NPortIni.load(path).get("Basic Settings", "Server Name") == "X"


def test_set_unknown_key_raises():
    with pytest.raises(KeyError):
        load_template().set("Basic Settings", "No Such Key", 1)


# --- channel record and reading back --------------------------------------


def _mixed_settings() -> Settings:
    channels = [Channel() for _ in range(N_PORTS)]
    channels[0] = Channel(DEVICES["MKS937A"], "GAUGE")
    channels[1] = Channel(DEVICES["DigitelMPC"], "PUMP")
    channels[2] = Channel(DEVICES["MKS937B"], "")  # in use with no alias
    channels[4] = Channel(Device(CUSTOM_NAME, baud=19200, parity="odd"), "ODD")
    return Settings(
        name="TS-01",
        location="RACK",
        ip="10.0.0.5",
        netmask="255.255.0.0",
        gateway="10.0.0.1",
        channels=channels,
    )


def test_record_written():
    ini = generate(_mixed_settings())
    assert ini.lines[-N_PORTS - 1].startswith("; dls-moxa-configurator ")
    assert read_record(ini)[1] == "MKS937A"
    assert read_record(ini)[4] == "unused"
    assert read_record(ini)[5] == "custom"
    assert ini.dumps().endswith("; port 16: unused\r\n")


def test_record_does_not_disturb_values(tmp_path: Path):
    """Comment lines are skipped by the parser, even ones containing '='."""
    path = tmp_path / "x.ini"
    generate(_mixed_settings()).save(path)
    ini = NPortIni.load(path)
    assert ini.get("SSL/TLS Configuration", "High Security Mode") == "0"


def test_roundtrip(tmp_path: Path):
    original = _mixed_settings()
    path = tmp_path / "x.ini"
    generate(original).save(path)
    restored, notes = read_settings(NPortIni.load(path), DEVICES)
    assert notes == []
    assert restored == original


def test_changed_library_device_opens_as_custom(tmp_path: Path):
    path = tmp_path / "x.ini"
    generate(_mixed_settings()).save(path)
    library = dict(DEVICES)
    library["MKS937A"] = Device("MKS937A", baud=19200)
    restored, notes = read_settings(NPortIni.load(path), library)
    ch = restored.channels[0]
    assert ch.device is not None and ch.device.name == CUSTOM_NAME
    assert ch.device.summary == "9600 8E1"  # the file's settings win
    assert any("port 1: recorded as MKS937A" in n for n in notes)


def test_unit_export_without_record_infers():
    """sr04c unit 1 as exported by the unit: no record, so devices are inferred
    from the serial settings; 9600 8N1 is ambiguous."""
    real = NPortIni.load(DATA / "sr04c_8026.ini")
    assert read_record(real) == {}
    restored, notes = read_settings(real, DEVICES)
    assert restored.name == "SR04C-VA-TSERV-01"
    assert restored.ip == "192.168.4.11"
    assert restored.gateway == ""
    ch = restored.channels
    assert ch[1].device == DEVICES["MKS937A"]  # 9600 8E1 is unique
    assert ch[1].alias == "GCTLR_A_01"
    assert ch[0].device is not None and ch[0].device.name == CUSTOM_NAME
    assert ch[15].device is None
    assert any(n.startswith("port 1: 9600 8N1 matches ") for n in notes)


def test_other_model_rejected():
    ini = load_template()
    ini.set("Overview", "Model Name", "NP5610-8")
    with pytest.raises(ValueError, match="NP5610-8"):
        read_settings(ini, DEVICES)


def test_rs485_device_matches_real_unit():
    """MicronixMDD (RS-485 2-wire, FIFO off) on port 5 of a unit's export."""
    real = NPortIni.load(DATA / "interface_example.ini")
    channels = [Channel() for _ in range(N_PORTS)]
    channels[4] = Channel(DEVICES["MicronixMDD"], "MicronixMDD")
    ours = generate(Settings(name="X", ip="10.0.0.1", channels=channels))
    section = "Communication Parameters @Port #5"
    assert ours.section(section) == real.section(section)


def test_unit_export_rs485_port_opens_as_micronix():
    restored, _ = read_settings(NPortIni.load(DATA / "interface_example.ini"), DEVICES)
    assert restored.channels[4].device == DEVICES["MicronixMDD"]
