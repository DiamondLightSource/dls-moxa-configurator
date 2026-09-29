"""PySide6 window: unit-wide settings on top, one row per serial channel below.

Each channel picks a device from the library (its serial settings are shown
read-only) or "Custom…", which makes the serial settings editable."""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .devices import (
    BAUD_RATES,
    CUSTOM_NAME,
    DATA_BITS,
    FLOW_CONTROLS,
    INTERFACES,
    PARITIES,
    STOP_BITS,
    Device,
    by_category,
)
from .generate import MODEL, N_PORTS, Channel, Settings, generate, read_settings
from .nport_ini import NPortIni

__all__ = ["MainWindow", "SerialEditor", "run_gui", "UNUSED", "CUSTOM"]

UNUSED = "(unused)"
CUSTOM = "Custom…"
_COL_PORT, _COL_DEVICE, _COL_ALIAS, _COL_SERIAL = range(4)
_FILE_FILTER = "NPort config (*.ini);;All files (*)"
_LAST_DIR_KEY = "last_dir"


def _combo(values: list[int] | list[str], tooltip: str) -> QComboBox:
    combo = QComboBox()
    combo.addItems([str(v) for v in values])
    combo.setToolTip(tooltip)
    return combo


def _device_combo(devices: dict[str, Device]) -> QComboBox:
    """(unused), then each category as a bold unselectable heading followed by
    its devices, then Custom…. Item text is the device name, so
    ``currentText()`` looks the device up directly."""
    combo = QComboBox()
    model = combo.model()
    assert isinstance(model, QStandardItemModel)
    combo.addItem(UNUSED)
    for category, members in by_category(devices):
        heading = QStandardItem(f"── {category} ──")
        heading.setFlags(Qt.ItemFlag.NoItemFlags)  # not selectable
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        model.appendRow(heading)
        for dev in members:
            combo.addItem(dev.name)
            tip = dev.description or dev.name
            combo.setItemData(
                combo.count() - 1, f"{tip}\n{dev.summary}", Qt.ItemDataRole.ToolTipRole
            )
    combo.addItem(CUSTOM)
    combo.setItemData(
        combo.count() - 1,
        "Set the serial parameters by hand",
        Qt.ItemDataRole.ToolTipRole,
    )
    return combo


class SerialEditor(QWidget):
    """Baud / data bits / parity / stop bits / flow control / interface / FIFO
    for one channel.

    Shows a library device's settings read-only, or lets the user edit them
    for a custom channel."""

    def __init__(self) -> None:
        super().__init__()
        self.baud = _combo(BAUD_RATES, "Baud rate")
        self.data_bits = _combo(DATA_BITS, "Data bits")
        self.parity = _combo(PARITIES, "Parity")
        self.stop_bits = _combo(STOP_BITS, "Stop bits")
        self.flow_control = _combo(FLOW_CONTROLS, "Flow control")
        self.interface = _combo(INTERFACES, "Serial interface")
        self.fifo = QCheckBox("FIFO")
        self.fifo.setToolTip("UART FIFO enabled")
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for widget in self._widgets():
            layout.addWidget(widget)
        self.setLayout(layout)
        self.show_device(Device(CUSTOM_NAME))

    def _widgets(self) -> list[QWidget]:
        return [
            self.baud,
            self.data_bits,
            self.parity,
            self.stop_bits,
            self.flow_control,
            self.interface,
            self.fifo,
        ]

    def show_device(self, device: Device) -> None:
        self.baud.setCurrentText(str(device.baud))
        self.data_bits.setCurrentText(str(device.data_bits))
        self.parity.setCurrentText(device.parity)
        self.stop_bits.setCurrentText(str(device.stop_bits))
        self.flow_control.setCurrentText(device.flow_control)
        self.interface.setCurrentText(device.interface)
        self.fifo.setChecked(device.fifo)

    def set_editable(self, editable: bool) -> None:
        for widget in self._widgets():
            widget.setEnabled(editable)

    def device(self) -> Device:
        return Device(
            name=CUSTOM_NAME,
            baud=int(self.baud.currentText()),
            data_bits=int(self.data_bits.currentText()),
            parity=self.parity.currentText(),
            stop_bits=int(self.stop_bits.currentText()),
            flow_control=self.flow_control.currentText(),
            interface=self.interface.currentText(),
            fifo=self.fifo.isChecked(),
        )


