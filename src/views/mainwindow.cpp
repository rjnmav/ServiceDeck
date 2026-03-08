#include "mainwindow.h"
#include "servicetoolbar.h"
#include "servicedetailpanel.h"
#include "createservicedialog.h"
#include "service_table_model.h"
#include "service_filter_model.h"
#include <QHeaderView>
#include <QStatusBar>
#include <QMessageBox>
#include <QMenu>
#include <QVBoxLayout>

MainWindow::MainWindow(MainPresenter *presenter, QWidget *parent)
    : QMainWindow(parent), m_presenter(presenter)
{
    setWindowTitle("ServiceDeck — Systemd Service Manager");
    resize(1200, 750);
    setMinimumSize(900, 500);

    setupUi();
    connectSignals();

    // Initial load
    m_presenter->requestServiceList();
}

MainWindow::~MainWindow() {}

void MainWindow::setupUi() {
    // ─── Toolbar ───
    m_toolbar = new ServiceToolbar(this);
    addToolBar(Qt::TopToolBarArea, m_toolbar);

    // ─── Central table view ───
    m_tableModel = new ServiceTableModel(this);
    m_filterModel = new ServiceFilterModel(this);
    m_filterModel->setSourceModel(m_tableModel);
    m_filterModel->setSortRole(Qt::DisplayRole);

    m_tableView = new QTableView(this);
    m_tableView->setObjectName("serviceTable");
    m_tableView->setModel(m_filterModel);
    m_tableView->setSortingEnabled(true);
    m_tableView->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_tableView->setSelectionMode(QAbstractItemView::SingleSelection);
    m_tableView->setAlternatingRowColors(true);
    m_tableView->setShowGrid(false);
    m_tableView->verticalHeader()->setVisible(false);
    m_tableView->horizontalHeader()->setStretchLastSection(true);
    m_tableView->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Interactive);
    m_tableView->horizontalHeader()->setSectionResizeMode(1, QHeaderView::Stretch);
    m_tableView->horizontalHeader()->setHighlightSections(false);
    m_tableView->setContextMenuPolicy(Qt::CustomContextMenu);
    m_tableView->sortByColumn(0, Qt::AscendingOrder);

    // Set sensible default column widths
    m_tableView->setColumnWidth(0, 300);
    m_tableView->setColumnWidth(2, 120);
    m_tableView->setColumnWidth(3, 120);
    m_tableView->setColumnWidth(4, 120);

    setCentralWidget(m_tableView);

    // ─── Detail panel dock ───
    m_detailPanel = new ServiceDetailPanel(this);
    addDockWidget(Qt::BottomDockWidgetArea, m_detailPanel);
    m_detailPanel->hide(); // Hidden until a service is selected

    // ─── Status bar ───
    m_statusLabel = new QLabel("Ready");
    m_statusLabel->setObjectName("statusMessage");
    m_countLabel = new QLabel("0 services");
    m_countLabel->setObjectName("serviceCount");

    statusBar()->addWidget(m_statusLabel, 1);
    statusBar()->addPermanentWidget(m_countLabel);
}

void MainWindow::connectSignals() {
    // Presenter signals
    connect(m_presenter, &MainPresenter::serviceListReady,
            this, &MainWindow::populateTable);
    connect(m_presenter, &MainPresenter::operationCompleted,
            this, &MainWindow::onOperationCompleted);
    connect(m_presenter, &MainPresenter::unitFileContentReady,
            this, &MainWindow::onUnitFileContentReady);

    // Toolbar actions
    connect(m_toolbar->startAction(),   &QAction::triggered, this, &MainWindow::onStartClicked);
    connect(m_toolbar->stopAction(),    &QAction::triggered, this, &MainWindow::onStopClicked);
    connect(m_toolbar->restartAction(), &QAction::triggered, this, &MainWindow::onRestartClicked);
    connect(m_toolbar->enableAction(),  &QAction::triggered, this, &MainWindow::onEnableClicked);
    connect(m_toolbar->disableAction(), &QAction::triggered, this, &MainWindow::onDisableClicked);
    connect(m_toolbar->maskAction(),    &QAction::triggered, this, &MainWindow::onMaskClicked);
    connect(m_toolbar->unmaskAction(),  &QAction::triggered, this, &MainWindow::onUnmaskClicked);
    connect(m_toolbar->reloadAction(),  &QAction::triggered, m_presenter, &MainPresenter::requestReloadDaemon);
    connect(m_toolbar->refreshAction(), &QAction::triggered, m_presenter, &MainPresenter::requestServiceList);
    connect(m_toolbar->createAction(),  &QAction::triggered, this, &MainWindow::onCreateClicked);

    // Toolbar search / filter
    connect(m_toolbar, &ServiceToolbar::searchTextChanged,
            m_filterModel, &ServiceFilterModel::setNameFilter);
    connect(m_toolbar, &ServiceToolbar::activeStateFilterChanged,
            m_filterModel, &ServiceFilterModel::setActiveStateFilter);
    connect(m_toolbar, &ServiceToolbar::systemModeToggled,
            m_presenter, &MainPresenter::requestSwitchBus);

    // Table selection
    connect(m_tableView->selectionModel(), &QItemSelectionModel::selectionChanged,
            this, &MainWindow::onSelectionChanged);

    // Context menu
    connect(m_tableView, &QWidget::customContextMenuRequested,
            this, &MainWindow::showContextMenu);
}

