#include "systemd_dbus.h"

#include <QHash>
#include <QSet>
#include <QFile>
#include <QTextStream>

#include <limits>

static const QString SYSTEMD_SERVICE   = QStringLiteral("org.freedesktop.systemd1");
static const QString SYSTEMD_PATH      = QStringLiteral("/org/freedesktop/systemd1");
static const QString SYSTEMD_INTERFACE = QStringLiteral("org.freedesktop.systemd1.Manager");

namespace {

constexpr quint64 kUnavailableCounter = std::numeric_limits<quint64>::max();

struct UnitFileEntry {
    QString path;
    QString state;
};

QString unitNameFromPath(const QString &path)
{
    const int slashIndex = path.lastIndexOf(QLatin1Char('/'));
    return slashIndex >= 0 ? path.mid(slashIndex + 1) : path;
}

bool propertyToUInt64(const QVariant &value, quint64 *result)
{
    if (!value.isValid() || result == nullptr)
        return false;

    bool ok = false;
    const qulonglong rawValue = value.toULongLong(&ok);
    if (!ok)
        return false;

    *result = static_cast<quint64>(rawValue);
    return true;
}

int countProcesses(const QDBusMessage &reply, bool *ok)
{
    if (ok != nullptr)
        *ok = false;

    if (reply.type() != QDBusMessage::ReplyMessage || reply.arguments().isEmpty())
        return 0;

    const QDBusArgument argument = qvariant_cast<QDBusArgument>(reply.arguments().constFirst());
    if (argument.currentType() != QDBusArgument::ArrayType)
        return 0;

    int count = 0;
    argument.beginArray();
    while (!argument.atEnd()) {
        QString controlGroup;
        uint pid = 0;
        QString command;
        argument.beginStructure();
        argument >> controlGroup >> pid >> command;
        argument.endStructure();
        ++count;
    }
    argument.endArray();

    if (ok != nullptr)
        *ok = true;
    return count;
}

QList<UnitFileEntry> parseUnitFileEntries(const QDBusMessage &reply, bool *ok)
{
    if (ok != nullptr)
        *ok = false;

    if (reply.type() != QDBusMessage::ReplyMessage || reply.arguments().isEmpty())
        return {};

    const QDBusArgument argument = qvariant_cast<QDBusArgument>(reply.arguments().constFirst());
    if (argument.currentType() != QDBusArgument::ArrayType)
        return {};

    QList<UnitFileEntry> entries;
    argument.beginArray();
    while (!argument.atEnd()) {
        UnitFileEntry entry;
        argument.beginStructure();
        argument >> entry.path >> entry.state;
        argument.endStructure();
        entries.append(entry);
    }
    argument.endArray();

    if (ok != nullptr)
        *ok = true;
    return entries;
}

static QString extractDescription(const QString &unitFilePath) {
    QFile file(unitFilePath);
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text))
        return {};

    QTextStream in(&file);
    while (!in.atEnd()) {
        QString line = in.readLine().trimmed();
        if (line.startsWith(QStringLiteral("Description="))) {
            return line.mid(12).trimmed(); // 12 is length of "Description="
        }
    }
    return {};
}

