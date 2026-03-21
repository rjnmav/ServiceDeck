#ifndef SERVICEDETAILPANEL_H
#define SERVICEDETAILPANEL_H

#include <QDockWidget>
#include <QElapsedTimer>
#include <QLabel>
#include <QTimer>
#include <QTextEdit>
#include <QTabWidget>
#include "systemd_dbus.h"
#include "unit_model.h"

class ServiceDetailPanel : public QDockWidget
{
    Q_OBJECT

public:
    explicit ServiceDetailPanel(QWidget *parent = nullptr);

    void showServiceDetails(const SystemdUnit &unit);
    void setUnitFileContent(const QString &content);
    void clear();

private:
    void setupUi();
    void refreshServiceLogs();
    void refreshResourceUsage();
    QString loadServiceLogs() const;
    void resetResourceUsageState();

    QTabWidget *m_tabWidget = nullptr;

    // Properties tab
    QLabel *m_nameValue = nullptr;
    QLabel *m_descValue = nullptr;
    QLabel *m_activeValue = nullptr;
    QLabel *m_subStateValue = nullptr;
    QLabel *m_loadValue = nullptr;
    QLabel *m_enabledValue = nullptr;
    QLabel *m_pathValue = nullptr;

    // Unit file tab
    QTextEdit *m_unitFileEdit = nullptr;

    // Service log tab
    QTextEdit *m_serviceLogEdit = nullptr;
    QTimer *m_logRefreshTimer = nullptr;

    // Resource usage tab
    QLabel *m_runningSinceValue = nullptr;
    QLabel *m_uptimeValue = nullptr;
    QLabel *m_cpuUsageValue = nullptr;
    QLabel *m_memoryUsageValue = nullptr;
    QLabel *m_diskReadValue = nullptr;
    QLabel *m_diskWriteValue = nullptr;
    QLabel *m_processCountValue = nullptr;
    QLabel *m_threadCountValue = nullptr;
    QTimer *m_resourceRefreshTimer = nullptr;
    SystemdDBus *m_resourceDbus = nullptr;
    SystemdUnit m_currentUnit;
    QElapsedTimer m_resourceElapsedTimer;
    quint64 m_previousCpuUsageNs = 0;
    quint64 m_previousReadBytes = 0;
    quint64 m_previousWriteBytes = 0;
    bool m_hasPreviousCpuSample = false;
    bool m_hasPreviousReadSample = false;
    bool m_hasPreviousWriteSample = false;
};

#endif // SERVICEDETAILPANEL_H
