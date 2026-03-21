#ifndef SYSTEMD_DBUS_H
#define SYSTEMD_DBUS_H

#include <QObject>
#include <QtDBus/QtDBus>
#include "unit_model.h"

struct OperationResult {
    bool success;
    QString message;
};

struct ServiceResourceUsage {
    quint64 cpu_usage_nsec = 0;
    quint64 memory_current = 0;
    quint64 io_read_bytes = 0;
    quint64 io_write_bytes = 0;
    quint64 active_enter_timestamp_usec = 0;
    int process_count = 0;
    int thread_count = 0;
    bool is_active = false;
    bool has_cpu_usage = false;
    bool has_memory_current = false;
    bool has_io_read_bytes = false;
    bool has_io_write_bytes = false;
    bool has_active_enter_timestamp = false;
    bool has_process_count = false;
    bool has_thread_count = false;
};

class SystemdDBus : public QObject
{
    Q_OBJECT

public:
    explicit SystemdDBus(QObject *parent = nullptr);

    void switchBus(bool useSystemBus);
    bool isSystemBus() const;

    QList<SystemdUnit> fetchAllServices();
    QString getUnitFileState(const QString &serviceName);
    QString getUnitFragmentPath(const QDBusObjectPath &unitObjectPath);
    ServiceResourceUsage fetchServiceResourceUsage(const SystemdUnit &unit);

    OperationResult startService(const QString &serviceName);
    OperationResult stopService(const QString &serviceName);
    OperationResult restartService(const QString &serviceName);
    OperationResult enableService(const QString &serviceName);
    OperationResult disableService(const QString &serviceName);
    OperationResult maskService(const QString &serviceName);
    OperationResult unmaskService(const QString &serviceName);
    OperationResult reloadDaemon();

private:
    void initInterface();
    OperationResult callMethod(const QString &method, const QVariant &arg1 = {},
                               const QVariant &arg2 = {});

    QDBusInterface *m_systemd = nullptr;
    bool m_useSystemBus = false;
};

#endif // SYSTEMD_DBUS_H