SystemdUnit makeInactiveUnit(const QString &serviceName, const QString &enabledState, const QString &unitFilePath, bool isSystem)
{
    SystemdUnit unit;
    unit.name = serviceName;
    unit.load_state = QStringLiteral("loaded");
    unit.active_state = QStringLiteral("inactive");
    unit.sub_state = QStringLiteral("dead");
    unit.enabled_state = enabledState;
    unit.unit_file_path = unitFilePath;
    unit.is_system = isSystem;
    unit.description = extractDescription(unitFilePath);
    return unit;
}

}

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
    QHash<QString, SystemdUnit> loadedServices;
    QDBusReply<QList<SystemdUnit>> unitsReply = m_systemd->call("ListUnits");
    if (unitsReply.isValid()) {
        for (const auto &unit : unitsReply.value()) {
            if (!unit.name.endsWith(QStringLiteral(".service")))
                continue;

            SystemdUnit service = unit;
            service.is_system = m_useSystemBus;
            loadedServices.insert(service.name, service);
        }
    }

    bool parsedUnitFiles = false;
    const QList<UnitFileEntry> unitFiles = parseUnitFileEntries(m_systemd->call("ListUnitFiles"), &parsedUnitFiles);
    if (!parsedUnitFiles) {
        QList<SystemdUnit> fallbackServices = loadedServices.values();
        for (SystemdUnit &service : fallbackServices)
            service.enabled_state = getUnitFileState(service.name);
        return fallbackServices;
    }

    QList<SystemdUnit> services;
    QSet<QString> seenServices;
    for (const UnitFileEntry &entry : unitFiles) {
        const QString serviceName = unitNameFromPath(entry.path);
        if (!serviceName.endsWith(QStringLiteral(".service")) || seenServices.contains(serviceName))
            continue;

        if (loadedServices.contains(serviceName)) {
            SystemdUnit service = loadedServices.take(serviceName);
            service.enabled_state = entry.state;
            service.unit_file_path = entry.path;
            services.append(service);
        } else {
            services.append(makeInactiveUnit(serviceName, entry.state, entry.path, m_useSystemBus));
        }

        seenServices.insert(serviceName);
    }

    for (auto it = loadedServices.cbegin(); it != loadedServices.cend(); ++it) {
        if (seenServices.contains(it.key()))
            continue;

        SystemdUnit service = it.value();
        service.enabled_state = getUnitFileState(service.name);
        services.append(service);
    }

    return services;
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

ServiceResourceUsage SystemdDBus::fetchServiceResourceUsage(const SystemdUnit &unit) {
    ServiceResourceUsage usage;

    if (!m_systemd || unit.unit_path.path().isEmpty())
        return usage;

    QDBusInterface serviceIface(
        SYSTEMD_SERVICE,
        unit.unit_path.path(),
        QStringLiteral("org.freedesktop.systemd1.Service"),
        m_systemd->connection()
    );

    if (!serviceIface.isValid())
        return usage;

    QDBusInterface unitIface(
        SYSTEMD_SERVICE,
        unit.unit_path.path(),
        QStringLiteral("org.freedesktop.systemd1.Unit"),
        m_systemd->connection()
    );

    if (!unitIface.isValid())
        return usage;

    usage.is_active = unitIface.property("ActiveState").toString() == QStringLiteral("active");

    quint64 rawValue = 0;
    if (propertyToUInt64(serviceIface.property("CPUUsageNSec"), &rawValue) && rawValue != kUnavailableCounter) {
        usage.cpu_usage_nsec = rawValue;
        usage.has_cpu_usage = true;
    }
    if (propertyToUInt64(serviceIface.property("MemoryCurrent"), &rawValue) && rawValue != kUnavailableCounter) {
        usage.memory_current = rawValue;
        usage.has_memory_current = true;
    }
    if (propertyToUInt64(serviceIface.property("IOReadBytes"), &rawValue) && rawValue != kUnavailableCounter) {
        usage.io_read_bytes = rawValue;
        usage.has_io_read_bytes = true;
    }
    if (propertyToUInt64(serviceIface.property("IOWriteBytes"), &rawValue) && rawValue != kUnavailableCounter) {
        usage.io_write_bytes = rawValue;
        usage.has_io_write_bytes = true;
    }
    if (propertyToUInt64(serviceIface.property("TasksCurrent"), &rawValue) && rawValue != kUnavailableCounter) {
        usage.thread_count = static_cast<int>(qMin<quint64>(rawValue, static_cast<quint64>(std::numeric_limits<int>::max())));
        usage.has_thread_count = true;
    }
    if (propertyToUInt64(unitIface.property("ActiveEnterTimestamp"), &rawValue) && rawValue != 0 && rawValue != kUnavailableCounter) {
        usage.active_enter_timestamp_usec = rawValue;
        usage.has_active_enter_timestamp = true;
    }

    bool hasProcessCount = false;
    const int processCount = countProcesses(serviceIface.call("GetProcesses"), &hasProcessCount);
    if (hasProcessCount) {
        usage.process_count = processCount;
        usage.has_process_count = true;
    }

    return usage;
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
    return {true, method + " executed successfully"};
}
