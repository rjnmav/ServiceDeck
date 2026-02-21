#ifndef SYSTEMD_DBUS_H
#define SYSTEMD_DBUS_H

#include <QObject>
#include <QtDBus/QtDBus>
#include "unit_model.h"

class SystemdDBus : public QObject
{
    Q_OBJECT
public:
    explicit SystemdDBus(QObject *parent = nullptr);
    QList<SystemdUnit> fetchAllServices();

private:
    QDBusInterface *systemd;
};

#endif // SYSTEMD_DBUS_H