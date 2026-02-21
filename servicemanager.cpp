#include "servicemanager.h"
#include <QDebug>

// CHANGE 1: Return type must be 'const QDBusArgument &'
const QDBusArgument &operator>>(const QDBusArgument &argument, SystemdUnit &unit) {
    argument.beginStructure();
    argument >> unit.name >> unit.description >> unit.load_state >> unit.active_state
             >> unit.sub_state >> unit.follower >> unit.unit_path >> unit.job_id
             >> unit.job_type >> unit.job_path;
    argument.endStructure();
    return argument;
}

// CHANGE 2: This one was mostly correct, just ensure it matches the header
QDBusArgument &operator<<(QDBusArgument &argument, const SystemdUnit &unit) {
    argument.beginStructure();
    argument << unit.name << unit.description << unit.load_state << unit.active_state
             << unit.sub_state << unit.follower << unit.unit_path << unit.job_id
             << unit.job_type << unit.job_path;
    argument.endStructure();
    return argument;
}

ServiceManager::ServiceManager(QObject *parent) : QObject(parent)
{
    systemd = new QDBusInterface(
        "org.freedesktop.systemd1",
        "/org/freedesktop/systemd1",
        "org.freedesktop.systemd1.Manager",
        QDBusConnection::sessionBus(),
        this
    );
}

QList<SystemdUnit> ServiceManager::getAllServices()
{
    QDBusReply<QList<SystemdUnit>> reply = systemd->call("ListUnits");

    if (!reply.isValid()) {
        qWarning() << "D-Bus Error:" << reply.error().message();
        return QList<SystemdUnit>();
    }

    QList<SystemdUnit> allUnits = reply.value();
    QList<SystemdUnit> servicesOnly;

    for(const auto &unit : allUnits) {
        if (unit.name.endsWith(".service")) {
            servicesOnly.append(unit);
        }
    }
    return servicesOnly;
}