#include "mainwindow.h"
#include <QHeaderView>

MainWindow::MainWindow(QWidget *parent)
    : QMainWindow(parent)
{
    // 1. Setup UI Elements
    setWindowTitle("ServiceDeck");
    resize(800, 600);

    centralWidget = new QWidget(this);
    setCentralWidget(centralWidget);

    layout = new QVBoxLayout(centralWidget);

    // The Refresh Button
    refreshBtn = new QPushButton("Refresh Services", this);
    layout->addWidget(refreshBtn);

    // The List (TreeWidget)
    serviceList = new QTreeWidget(this);
    serviceList->setColumnCount(3);
    serviceList->setHeaderLabels({"Service Name", "Status", "Description"});
    serviceList->header()->setSectionResizeMode(0, QHeaderView::ResizeToContents);
    layout->addWidget(serviceList);

    // 2. Setup Backend
    manager = new ServiceManager(this);

    // 3. Connect Signals
    connect(refreshBtn, &QPushButton::clicked, this, &MainWindow::refreshServiceList);

    // 4. Load initial data
    refreshServiceList();
}

MainWindow::~MainWindow() {}

void MainWindow::refreshServiceList()
{
    serviceList->clear();
    QList<SystemdUnit> units = manager->getAllServices();

    for (const auto &unit : units) {
        QTreeWidgetItem *item = new QTreeWidgetItem(serviceList);
        
        // Column 0: Name
        item->setText(0, unit.name);
        
        // Column 1: Active State (Green/Red text logic can be added here)
        item->setText(1, unit.active_state);
        
        // Column 2: Description
        item->setText(2, unit.description);
    }
}