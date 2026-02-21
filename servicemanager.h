#ifndef SERVICEMANAGER_H
#define SERVICEMANAGER_H

#include <QObject>
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

// <--- ADD THESE TWO LINES SO MAIN.CPP CAN SEE THEM
QDBusArgument &operator<<(QDBusArgument &argument, const SystemdUnit &unit);
const QDBusArgument &operator>>(const QDBusArgument &argument, SystemdUnit &unit);

class ServiceManager : public QObject
{
    Q_OBJECT
public:
    explicit ServiceManager(QObject *parent = nullptr);
    QList<SystemdUnit> getAllServices();

private:
    QDBusInterface *systemd;
};

#endif // SERVICEMANAGER_H