void MainWindow::populateTable(const QList<SystemdUnit> &units) {
    m_tableModel->setServices(units);
    m_countLabel->setText(QString::number(units.size()) + " services");

    // Reconnect selection model (reset invalidates it)
    connect(m_tableView->selectionModel(), &QItemSelectionModel::selectionChanged,
            this, &MainWindow::onSelectionChanged, Qt::UniqueConnection);

    m_detailPanel->clear();
    m_toolbar->setActionsEnabled(false);
}

void MainWindow::onSelectionChanged() {
    QModelIndexList indexes = m_tableView->selectionModel()->selectedRows();
    if (indexes.isEmpty()) {
        m_toolbar->setActionsEnabled(false);
        m_detailPanel->clear();
        return;
    }

    m_toolbar->setActionsEnabled(true);

    QModelIndex sourceIndex = m_filterModel->mapToSource(indexes.first());
    SystemdUnit unit = m_tableModel->serviceAt(sourceIndex.row());

    m_detailPanel->showServiceDetails(unit);
    m_presenter->requestUnitFileContent(unit.unit_path);
}

void MainWindow::onOperationCompleted(bool success, const QString &message) {
    m_statusLabel->setText(message);
    if (success)
        m_statusLabel->setStyleSheet("color: #4CAF50;");
    else
        m_statusLabel->setStyleSheet("color: #F44336;");
}

void MainWindow::onUnitFileContentReady(const QString &content) {
    m_detailPanel->setUnitFileContent(content);
}

void MainWindow::showContextMenu(const QPoint &pos) {
    QModelIndex index = m_tableView->indexAt(pos);
    if (!index.isValid())
        return;

    m_tableView->selectRow(index.row());

    QMenu menu(this);
    menu.setObjectName("contextMenu");
    menu.addAction("▶ Start",     this, &MainWindow::onStartClicked);
    menu.addAction("■ Stop",      this, &MainWindow::onStopClicked);
    menu.addAction("↻ Restart",   this, &MainWindow::onRestartClicked);
    menu.addSeparator();
    menu.addAction("✓ Enable",    this, &MainWindow::onEnableClicked);
    menu.addAction("✗ Disable",   this, &MainWindow::onDisableClicked);
    menu.addSeparator();
    menu.addAction("🔒 Mask",     this, &MainWindow::onMaskClicked);
    menu.addAction("🔓 Unmask",   this, &MainWindow::onUnmaskClicked);

    menu.exec(m_tableView->viewport()->mapToGlobal(pos));
}

// ─── Action handlers ───

void MainWindow::onStartClicked() {
    QString name = selectedServiceName();
    if (!name.isEmpty())
        m_presenter->requestStartService(name);
}

void MainWindow::onStopClicked() {
    QString name = selectedServiceName();
    if (!name.isEmpty() && confirmAction("stop", name))
        m_presenter->requestStopService(name);
}

void MainWindow::onRestartClicked() {
    QString name = selectedServiceName();
    if (!name.isEmpty())
        m_presenter->requestRestartService(name);
}

void MainWindow::onEnableClicked() {
    QString name = selectedServiceName();
    if (!name.isEmpty())
        m_presenter->requestEnableService(name);
}

void MainWindow::onDisableClicked() {
    QString name = selectedServiceName();
    if (!name.isEmpty() && confirmAction("disable", name))
        m_presenter->requestDisableService(name);
}

void MainWindow::onMaskClicked() {
    QString name = selectedServiceName();
    if (!name.isEmpty() && confirmAction("mask", name))
        m_presenter->requestMaskService(name);
}

void MainWindow::onUnmaskClicked() {
    QString name = selectedServiceName();
    if (!name.isEmpty())
        m_presenter->requestUnmaskService(name);
}

void MainWindow::onCreateClicked() {
    CreateServiceDialog dlg(this);
    if (dlg.exec() == QDialog::Accepted) {
        m_presenter->requestCreateService(dlg.fileName(), dlg.content(), dlg.isSystemScope());
    }
}

// ─── Helpers ───

QString MainWindow::selectedServiceName() const {
    QModelIndexList indexes = m_tableView->selectionModel()->selectedRows();
    if (indexes.isEmpty())
        return {};
    QModelIndex sourceIndex = m_filterModel->mapToSource(indexes.first());
    return m_tableModel->serviceAt(sourceIndex.row()).name;
}

bool MainWindow::confirmAction(const QString &action, const QString &serviceName) {
    QMessageBox::StandardButton reply = QMessageBox::warning(
        const_cast<MainWindow*>(this),
        "Confirm " + action,
        "Are you sure you want to <b>" + action + "</b> the service:<br><br>"
        "<b>" + serviceName + "</b>?",
        QMessageBox::Yes | QMessageBox::No,
        QMessageBox::No
    );
    return reply == QMessageBox::Yes;
}