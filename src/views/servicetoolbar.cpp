#include "servicetoolbar.h"
#include <QLabel>

ServiceToolbar::ServiceToolbar(QWidget *parent)
    : QToolBar("Service Actions", parent)
{
    setMovable(false);
    setIconSize(QSize(20, 20));
    setToolButtonStyle(Qt::ToolButtonTextBesideIcon);

    setupActions();
    addSeparator();
    setupSearchAndFilters();
}

void ServiceToolbar::setupActions() {
    m_startAction   = addAction("▶ Start");
    m_stopAction    = addAction("■ Stop");
    m_restartAction = addAction("↻ Restart");

    addSeparator();

    m_enableAction  = addAction("✓ Enable");
    m_disableAction = addAction("✗ Disable");

    addSeparator();

    m_maskAction    = addAction("🔒 Mask");
    m_unmaskAction  = addAction("🔓 Unmask");

    addSeparator();

    m_reloadAction  = addAction("⟳ Reload Daemon");
    m_refreshAction = addAction("🔄 Refresh");
    m_createAction  = addAction("+ Create Service");

    m_startAction->setToolTip("Start the selected service");
    m_stopAction->setToolTip("Stop the selected service");
    m_restartAction->setToolTip("Restart the selected service");
    m_enableAction->setToolTip("Enable the selected service at boot");
    m_disableAction->setToolTip("Disable the selected service at boot");
    m_maskAction->setToolTip("Mask the selected service (prevent starting)");
    m_unmaskAction->setToolTip("Unmask the selected service");
    m_reloadAction->setToolTip("Reload systemd daemon configuration");
    m_refreshAction->setToolTip("Refresh the service list");
    m_createAction->setToolTip("Create a new systemd service unit");

    setActionsEnabled(false);
}

void ServiceToolbar::setupSearchAndFilters() {
    // Search
    QLabel *searchLabel = new QLabel("  Search: ", this);
    addWidget(searchLabel);

    m_searchEdit = new QLineEdit(this);
    m_searchEdit->setPlaceholderText("Filter by name...");
    m_searchEdit->setMinimumWidth(200);
    m_searchEdit->setMaximumWidth(300);
    m_searchEdit->setClearButtonEnabled(true);
    m_searchEdit->setObjectName("searchEdit");
    addWidget(m_searchEdit);

    connect(m_searchEdit, &QLineEdit::textChanged, this, &ServiceToolbar::searchTextChanged);

    // State filter
    QLabel *filterLabel = new QLabel("  Status: ", this);
    addWidget(filterLabel);

    m_filterCombo = new QComboBox(this);
    m_filterCombo->setObjectName("filterCombo");
    m_filterCombo->addItem("All",      "");
    m_filterCombo->addItem("Active",   "active");
    m_filterCombo->addItem("Inactive", "inactive");
    m_filterCombo->addItem("Failed",   "failed");
    m_filterCombo->setMinimumWidth(100);
    addWidget(m_filterCombo);

    connect(m_filterCombo, QOverload<int>::of(&QComboBox::currentIndexChanged), this, [this](int idx) {
        emit activeStateFilterChanged(m_filterCombo->itemData(idx).toString());
    });

    addSeparator();

    // System toggle
    m_systemToggle = new QCheckBox("System Services", this);
    m_systemToggle->setObjectName("systemToggle");
    addWidget(m_systemToggle);

    connect(m_systemToggle, &QCheckBox::toggled, this, &ServiceToolbar::systemModeToggled);
}

void ServiceToolbar::setActionsEnabled(bool enabled) {
    m_startAction->setEnabled(enabled);
    m_stopAction->setEnabled(enabled);
    m_restartAction->setEnabled(enabled);
    m_enableAction->setEnabled(enabled);
    m_disableAction->setEnabled(enabled);
    m_maskAction->setEnabled(enabled);
    m_unmaskAction->setEnabled(enabled);
}
