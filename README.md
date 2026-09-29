[![CI](https://github.com/DiamondLightSource/dls-moxa-configurator/actions/workflows/ci.yml/badge.svg)](https://github.com/DiamondLightSource/dls-moxa-configurator/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/DiamondLightSource/dls-moxa-configurator/branch/main/graph/badge.svg)](https://codecov.io/gh/DiamondLightSource/dls-moxa-configurator)
[![PyPI](https://img.shields.io/pypi/v/dls-moxa-configurator.svg)](https://pypi.org/project/dls-moxa-configurator)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

# dls-moxa-configurator

GUI for building a Moxa NPort 6650-16 terminal-server configuration file
(`*_config.ini`) to import through the unit's web UI.

Set the unit-wide settings (name, location, IP, netmask and gateway) at the
top. Then give each of the 16 channels an alias and either a device from the
library, which sets baud rate, data bits, parity, stop bits, flow control,
interface (RS-232/422/485) and FIFO for you, or **Custom…**, which lets you
set them by hand. Channel *n* is TCP port 7000+*n*.

Everything else comes from a template exported from a working unit
(`src/dls_moxa_configurator/templates/NP6650-16.ini`), with its channels reset
to unused. The template has no password lines, so generated files carry no
credentials; set the admin password on the unit itself.

What            | Where
:---:           | :---:
Source          | <https://github.com/DiamondLightSource/dls-moxa-configurator>
PyPI            | `pip install dls-moxa-configurator`
Releases        | <https://github.com/DiamondLightSource/dls-moxa-configurator/releases>

## Running

```
uvx dls-moxa-configurator                        # released version
uv run dls-moxa-configurator                     # from a checkout of this repo
uvx dls-moxa-configurator -d my_devices.toml     # with extra devices
```


## Opening a file

**Open .ini…** loads a file back into the window, which is the quickest way to
make several similar units: open one, change the name, IP and anything else
that differs, and save under a new name. Both dialogs start in the folder you
last used, which is remembered between runs.

The tool ends each file it saves with a comment block recording the device on
each port:

```
; dls-moxa-configurator 0.1.0: channel devices
; port 1: MKS937A
; port 2: custom
; port 3: unused
```

The port's actual settings always win over this record: if a recorded device
no longer matches them (for example, the file was edited by hand or the library
entry has changed), the port opens as **Custom…** and you get a note. A unit's
own export won't have the record, so for those each port's device is guessed
from its serial settings, and where several devices share the same settings
the port opens as **Custom…**. Only the settings this tool manages are read; everything
else in the opened file is replaced by the template.
## Devices

The bundled devices are in
[`src/dls_moxa_configurator/devices.toml`](src/dls_moxa_configurator/devices.toml),
written in plain serial terms:

```toml
[[device]]
name = "MKS937A"
category = "Vacuum"      # drop-down heading; default "Other"
description = "MKS 937A gauge controller"
baud = 9600
parity = "even"         # data_bits = 8, stop_bits = 1, interface = "rs232"
                        # and fifo = true by default
```

To add a device for everyone, add a block to that file. To try one out without
a release, put it in your own TOML file and pass it with `-d` (repeatable). A
device there replaces a bundled one with the same name.

In the channel drop-down, devices are grouped under their `category` (A–Z,
with uncategorised devices under "Other" at the end), sorted by name within
each group. Names must be unique across all categories.

Category | Name | Settings
:-- | :-- | :--
Diagnostics | enzLoCuM4 | 9600 8N1
Motion Control | Geobrick | 38400 8N1
Motion Control | MicronixMDD | 38400 8N1 rs485-2w no-FIFO
Vacuum | DigitelMPC | 9600 8N1
Vacuum | DigitelQPC | 9600 8N1
Vacuum | MKS937A | 9600 8E1
Vacuum | MKS937B | 9600 8N1
Vacuum | rgaPC | 38400 8N1
