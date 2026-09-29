"""Headless tests for the configurator window."""

from pathlib import Path

import pytest

from dls_moxa_configurator.devices import by_category, load_devices
from dls_moxa_configurator.nport_ini import NPortIni

# Skip (rather than error) where the Qt platform libraries are unavailable,
# e.g. a minimal container without libGL. CI runners have them.
try:
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QStandardItemModel

    from dls_moxa_configurator.gui import CUSTOM, UNUSED, MainWindow
except ImportError as exc:
    pytest.skip(f"Qt unavailable: {exc}", allow_module_level=True)


@pytest.fixture
def win(qapp: object, tmp_path: Path):
    store = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    w = MainWindow(load_devices(), store)
    w.name_edit.setText("TS-01")
    w.ip_edit.setText("10.0.0.1")
    yield w
    w.close()


def port1(path: Path) -> tuple[str, str, str, str]:
    s = NPortIni.load(path).section("Communication Parameters @Port #1")
    return s["Port Alias"], s["Baud Rate"], s["Mode"], s["Flow Control"]


def test_device_list_offered(win: MainWindow):
    combo = win.device_combos[0]
    items = [combo.itemText(i) for i in range(combo.count())]
    expected = [UNUSED]
    for category, members in by_category(win.devices):
        expected += [f"── {category} ──", *(d.name for d in members)]
    assert items == [*expected, CUSTOM]
    assert "── Vacuum ──" in items


def test_category_heading_not_selectable(win: MainWindow):
    model = win.device_combos[0].model()
    assert isinstance(model, QStandardItemModel)
    heading = model.item(1)
    assert heading is not None
    assert not heading.isEnabled() and not heading.isSelectable()


def test_library_device_shown_read_only(win: MainWindow):
    win.device_combos[1].setCurrentText("MKS937A")
    editor = win.serial_editors[1]
    assert editor.parity.currentText() == "even"
    assert not editor.baud.isEnabled()
    assert not editor.isHidden()
    win.device_combos[1].setCurrentText(UNUSED)
    assert editor.isHidden()


def test_custom_is_editable_and_starts_from_previous(win: MainWindow):
    win.device_combos[0].setCurrentText("rgaPC")
    win.device_combos[0].setCurrentText(CUSTOM)
    editor = win.serial_editors[0]
    assert editor.baud.isEnabled()
    assert editor.baud.currentText() == "38400"


def test_save_library_device(win: MainWindow, tmp_path: Path):
    win.device_combos[0].setCurrentText("rgaPC")
    win.alias_edits[0].setText("RGA_PC_01")
    win.save(tmp_path / "out.ini")
    assert port1(tmp_path / "out.ini") == ("RGA_PC_01", "14", "3", "0")


def test_save_custom(win: MainWindow, tmp_path: Path):
    win.device_combos[0].setCurrentText(CUSTOM)
    editor = win.serial_editors[0]
    editor.baud.setCurrentText("19200")
    editor.data_bits.setCurrentText("7")
    editor.parity.setCurrentText("odd")
    editor.stop_bits.setCurrentText("2")
    editor.flow_control.setCurrentText("xon/xoff")
    win.save(tmp_path / "out.ini")
    assert port1(tmp_path / "out.ini") == ("", "13", str(2 | 4 | 8), "2")


@pytest.mark.parametrize(
    "name, ip, match", [("", "10.0.0.1", "name"), ("X", "not-an-ip", "IPv4")]
)
def test_save_refuses_bad_settings(
    win: MainWindow, tmp_path: Path, name: str, ip: str, match: str
):
    win.name_edit.setText(name)
    win.ip_edit.setText(ip)
    with pytest.raises(ValueError, match=match):
        win.save(tmp_path / "out.ini")
    assert not (tmp_path / "out.ini").exists()


def test_open_restores_window(win: MainWindow, tmp_path: Path):
    win.location_edit.setText("RACK-9")
    win.gateway_edit.setText("10.0.0.254")
    win.device_combos[0].setCurrentText("MKS937A")
    win.alias_edits[0].setText("GAUGE")
    win.device_combos[3].setCurrentText(CUSTOM)
    win.serial_editors[3].baud.setCurrentText("57600")
    win.serial_editors[3].parity.setCurrentText("odd")
    path = tmp_path / "out.ini"
    win.save(path)
    saved = win.settings()

    other = MainWindow(win.devices, win.store)
    assert other.open(path) == []
    assert other.settings() == saved
    assert other.device_combos[0].currentText() == "MKS937A"
    assert other.device_combos[3].currentText() == CUSTOM
    assert other.serial_editors[3].baud.isEnabled()
    assert other.serial_editors[3].baud.currentText() == "57600"
    other.close()


def test_open_bad_file_leaves_window(win: MainWindow, tmp_path: Path):
    path = tmp_path / "junk.ini"
    path.write_text("not an nport file\n")
    with pytest.raises(KeyError):
        win.open(path)
    assert win.name_edit.text() == "TS-01"


def test_last_dir_remembered(win: MainWindow, tmp_path: Path):
    assert win.last_dir() == ""
    win.remember_dir(str(tmp_path / "sub" / "x.ini"))
    assert win.last_dir() == str(tmp_path / "sub")
    # a new window (i.e. the next run) sees it too
    again = MainWindow(win.devices, win.store)
    assert again.last_dir() == str(tmp_path / "sub")
    again.close()


def test_save_custom_rs485(win: MainWindow, tmp_path: Path):
    win.device_combos[0].setCurrentText(CUSTOM)
    editor = win.serial_editors[0]
    assert editor.interface.isEnabled() and editor.fifo.isEnabled()
    editor.interface.setCurrentText("rs485-2w")
    editor.fifo.setChecked(False)
    win.save(tmp_path / "out.ini")
    s = NPortIni.load(tmp_path / "out.ini").section("Communication Parameters @Port #1")
    assert (s["Interface"], s["FIFO"]) == ("2", "0")


def test_library_rs485_device_shown(win: MainWindow):
    win.device_combos[2].setCurrentText("MicronixMDD")
    editor = win.serial_editors[2]
    assert editor.interface.currentText() == "rs485-2w"
    assert not editor.fifo.isChecked() and not editor.fifo.isEnabled()
