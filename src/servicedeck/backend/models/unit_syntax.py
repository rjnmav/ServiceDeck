"""Lightweight syntax check for systemd unit files and drop-ins (stdlib only).

This is not a full ``systemd-analyze verify``: it catches text systemd cannot parse at all
(keys outside a section, lines that are neither a section, an assignment nor a comment).
Semantic problems, such as an invalid ``Type=``, are caught after ``daemon-reload`` by
checking the unit's ``LoadState``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

KNOWN_SECTIONS = frozenset({"Unit", "Service", "Install"})

_SECTION = re.compile(r"^\[(?P<name>[^\[\]]*)\]$")
_KEY = re.compile(r"^[A-Za-z0-9_\-]+$")


@dataclass(slots=True)
class UnitSyntaxReport:
    """Errors block a write; warnings are shown but systemd will still load the file."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: True if the text has nothing but blank lines and comments.
    empty: bool = True

    @property
    def ok(self) -> bool:
        return not self.errors


def is_effectively_empty(text: str) -> bool:
    """True if ``text`` contains only whitespace and comments."""
    return all(
        not line.strip() or line.lstrip().startswith(("#", ";")) for line in text.splitlines()
    )


def check_unit_text(text: str, *, drop_in: bool = False) -> UnitSyntaxReport:
    """Check ``text`` line by line. ``drop_in`` relaxes the required-section rules."""
    report = UnitSyntaxReport()
    section: str | None = None
    seen: set[str] = set()
    continuing = False

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if continuing:
            # A trailing backslash continues the previous value onto this line.
            continuing = line.endswith("\\")
            continue
        if not line or line.startswith(("#", ";")):
            continue
        report.empty = False

        match = _SECTION.match(line)
        if match:
            name = match.group("name").strip()
            if not name:
                report.errors.append(f"Line {number}: empty section name '[]'.")
                section = None
                continue
            if name in seen:
                report.warnings.append(f"Line {number}: section [{name}] appears more than once.")
            elif name not in KNOWN_SECTIONS and not name.startswith("X-"):
                report.warnings.append(
                    f"Line {number}: unknown section [{name}] (systemd will ignore it)."
                )
            seen.add(name)
            section = name
            continue

        if line.startswith("["):
            report.errors.append(f"Line {number}: malformed section header '{line}'.")
            continue

        if "=" not in line:
            report.errors.append(
                f"Line {number}: expected 'Key=Value', a [Section] or a comment, got '{line}'."
            )
            continue

        key = line.split("=", 1)[0].strip()
        if not _KEY.match(key):
            report.errors.append(f"Line {number}: invalid key name '{key}'.")
            continue
        if section is None:
            report.errors.append(
                f"Line {number}: '{key}=' must be inside a section such as [Service]."
            )
            continue
        continuing = line.endswith("\\")

    if not drop_in and not report.empty:
        for required in ("Unit", "Service"):
            if required not in seen:
                report.errors.append(f"A service unit needs a [{required}] section.")

    return report


__all__ = ["KNOWN_SECTIONS", "UnitSyntaxReport", "check_unit_text", "is_effectively_empty"]
