"""Unit tests for the ServiceDeck CLI dispatcher."""

from unittest.mock import patch

import pytest

from servicedeck.cli import main


def test_cli_remote_subcommand_message(capsys: pytest.CaptureFixture) -> None:
    """Invoking 'servicedeck remote' prints Phase 2 informational guidance."""
    exit_code = main(["remote"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Phase 2" in captured.err


def test_cli_backend_dispatches_with_defaults() -> None:
    """Invoking 'servicedeck backend' calls backend main with forwarded arguments."""
    with patch("servicedeck.backend.main.main", return_value=0) as mock_backend:
        exit_code = main(["backend", "--port", "8888"])
        assert exit_code == 0
        mock_backend.assert_called_once_with(["--port", "8888"])
