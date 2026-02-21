#include "systemd_dbus.h"

SystemdDBus::SystemdDBus(QObject *parent) : QObject(parent) {
    systemd = new QDBusInterface("org.freedesktop.systemd1", "/org/freedesktop/systemd1",
                                 "org.freedesktop.systemd1.Manager", QDBusConnection::sessionBus(), this);
}

QList<SystemdUnit> SystemdDBus::fetchAllServices() {
    QDBusReply<QList<SystemdUnit>> reply = systemd->call("ListUnits");
    if (!reply.isValid()) return QList<SystemdUnit>();

    QList<SystemdUnit> servicesOnly;
    for(const auto &unit : reply.value()) {
        // We can access unit.name because systemd_dbus.h included unit_model.h
        if (unit.name.endsWith(".service")) {
            servicesOnly.append(unit);
        }
    }
    return servicesOnly;
}