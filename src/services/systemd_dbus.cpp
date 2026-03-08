#include "systemd_dbus.h"

static const QString SYSTEMD_SERVICE   = QStringLiteral("org.freedesktop.systemd1");
static const QString SYSTEMD_PATH      = QStringLiteral("/org/freedesktop/systemd1");
static const QString SYSTEMD_INTERFACE = QStringLiteral("org.freedesktop.systemd1.Manager");

SystemdDBus::SystemdDBus(QObject *parent) : QObject(parent) {
    initInterface();
}

void SystemdDBus::initInterface() {
    delete m_systemd;
    QDBusConnection bus = m_useSystemBus
        ? QDBusConnection::systemBus()
        : QDBusConnection::sessionBus();
    m_systemd = new QDBusInterface(SYSTEMD_SERVICE, SYSTEMD_PATH, SYSTEMD_INTERFACE, bus, this);
}

void SystemdDBus::switchBus(bool useSystemBus) {
    if (m_useSystemBus == useSystemBus)
        return;
    m_useSystemBus = useSystemBus;
    initInterface();
}

bool SystemdDBus::isSystemBus() const {
    return m_useSystemBus;
}

QList<SystemdUnit> SystemdDBus::fetchAllServices() {
    QDBusReply<QList<SystemdUnit>> reply = m_systemd->call("ListUnits");
    if (!reply.isValid())
        return {};

    QList<SystemdUnit> servicesOnly;
    for (const auto &unit : reply.value()) {
        if (unit.name.endsWith(".service")) {
            SystemdUnit svc = unit;
            svc.is_system = m_useSystemBus;
            svc.enabled_state = getUnitFileState(svc.name);
            servicesOnly.append(svc);
        }
    }
    return servicesOnly;
}

QString SystemdDBus::getUnitFileState(const QString &serviceName) {
    QDBusMessage msg = m_systemd->call("GetUnitFileState", serviceName);
    if (msg.type() == QDBusMessage::ReplyMessage && !msg.arguments().isEmpty())
        return msg.arguments().first().toString();
    return "unknown";
}

QString SystemdDBus::getUnitFragmentPath(const QDBusObjectPath &unitObjectPath) {
    if (!m_systemd)
        return {};

    QDBusInterface unitIface(
        SYSTEMD_SERVICE,
        unitObjectPath.path(),
        QStringLiteral("org.freedesktop.systemd1.Unit"),
        m_systemd->connection()
    );

    QVariant value = unitIface.property("FragmentPath");
    if (!value.isValid())
        return {};
    return value.toString();
}

OperationResult SystemdDBus::startService(const QString &serviceName) {
    return callMethod("StartUnit", serviceName, "replace");
}

OperationResult SystemdDBus::stopService(const QString &serviceName) {
    return callMethod("StopUnit", serviceName, "replace");
}

OperationResult SystemdDBus::restartService(const QString &serviceName) {
    return callMethod("RestartUnit", serviceName, "replace");
}

OperationResult SystemdDBus::enableService(const QString &serviceName) {
    QStringList units = {serviceName};
    QDBusMessage call = QDBusMessage::createMethodCall(SYSTEMD_SERVICE, SYSTEMD_PATH, SYSTEMD_INTERFACE, "EnableUnitFiles");
    call.setArguments({QVariant::fromValue(units), false, true});
    call.setInteractiveAuthorizationAllowed(true);
    QDBusMessage msg = m_systemd->connection().call(call);
    if (msg.type() == QDBusMessage::ErrorMessage)
        return {false, msg.errorMessage()};
    return {true, "Service enabled successfully"};
}

OperationResult SystemdDBus::disableService(const QString &serviceName) {
    QStringList units = {serviceName};
    QDBusMessage call = QDBusMessage::createMethodCall(SYSTEMD_SERVICE, SYSTEMD_PATH, SYSTEMD_INTERFACE, "DisableUnitFiles");
    call.setArguments({QVariant::fromValue(units), false});
    call.setInteractiveAuthorizationAllowed(true);
    QDBusMessage msg = m_systemd->connection().call(call);
    if (msg.type() == QDBusMessage::ErrorMessage)
        return {false, msg.errorMessage()};
    return {true, "Service disabled successfully"};
}

OperationResult SystemdDBus::maskService(const QString &serviceName) {
    QStringList units = {serviceName};
    QDBusMessage call = QDBusMessage::createMethodCall(SYSTEMD_SERVICE, SYSTEMD_PATH, SYSTEMD_INTERFACE, "MaskUnitFiles");
    call.setArguments({QVariant::fromValue(units), false, true});
    call.setInteractiveAuthorizationAllowed(true);
    QDBusMessage msg = m_systemd->connection().call(call);
    if (msg.type() == QDBusMessage::ErrorMessage)
        return {false, msg.errorMessage()};
    return {true, "Service masked successfully"};
}

OperationResult SystemdDBus::unmaskService(const QString &serviceName) {
    QStringList units = {serviceName};
    QDBusMessage call = QDBusMessage::createMethodCall(SYSTEMD_SERVICE, SYSTEMD_PATH, SYSTEMD_INTERFACE, "UnmaskUnitFiles");
    call.setArguments({QVariant::fromValue(units), false});
    call.setInteractiveAuthorizationAllowed(true);
    QDBusMessage msg = m_systemd->connection().call(call);
    if (msg.type() == QDBusMessage::ErrorMessage)
        return {false, msg.errorMessage()};
    return {true, "Service unmasked successfully"};
}

OperationResult SystemdDBus::reloadDaemon() {
    QDBusMessage call = QDBusMessage::createMethodCall(SYSTEMD_SERVICE, SYSTEMD_PATH, SYSTEMD_INTERFACE, "Reload");
    call.setInteractiveAuthorizationAllowed(true);
    QDBusMessage msg = m_systemd->connection().call(call);
    if (msg.type() == QDBusMessage::ErrorMessage)
        return {false, msg.errorMessage()};
    return {true, "Daemon reloaded successfully"};
}

OperationResult SystemdDBus::callMethod(const QString &method, const QVariant &arg1, const QVariant &arg2) {
    QDBusMessage call = QDBusMessage::createMethodCall(SYSTEMD_SERVICE, SYSTEMD_PATH, SYSTEMD_INTERFACE, method);
    if (arg2.isValid())
        call.setArguments({arg1, arg2});
    else if (arg1.isValid())
        call.setArguments({arg1});
    call.setInteractiveAuthorizationAllowed(true);
    QDBusMessage msg = m_systemd->connection().call(call);

    if (msg.type() == QDBusMessage::ErrorMessage)
        return {false, msg.errorMessage()};
    return {true, method + " completed successfully"};
}