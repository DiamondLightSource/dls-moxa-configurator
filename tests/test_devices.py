from pathlib import Path

import pytest

from dls_moxa_configurator.devices import (
    OTHER,
    Device,
    DeviceError,
    by_category,
    load_devices,
)

VACUUM = {"MKS937A", "MKS937B", "DigitelMPC", "DigitelQPC", "rgaPC"}


def test_bundled_devices():
    devices = load_devices()
    assert VACUUM <= set(devices)
    assert {devices[n].category for n in VACUUM} == {"Vacuum"}
    uncategorised = sorted(d.name for d in devices.values() if d.category == OTHER)
    assert not uncategorised, (
        f'add a category = "..." line to {", ".join(uncategorised)} in '
        "devices.toml (bundled devices must not fall under Other)"
    )


@pytest.mark.parametrize(
    "kwargs, baud_index, mode",
    [
        ({}, 12, 3),  # 9600 8N1
        ({"parity": "even"}, 12, 27),  # 9600 8E1
        ({"baud": 38400}, 14, 3),
        ({"data_bits": 7, "parity": "odd", "stop_bits": 2}, 12, 2 | 4 | 8),
    ],
)
def test_encoding(kwargs: dict[str, object], baud_index: int, mode: int):
    d = Device("x", **kwargs)  # type: ignore[arg-type]
    assert (d.baud_index, d.mode) == (baud_index, mode)


def test_summary():
    assert Device("x", parity="even").summary == "9600 8E1"
    assert Device("x", flow_control="rts/cts").summary == "9600 8N1 rts/cts"


def test_extra_file_adds_and_overrides(tmp_path: Path):
    extra = tmp_path / "mine.toml"
    extra.write_text(
        '[[device]]\nname = "Widget"\nbaud = 19200\n\n'
        '[[device]]\nname = "rgaPC"\nbaud = 9600\n'
    )
    devices = load_devices([extra])
    assert devices["Widget"].baud == 19200
    assert devices["rgaPC"].baud == 9600
    assert "MKS937A" in devices


@pytest.mark.parametrize(
    "body, match",
    [
        ('name = "a"\nbaud = 12345', "baud"),
        ('name = "a"\nparity = "sometimes"', "parity"),
        ('name = "a"\nspeed = 9600', "unexpected keyword"),
        ("baud = 9600", "name"),
    ],
)
def test_bad_device_file(tmp_path: Path, body: str, match: str):
    extra = tmp_path / "bad.toml"
    extra.write_text(f"[[device]]\n{body}\n")
    with pytest.raises(DeviceError, match=match):
        load_devices([extra])


def test_bad_toml(tmp_path: Path):
    extra = tmp_path / "bad.toml"
    extra.write_text("[[device]\n")
    with pytest.raises(DeviceError, match="bad.toml"):
        load_devices([extra])


def test_category_defaults_to_other():
    assert Device("x").category == OTHER


def test_by_category_order():
    devices = {
        d.name: d
        for d in [
            Device("zeta", category="Vacuum"),
            Device("Alpha", category="Vacuum"),
            Device("loose"),
            Device("m1", category="motion"),
        ]
    }
    grouped = [(c, [d.name for d in ds]) for c, ds in by_category(devices)]
    assert grouped == [
        ("motion", ["m1"]),
        ("Vacuum", ["Alpha", "zeta"]),
        (OTHER, ["loose"]),
    ]


@pytest.mark.parametrize(
    "device",
    [
        Device("x"),
        Device("x", baud=115200, data_bits=7, parity="odd", stop_bits=2),
        Device("x", baud=50, data_bits=5, parity="space", flow_control="dtr/dsr"),
        Device("x", baud=38400, interface="rs485-2w", fifo=False),
        Device("x", interface="rs422"),
        Device("x", interface="rs485-4w"),
    ],
)
def test_from_port_inverts_encoding(device: Device):
    port = {k: str(v) for k, v in device.port_values().items()}
    assert Device.from_port("x", port) == device


def test_port_values_rs485_2w():
    """The MicronixMDD port in tests/data/interface_example.ini."""
    d = Device("x", baud=38400, interface="rs485-2w", fifo=False)
    assert d.port_values() == {
        "Baud Rate": 14,
        "Mode": 3,
        "Flow Control": 0,
        "FIFO": 0,
        "Interface": 2,
    }


@pytest.mark.parametrize(
    "key, value",
    [
        ("Baud Rate", "99"),
        ("Mode", "64"),
        ("Flow Control", "9"),
        ("Interface", "7"),
        ("FIFO", "2"),
        ("Mode", "x"),
    ],
)
def test_from_port_rejects_unknown(key: str, value: str):
    port = {k: str(v) for k, v in Device("x").port_values().items()}
    port[key] = value
    with pytest.raises(DeviceError, match=key):
        Device.from_port("x", port)


def test_summary_extras():
    d = Device("x", baud=38400, interface="rs485-2w", fifo=False)
    assert d.summary == "38400 8N1 rs485-2w no-FIFO"


@pytest.mark.parametrize(
    "body, match",
    [('interface = "rs485"', "interface"), ('fifo = "no"', "fifo")],
)
def test_bad_interface_or_fifo(tmp_path: Path, body: str, match: str):
    extra = tmp_path / "bad.toml"
    extra.write_text(f'[[device]]\nname = "a"\n{body}\n')
    with pytest.raises(DeviceError, match=match):
        load_devices([extra])


def test_same_serial_ignores_name():
    assert Device("a", category="A").same_serial(Device("b"))
    assert not Device("a").same_serial(Device("a", parity="even"))
    assert not Device("a").same_serial(Device("a", interface="rs485-2w"))
    assert not Device("a").same_serial(Device("a", fifo=False))


@pytest.mark.parametrize("name", ["custom", "Unused"])
def test_reserved_names(tmp_path: Path, name: str):
    extra = tmp_path / "bad.toml"
    extra.write_text(f'[[device]]\nname = "{name}"\n')
    with pytest.raises(DeviceError, match="reserved"):
        load_devices([extra])