class MainWindow(QMainWindow):
    def __init__(
        self, devices: dict[str, Device], store: QSettings | None = None
    ) -> None:
        super().__init__()
        self.devices = devices
        # remembers the last folder used; tests pass their own
        self.store = store or QSettings("DiamondLightSource", "dls-moxa-configurator")
        self.setWindowTitle(f"Moxa {MODEL} configurator")

        # --- unit-wide settings ------------------------------------------
        self.name_edit = QLineEdit()
        self.location_edit = QLineEdit()
        self.ip_edit = QLineEdit()
        self.netmask_edit = QLineEdit("255.255.255.0")
        self.gateway_edit = QLineEdit()
        self.gateway_edit.setPlaceholderText("none")

        form = QFormLayout()
        form.addRow("Server name", self.name_edit)
        form.addRow("Location", self.location_edit)
        form.addRow("IP address", self.ip_edit)
        form.addRow("Netmask", self.netmask_edit)
        form.addRow("Gateway", self.gateway_edit)
        unit_box = QGroupBox("Terminal server")
        unit_box.setLayout(form)

        # --- channels ----------------------------------------------------
        self.table = QTableWidget(N_PORTS, 4)
        self.table.setHorizontalHeaderLabels(
            [
                "TCP port",
                "Device",
                "Alias",
                "Baud / data / parity / stop / flow / interface / FIFO",
            ]
        )
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_ALIAS, QHeaderView.ResizeMode.Stretch)
        self.device_combos: list[QComboBox] = []
        self.alias_edits: list[QLineEdit] = []
        self.serial_editors: list[SerialEditor] = []
        for row in range(N_PORTS):
            port = QTableWidgetItem(f"{row + 1}  ({7001 + row})")
            port.setFlags(port.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, _COL_PORT, port)
            combo = _device_combo(devices)
            combo.currentTextChanged.connect(partial(self._on_device_changed, row))
            self.table.setCellWidget(row, _COL_DEVICE, combo)
            self.device_combos.append(combo)
            alias = QLineEdit()
            alias.setFrame(False)
            self.table.setCellWidget(row, _COL_ALIAS, alias)
            self.alias_edits.append(alias)
            editor = SerialEditor()
            self.table.setCellWidget(row, _COL_SERIAL, editor)
            self.serial_editors.append(editor)
            self._update_row(row)
        channel_box = QGroupBox("Channels")
        channel_layout = QVBoxLayout()
        channel_layout.addWidget(self.table)
        channel_box.setLayout(channel_layout)

        open_button = QPushButton("Open .ini…")
        open_button.setToolTip(
            "Load a file saved by this tool (or exported from a unit)"
        )
        open_button.clicked.connect(self.open_dialog)
        save = QPushButton("Save .ini…")
        save.clicked.connect(self.save_dialog)
        buttons = QHBoxLayout()
        buttons.addWidget(open_button)
        buttons.addStretch()
        buttons.addWidget(save)

        layout = QVBoxLayout()
        layout.addWidget(unit_box)
        layout.addWidget(channel_box, stretch=1)
        layout.addLayout(buttons)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)
        self.resize(1100, 760)

    def _on_device_changed(self, row: int, _name: str) -> None:
        self._update_row(row)

    def _update_row(self, row: int) -> None:
        """Library device: show its settings, locked. Custom: unlock, starting
        from whatever was showing. Unused: hide."""
        choice = self.device_combos[row].currentText()
        editor = self.serial_editors[row]
        dev = self.devices.get(choice)
        if dev is not None:
            editor.show_device(dev)
        editor.set_editable(choice == CUSTOM)
        editor.setVisible(choice != UNUSED)

    def channel_device(self, row: int) -> Device | None:
        choice = self.device_combos[row].currentText()
        if choice == CUSTOM:
            return self.serial_editors[row].device()
        return self.devices.get(choice)

    def settings(self) -> Settings:
        channels = [
            Channel(self.channel_device(row), self.alias_edits[row].text().strip())
            for row in range(N_PORTS)
        ]
        return Settings(
            name=self.name_edit.text().strip(),
            location=self.location_edit.text().strip(),
            ip=self.ip_edit.text().strip(),
            netmask=self.netmask_edit.text().strip(),
            gateway=self.gateway_edit.text().strip(),
            channels=channels,
        )

    def save(self, path: Path) -> None:
        """Generate and write the file. Raises ValueError on bad settings."""
        s = self.settings()
        if not s.name:
            raise ValueError("Server name is empty")
        generate(s).save(path)

    def open(self, path: Path) -> list[str]:
        """Load a file into the window. Returns notes on ports whose device
        could not be restored exactly. Raises ValueError/KeyError/OSError for a
        file that isn't a supported NPort config, leaving the window as it was."""
        settings, notes = read_settings(NPortIni.load(path), self.devices)
        self.apply(settings)
        return notes

    def apply(self, s: Settings) -> None:
        self.name_edit.setText(s.name)
        self.location_edit.setText(s.location)
        self.ip_edit.setText(s.ip)
        self.netmask_edit.setText(s.netmask)
        self.gateway_edit.setText(s.gateway)
        for row, ch in enumerate(s.channels):
            self.alias_edits[row].setText(ch.alias)
            combo = self.device_combos[row]
            if ch.device is None:
                combo.setCurrentText(UNUSED)
            elif self.devices.get(ch.device.name) == ch.device:
                combo.setCurrentText(ch.device.name)
            else:
                combo.setCurrentText(CUSTOM)
                self.serial_editors[row].show_device(ch.device)

    # --- file dialogs, starting in the folder last used (kept across runs) --

    def last_dir(self) -> str:
        value = self.store.value(_LAST_DIR_KEY, "")
        return value if isinstance(value, str) else ""

    def remember_dir(self, path: str) -> None:
        self.store.setValue(_LAST_DIR_KEY, str(Path(path).parent))

    def save_dialog(self) -> None:
        name = f"{self.name_edit.text().strip() or 'nport'}_config.ini"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save NPort configuration",
            str(Path(self.last_dir()) / name),
            _FILE_FILTER,
        )
        if not path:
            return
        self.remember_dir(path)
        try:
            self.save(Path(path))
        except (ValueError, OSError) as exc:
            QMessageBox.critical(self, "Not saved", str(exc))
            return
        self.statusBar().showMessage(f"Saved {path}", 10000)

    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open NPort configuration", self.last_dir(), _FILE_FILTER
        )
        if not path:
            return
        self.remember_dir(path)
        try:
            notes = self.open(Path(path))
        except (ValueError, KeyError, OSError, UnicodeDecodeError) as exc:
            QMessageBox.critical(self, "Not opened", f"{path}:\n{exc}")
            return
        self.statusBar().showMessage(f"Opened {path}", 10000)
        if notes:
            QMessageBox.information(
                self, "Opened with notes", "\n".join(["Check these ports:", *notes])
            )


def run_gui(devices: dict[str, Device]) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow(devices)
    win.show()
    sys.exit(app.exec())
