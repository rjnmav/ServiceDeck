#ifndef MAINWINDOW_H
#define MAINWINDOW_H

#include <QMainWindow>
#include <QTableView>
#include <QLabel>
#include "mainpresenter.h"

class ServiceToolbar;
class ServiceDetailPanel;
class ServiceTableModel;
class ServiceFilterModel;

class MainWindow : public QMainWindow
{
    Q_OBJECT

public:
    explicit MainWindow(MainPresenter *presenter, QWidget *parent = nullptr);
    ~MainWindow();

private slots:
    void populateTable(const QList<SystemdUnit> &units);
    void onSelectionChanged();
    void onOperationCompleted(bool success, const QString &message);
    void onUnitFileContentReady(const QString &content);
    void showContextMenu(const QPoint &pos);

    void onStartClicked();
    void onStopClicked();
    void onRestartClicked();
    void onEnableClicked();
    void onDisableClicked();
    void onMaskClicked();
    void onUnmaskClicked();
    void onCreateClicked();

    void onPreferencesClicked();
    void onAboutClicked();

protected:
    void keyPressEvent(QKeyEvent *event) override;

private:
    void setupUi();
    void setupMenuBar();
    void connectSignals();
    QString selectedServiceName() const;
    bool confirmAction(const QString &action, const QString &serviceName);

    MainPresenter *m_presenter;
    ServiceToolbar *m_toolbar = nullptr;
    ServiceDetailPanel *m_detailPanel = nullptr;
    QTableView *m_tableView = nullptr;
    ServiceTableModel *m_tableModel = nullptr;
    ServiceFilterModel *m_filterModel = nullptr;
    QLabel *m_statusLabel = nullptr;
    QLabel *m_countLabel = nullptr;
};

#endif // MAINWINDOW_H