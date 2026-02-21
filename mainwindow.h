#ifndef MAINWINDOW_H
#define MAINWINDOW_H

#include <QMainWindow>
#include <QTreeWidget>
#include <QPushButton>
#include <QVBoxLayout>
#include "servicemanager.h"

class MainWindow : public QMainWindow
{
    Q_OBJECT

public:
    MainWindow(QWidget *parent = nullptr);
    ~MainWindow();

private slots:
    void refreshServiceList();

private:
    QWidget *centralWidget;
    QVBoxLayout *layout;
    QTreeWidget *serviceList;
    QPushButton *refreshBtn;
    ServiceManager *manager;
};

#endif // MAINWINDOW_H