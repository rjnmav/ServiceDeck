"""Unit tests for ServiceTableModel."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from servicedeck.api_client.models.service import Service
from servicedeck.gui.models.service_model import ServiceTableModel


def test_service_table_model_empty(qapp):
    """Verify empty model behavior."""
    model = ServiceTableModel()
    assert model.rowCount() == 0
    assert model.columnCount() == 3
    assert model.service_at(0) is None
    assert model.all_services() == []
    assert model.state_counts() == {"all": 0, "active": 0, "failed": 0, "inactive": 0}


def test_service_table_model_headers(qapp):
    """Verify header labels match expected 3-column layout."""
    model = ServiceTableModel()
    expected = ["Service", "Status", "Startup"]
    for col, title in enumerate(expected):
        assert (
            model.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == title
        )


def test_service_table_model_data_roles(qapp):
    """Verify data formatting, custom roles, colors, and fonts across columns."""
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
    assert model.state_counts() == {"all": 2, "active": 1, "failed": 1, "inactive": 0}

    # Row 0 Display & Custom Roles
    idx_name = model.index(0, ServiceTableModel.COL_SERVICE)
    assert model.data(idx_name, Qt.ItemDataRole.DisplayRole) == "demo.service"
    assert model.data(idx_name, ServiceTableModel.ROLE_DESCRIPTION) == "A demo unit"

    idx_status = model.index(0, ServiceTableModel.COL_STATUS)
    assert model.data(idx_status, Qt.ItemDataRole.DisplayRole) == "Active"
    assert model.data(idx_status, ServiceTableModel.ROLE_ACTIVE_STATE) == "active"
    assert model.data(idx_status, ServiceTableModel.ROLE_SUB_STATE) == "running"

    idx_startup = model.index(0, ServiceTableModel.COL_STARTUP)
    assert model.data(idx_startup, Qt.ItemDataRole.DisplayRole) == "Enabled"
    assert model.data(idx_startup, ServiceTableModel.ROLE_UNIT_FILE_STATE) == "enabled"

    # Color roles for active state
    color_active = model.data(idx_status, Qt.ItemDataRole.ForegroundRole)
    assert isinstance(color_active, QColor)
    assert color_active == ServiceTableModel.COLOR_SUCCESS

    idx_fail_status = model.index(1, ServiceTableModel.COL_STATUS)
    color_failed = model.data(idx_fail_status, Qt.ItemDataRole.ForegroundRole)
    assert color_failed == ServiceTableModel.COLOR_DANGER

    # Font role
    font = model.data(idx_status, Qt.ItemDataRole.FontRole)
    assert isinstance(font, QFont)
    assert font.bold() is True

    # Alignment role
    align = model.data(idx_status, Qt.ItemDataRole.TextAlignmentRole)
    assert align == Qt.AlignmentFlag.AlignCenter
