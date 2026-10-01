"""Unit tests for ServiceTableModel."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from servicedeck.api_client.models.service import Service
from servicedeck.gui.models.service_model import ServiceTableModel


def test_service_table_model_empty(qapp):
    """Verify empty model behavior."""
    model = ServiceTableModel()
    assert model.rowCount() == 0
    assert model.columnCount() == 5
    assert model.service_at(0) is None
    assert model.all_services() == []


def test_service_table_model_headers(qapp):
    """Verify header labels match expected columns."""
    model = ServiceTableModel()
    expected = ["Service Name", "Description", "Active", "Sub State", "Enabled"]
    for col, title in enumerate(expected):
        assert (
            model.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == title
        )


def test_service_table_model_data_roles(qapp):
    """Verify data formatting, colors, and fonts across columns."""
    model = ServiceTableModel()
    services = [
        Service(
            name="demo.service",
            description="A demo unit",
            load_state="loaded",
            active_state="active",
            sub_state="running",
            unit_file_state="enabled",
            scope="user",
        ),
        Service(
            name="fail.service",
            description="Failed unit",
            load_state="loaded",
            active_state="failed",
            sub_state="failed",
            unit_file_state="disabled",
            scope="user",
        ),
    ]
    model.set_services(services)

    assert model.rowCount() == 2
    assert model.service_at(0) == services[0]
    assert model.service_at(1) == services[1]

    # Row 0 Display Role
    idx_name = model.index(0, ServiceTableModel.COL_NAME)
    assert model.data(idx_name, Qt.ItemDataRole.DisplayRole) == "demo.service"

    idx_desc = model.index(0, ServiceTableModel.COL_DESCRIPTION)
    assert model.data(idx_desc, Qt.ItemDataRole.DisplayRole) == "A demo unit"

    idx_active = model.index(0, ServiceTableModel.COL_ACTIVE_STATE)
    assert model.data(idx_active, Qt.ItemDataRole.DisplayRole) == "ACTIVE"

    idx_sub = model.index(0, ServiceTableModel.COL_SUB_STATE)
    assert model.data(idx_sub, Qt.ItemDataRole.DisplayRole) == "running"

    idx_enabled = model.index(0, ServiceTableModel.COL_ENABLED)
    assert model.data(idx_enabled, Qt.ItemDataRole.DisplayRole) == "ENABLED"

    # Color roles for active state
    color_active = model.data(idx_active, Qt.ItemDataRole.ForegroundRole)
    assert isinstance(color_active, QColor)
    assert color_active == ServiceTableModel.COLOR_SUCCESS

    idx_fail_active = model.index(1, ServiceTableModel.COL_ACTIVE_STATE)
    color_failed = model.data(idx_fail_active, Qt.ItemDataRole.ForegroundRole)
    assert color_failed == ServiceTableModel.COLOR_DANGER

    # Font role
    font = model.data(idx_active, Qt.ItemDataRole.FontRole)
    assert isinstance(font, QFont)
    assert font.bold() is True

    # Alignment role
    align = model.data(idx_active, Qt.ItemDataRole.TextAlignmentRole)
    assert align == Qt.AlignmentFlag.AlignCenter
