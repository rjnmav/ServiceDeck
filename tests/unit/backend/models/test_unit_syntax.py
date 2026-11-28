"""Unit file syntax checks shared by the backend, the agent and the GUI editor."""

import pytest

from servicedeck.backend.models.unit_files import is_valid_drop_in_name
from servicedeck.backend.models.unit_syntax import check_unit_text, is_effectively_empty


def test_valid_drop_in() -> None:
    report = check_unit_text("[Service]\nNice=5\nEnvironment=A=1 B=2\n", drop_in=True)
    assert report.ok
    assert not report.warnings
    assert not report.empty


def test_comments_and_blank_lines_are_ignored() -> None:
    report = check_unit_text("# hello\n; also a comment\n\n   \n", drop_in=True)
    assert report.ok
    assert report.empty
    assert is_effectively_empty("# hello\n\n")
    assert not is_effectively_empty("[Service]\n")


def test_key_outside_section_is_an_error() -> None:
    report = check_unit_text("Nice=5\n", drop_in=True)
    assert report.errors == ["Line 1: 'Nice=' must be inside a section such as [Service]."]


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("[Service]\njust words\n", "expected 'Key=Value'"),
        ("[Service\nNice=5\n", "malformed section header"),
        ("[]\n", "empty section name"),
        ("[Service]\nbad key=1\n", "invalid key name"),
    ],
)
def test_malformed_lines(text: str, fragment: str) -> None:
    report = check_unit_text(text, drop_in=True)
    assert not report.ok
    assert fragment in report.errors[0]


def test_unknown_and_duplicate_sections_warn() -> None:
    report = check_unit_text("[Servcie]\nA=1\n[X-Custom]\nB=2\n[Servcie]\nC=3\n", drop_in=True)
    assert report.ok
    assert report.warnings == [
        "Line 1: unknown section [Servcie] (systemd will ignore it).",
        "Line 5: section [Servcie] appears more than once.",
    ]


def test_continuation_lines_are_part_of_the_value() -> None:
    text = "[Service]\nExecStart=/bin/sh -c \\\n    'echo one; \\\n     echo two'\n"
    assert check_unit_text(text, drop_in=True).ok


def test_full_unit_needs_unit_and_service_sections() -> None:
    report = check_unit_text("[Service]\nExecStart=/bin/true\n")
    assert report.errors == ["A service unit needs a [Unit] section."]
    assert check_unit_text("[Unit]\nDescription=x\n[Service]\nExecStart=/bin/true\n").ok


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("override.conf", True),
        ("10-limits.conf", True),
        ("a@b_c.d-e.conf", True),
        ("override", False),
        ("../x.conf", False),
        ("a/b.conf", False),
        (".conf", False),
        ("", False),
    ],
)
def test_drop_in_names(name: str, valid: bool) -> None:
    assert is_valid_drop_in_name(name) is valid
