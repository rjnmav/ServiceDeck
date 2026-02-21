#ifndef MAINWINDOW_H
#define MAINWINDOW_H

#include <QMainWindow>
#include <QTreeWidget>
#include <QPushButton>
#include <QVBoxLayout>
#include "mainpresenter.h"

class MainWindow : public QMainWindow
{
    Q_OBJECT

public:
    // The View requires a Presenter to function
    explicit MainWindow(MainPresenter *presenter, QWidget *parent = nullptr);
    ~MainWindow();

private slots:
    // Reacts to the Presenter's signal
    void populateTable(const QList<SystemdUnit> &units);

private:
    MainPresenter *m_presenter;
    QWidget *centralWidget;
    QVBoxLayout *layout;
    QTreeWidget *serviceList;
    QPushButton *refreshBtn;
};

#endif