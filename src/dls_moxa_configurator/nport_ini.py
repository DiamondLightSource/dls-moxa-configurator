"""Read and edit Moxa NPort configuration export files (``*_config.ini``).

The NPort web UI exports its whole configuration as an ini-like text file and
imports the same format back. It is not quite standard ini (keys contain ``#``,
``.`` and ``=``-free punctuation, and the device writes CRLF line endings), so
rather than round-trip through :mod:`configparser` we keep the file as a list of
lines and edit values in place. Everything we do not touch is written back
byte-for-byte, which keeps the order and spelling the device expects.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["COMMENT", "NPortIni"]

COMMENT = ";"
_SECTION = re.compile(r"^\[(?P<name>.*)\]$")


class NPortIni:
    """An NPort configuration file held as editable lines."""

    def __init__(self, text: str) -> None:
        self.lines: list[str] = text.splitlines()
        # (section, key) -> line index, for O(1) get/set
        self._index: dict[tuple[str, str], int] = {}
        section = ""
        for i, line in enumerate(self.lines):
            m = _SECTION.match(line)
            if m:
                section = m.group("name")
            elif line.startswith(COMMENT):
                continue
            elif "=" in line and section:
                key = line.split("=", 1)[0]
                self._index.setdefault((section, key), i)

    @classmethod
    def load(cls, path: Path) -> NPortIni:
        return cls(path.read_bytes().decode("utf-8"))

    def sections(self) -> list[str]:
        return [m.group("name") for m in map(_SECTION.match, self.lines) if m]

    def section(self, name: str) -> dict[str, str]:
        """All key/value pairs in one section, in file order."""
        return {k: self.get(s, k) for (s, k) in self._index if s == name}

    def get(self, section: str, key: str) -> str:
        return self.lines[self._index[(section, key)]].split("=", 1)[1]

    def set(self, section: str, key: str, value: str | int) -> None:
        """Set an existing key. Raises KeyError for an unknown key rather than
        adding it, since the device silently ignores keys it doesn't know."""
        i = self._index[(section, key)]
        self.lines[i] = f"{key}={value}"

    def comments(self) -> list[str]:
        """The text of every comment line, without the leading ``;``."""
        return [x[len(COMMENT) :].strip() for x in self.lines if x.startswith(COMMENT)]

    def add_comments(self, texts: list[str]) -> None:
        """Append comment lines at the end of the file."""
        self.lines.extend(f"{COMMENT} {t}" for t in texts)

    def dumps(self) -> str:
        """The file text with the CRLF line endings the NPort writes."""
        return "\r\n".join(self.lines) + "\r\n"

    def save(self, path: Path) -> None:
        path.write_bytes(self.dumps().encode("utf-8"))
