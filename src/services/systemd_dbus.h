#ifndef SYSTEMD_DBUS_H
#define SYSTEMD_DBUS_H

#include <QObject>
#include <QtDBus/QtDBus>
#include "unit_model.h"

struct OperationResult {
    bool success;
    QString message;
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