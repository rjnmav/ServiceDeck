#ifndef UNIT_MODEL_H
#define UNIT_MODEL_H

#include <QtDBus/QtDBus>

struct SystemdUnit {
    QString name;
    QString description;
    QString load_state;
    QString active_state;
    QString sub_state;
    QString follower;
    QDBusObjectPath unit_path;
    uint job_id;
    QString job_type;
    QDBusObjectPath job_path;
};

Q_DECLARE_METATYPE(SystemdUnit)
Q_DECLARE_METATYPE(QList<SystemdUnit>)

QDBusArgument &operator<<(QDBusArgument &argument, const SystemdUnit &unit);
const QDBusArgument &operator>>(const QDBusArgument &argument, SystemdUnit &unit);

#endif