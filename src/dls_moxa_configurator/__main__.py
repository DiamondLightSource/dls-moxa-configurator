"""``dls-moxa-configurator`` command line: opens the configurator GUI.

The entry point is named to match the package, so it launches with::

    uvx dls-moxa-configurator
    uvx dls-moxa-configurator --devices my_devices.toml

PySide6 is imported inside the command so ``--version`` / ``--help`` stay fast.
"""

from pathlib import Path
from typing import Annotated

import typer

from . import __version__

__all__ = ["main"]

app = typer.Typer(add_completion=False)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def gui(
    devices: Annotated[
        list[Path] | None,
        typer.Option(
            "-d",
            "--devices",
            exists=True,
            dir_okay=False,
            help="extra device TOML file (repeatable); overrides bundled "
            "devices of the same name",
        ),
    ] = None,
    version: Annotated[
        bool,
        typer.Option(
            "-v",
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Build a Moxa NPort terminal-server .ini file by picking a device per
    channel."""
    from .devices import DeviceError, load_devices

    try:
        library = load_devices(devices)
    except DeviceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    from .gui import run_gui

    run_gui(library)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
