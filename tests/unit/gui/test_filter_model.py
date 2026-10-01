"""Unit tests for ServiceFilterModel."""

from servicedeck.api_client.models.service import Service
from servicedeck.gui.models.service_filter_model import ServiceFilterModel
from servicedeck.gui.models.service_model import ServiceTableModel


def test_filter_by_name(qapp):
    """Verify name-based filtering (case-insensitive substring)."""
    table_model = ServiceTableModel()
    filter_model = ServiceFilterModel()
    filter_model.setSourceModel(table_model)

    services = [
        Service(
            name="ssh.service",
            description="OpenSSH server",
            load_state="loaded",
            active_state="active",
            sub_state="running",
            unit_file_state="enabled",
        ),
        Service(
            name="systemd-resolved.service",
            description="Network Name Resolution",
            load_state="loaded",
            active_state="active",
            sub_state="running",
            unit_file_state="enabled",
        ),
        Service(
            name="cups.service",
            description="CUPS Scheduler",
            load_state="loaded",
            active_state="inactive",
            sub_state="dead",
            unit_file_state="disabled",
        ),
    ]
    table_model.set_services(services)
    assert filter_model.rowCount() == 3

    # Filter by "ssh"
    filter_model.set_name_filter("ssh")
    assert filter_model.rowCount() == 1
    idx = filter_model.index(0, ServiceTableModel.COL_NAME)
    assert filter_model.data(idx) == "ssh.service"

    # Filter with no match
    filter_model.set_name_filter("nonexistent")
    assert filter_model.rowCount() == 0

    # Clear filter
    filter_model.set_name_filter("")
    assert filter_model.rowCount() == 3


def test_filter_by_active_state(qapp):
    """Verify active-state filtering."""
    table_model = ServiceTableModel()
    filter_model = ServiceFilterModel()
    filter_model.setSourceModel(table_model)

    services = [
        Service(
            name="active1.service",
            description="",
            load_state="loaded",
            active_state="active",
            sub_state="running",
            unit_file_state="enabled",
        ),
        Service(
            name="inactive1.service",
            description="",
            load_state="loaded",
            active_state="inactive",
            sub_state="dead",
            unit_file_state="disabled",
        ),
        Service(
            name="failed1.service",
            description="",
            load_state="loaded",
            active_state="failed",
            sub_state="failed",
            unit_file_state="enabled",
        ),
    ]
    table_model.set_services(services)

    filter_model.set_active_state_filter("active")
    assert filter_model.rowCount() == 1

    filter_model.set_active_state_filter("inactive")
    assert filter_model.rowCount() == 1

    filter_model.set_active_state_filter("failed")
    assert filter_model.rowCount() == 1

    filter_model.set_active_state_filter("")
    assert filter_model.rowCount() == 3
