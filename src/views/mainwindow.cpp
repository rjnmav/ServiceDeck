#include "mainwindow.h"
#include <QHeaderView>

MainWindow::MainWindow(MainPresenter *presenter, QWidget *parent)
    : QMainWindow(parent), m_presenter(presenter)
{
    setWindowTitle("ServiceDeck");
    resize(800, 600);

    centralWidget = new QWidget(this);
    setCentralWidget(centralWidget);
    layout = new QVBoxLayout(centralWidget);

    refreshBtn = new QPushButton("Refresh Services", this);
    layout->addWidget(refreshBtn);

    serviceList = new QTreeWidget(this);
    serviceList->setColumnCount(3);
    serviceList->setHeaderLabels({"Service Name", "Status", "Description"});
    serviceList->header()->setSectionResizeMode(0, QHeaderView::ResizeToContents);
    layout->addWidget(serviceList);

    connect(refreshBtn, &QPushButton::clicked, m_presenter, &MainPresenter::requestServiceList);

    connect(m_presenter, &MainPresenter::serviceListReady, this, &MainWindow::populateTable);

    m_presenter->requestServiceList();
}

MainWindow::~MainWindow() {}

void MainWindow::populateTable(const QList<SystemdUnit> &units) {
    serviceList->clear();
    for (const auto &unit : units) {
        QTreeWidgetItem *item = new QTreeWidgetItem(serviceList);
        item->setText(0, unit.name);
        item->setText(1, unit.active_state);
        item->setText(2, unit.description);
    }
}