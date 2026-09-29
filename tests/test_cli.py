import subprocess
import sys

from dls_moxa_configurator import __version__


def test_cli_version():
    cmd = [sys.executable, "-m", "dls_moxa_configurator", "--version"]
    assert subprocess.check_output(cmd).decode().strip() == __version__
