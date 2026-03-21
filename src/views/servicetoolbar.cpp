#include "servicetoolbar.h"
#include <QLabel>
#include <QAbstractItemView>
#include <QWindow>

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
    m_startAction   = addAction("Start");
    m_startAction->setIcon(QIcon::fromTheme("media-playback-start"));
    m_stopAction    = addAction("Stop");
    m_stopAction->setIcon(QIcon::fromTheme("media-playback-stop"));
    m_restartAction = addAction("Restart");
    m_restartAction->setIcon(QIcon::fromTheme("view-refresh"));

    addSeparator();

    m_enableAction  = addAction("Enable");
    m_enableAction->setIcon(QIcon::fromTheme("emblem-default"));
    m_disableAction = addAction("Disable");
    m_disableAction->setIcon(QIcon::fromTheme("process-stop"));

    addSeparator();

    m_maskAction    = addAction("Mask");
    m_maskAction->setIcon(QIcon::fromTheme("object-locked"));
    m_unmaskAction  = addAction("Unmask");
    m_unmaskAction->setIcon(QIcon::fromTheme("object-unlocked"));

    addSeparator();

    m_reloadAction  = addAction("Reload Daemon");
    m_reloadAction->setIcon(QIcon::fromTheme("view-refresh"));
    m_refreshAction = addAction("Refresh");
    m_refreshAction->setIcon(QIcon::fromTheme("view-refresh"));
    m_createAction  = addAction("Create Service");
    m_createAction->setIcon(QIcon::fromTheme("document-new"));

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
    QLabel *searchLabel = new QLabel("Search: ", this);
    addWidget(searchLabel);

    m_searchEdit = new QLineEdit(this);
    m_searchEdit->setPlaceholderText("Filter by name...");
    m_searchEdit->setMinimumWidth(200);
    m_searchEdit->setMaximumWidth(300);
    m_searchEdit->setClearButtonEnabled(true);
    m_searchEdit->setObjectName("searchEdit");
    addWidget(m_searchEdit);
    
    // Add a spacer item
    QWidget *spacer = new QWidget();
    spacer->setFixedWidth(10);
    spacer->setSizePolicy(QSizePolicy::Fixed, QSizePolicy::Fixed);
    addWidget(spacer);

    connect(m_searchEdit, &QLineEdit::textChanged, this, &ServiceToolbar::searchTextChanged);

    // State filter
    QLabel *filterLabel = new QLabel("Status: ", this);
    addWidget(filterLabel);

    m_filterCombo = new QComboBox(this);
    m_filterCombo->setObjectName("filterCombo");
    m_filterCombo->addItem("All",      "");
    m_filterCombo->addItem("Active",   "active");
    m_filterCombo->addItem("Inactive", "inactive");
    m_filterCombo->addItem("Failed",   "failed");
    m_filterCombo->setMinimumWidth(100);
    m_filterCombo->setMaximumWidth(200);
    m_filterCombo->setCursor(Qt::PointingHandCursor);
    m_filterCombo->view()->setCursor(Qt::PointingHandCursor);
    m_filterCombo->view()->window()->setWindowFlags(Qt::Popup);
    m_filterCombo->setItemDelegate(new ItemSpacingDelegate(m_filterCombo));
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
