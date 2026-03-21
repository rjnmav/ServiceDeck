#include "servicedetailpanel.h"

#include <cstdint>
#include <QDateTime>
#include <QFont>
#include <QFormLayout>
#include <QLocale>
#include <QThread>
#include <QTextCursor>
#include <QWidget>

#include <algorithm>

#ifdef SERVICEDECK_HAS_SD_JOURNAL
#include <systemd/sd-journal.h>
#endif

namespace {

QString unavailableValue()
{
    return QStringLiteral("N/A");
}

QString formatDataSize(quint64 bytes)
{
    return QLocale().formattedDataSize(static_cast<qint64>(bytes), 1, QLocale::DataSizeIecFormat);
}

QString formatRunningSince(quint64 timestampUsec)
{
    const QDateTime startTime = QDateTime::fromMSecsSinceEpoch(static_cast<qint64>(timestampUsec / 1000)).toLocalTime();
    return QLocale().toString(startTime, QLocale::ShortFormat);
}

QString formatDuration(qint64 totalSeconds)
{
    const qint64 safeSeconds = std::max<qint64>(0, totalSeconds);
    const qint64 days = safeSeconds / 86400;
    const qint64 hours = (safeSeconds % 86400) / 3600;
    const qint64 minutes = (safeSeconds % 3600) / 60;
    const qint64 seconds = safeSeconds % 60;

    if (days > 0)
        return QStringLiteral("%1d %2h %3m %4s").arg(days).arg(hours).arg(minutes).arg(seconds);
    if (hours > 0)
        return QStringLiteral("%1h %2m %3s").arg(hours).arg(minutes).arg(seconds);
    if (minutes > 0)
        return QStringLiteral("%1m %2s").arg(minutes).arg(seconds);
    return QStringLiteral("%1s").arg(seconds);
}

int logicalCpuCount()
{
    const int threadCount = QThread::idealThreadCount();
    return threadCount > 0 ? threadCount : 1;
}

#ifdef SERVICEDECK_HAS_SD_JOURNAL
QString journalFieldValue(sd_journal *journal, const char *fieldName)
{
    const void *data = nullptr;
    size_t length = 0;
    const int result = sd_journal_get_data(journal, fieldName, &data, &length);
    if (result < 0 || data == nullptr || length == 0)
        return {};

    const int prefixLength = qstrlen(fieldName) + 1;
    if (static_cast<int>(length) <= prefixLength)
        return {};

    const char *value = static_cast<const char *>(data) + prefixLength;
    return QString::fromUtf8(value, static_cast<int>(length) - prefixLength);
}

QString journalPriorityLabel(const QString &priority)
{
    bool ok = false;
    const int level = priority.toInt(&ok);
    if (!ok) return QStringLiteral("info");

    switch (level) {
    case 0: return QStringLiteral("emerg");
    case 1: return QStringLiteral("alert");
    case 2: return QStringLiteral("crit");
    case 3: return QStringLiteral("err");
    case 4: return QStringLiteral("warning");
    case 5: return QStringLiteral("notice");
    case 6: return QStringLiteral("info");
    case 7: return QStringLiteral("debug");
    default: return QStringLiteral("info");
    }
}
#endif

}

ServiceDetailPanel::ServiceDetailPanel(QWidget *parent)
    : QDockWidget("Service Details", parent)
{
    setObjectName("detailPanel");
    setMinimumHeight(200);
    setFeatures(QDockWidget::DockWidgetMovable | QDockWidget::DockWidgetClosable | QDockWidget::DockWidgetVerticalTitleBar);
    setupUi();
}

void ServiceDetailPanel::setupUi() {
    m_tabWidget = new QTabWidget(this);
    m_tabWidget->setObjectName("detailTabs");
    m_logRefreshTimer = new QTimer(this);
    m_logRefreshTimer->setInterval(5000);
    connect(m_logRefreshTimer, &QTimer::timeout, this, &ServiceDetailPanel::refreshServiceLogs);
    m_resourceRefreshTimer = new QTimer(this);
    m_resourceRefreshTimer->setInterval(2000);
    connect(m_resourceRefreshTimer, &QTimer::timeout, this, &ServiceDetailPanel::refreshResourceUsage);
    m_resourceDbus = new SystemdDBus(this);

    // ─── Properties tab ───
    QWidget *propsWidget = new QWidget();
    QFormLayout *propsLayout = new QFormLayout(propsWidget);
    propsLayout->setContentsMargins(16, 16, 16, 16);
    propsLayout->setSpacing(8);

    auto makeLabel = [](const QString &text = "-") {
        QLabel *lbl = new QLabel(text);
        lbl->setTextInteractionFlags(Qt::TextSelectableByMouse);
        return lbl;
    };

    m_nameValue    = makeLabel();
    m_descValue    = makeLabel();
    m_activeValue  = makeLabel();
    m_subStateValue = makeLabel();
    m_loadValue    = makeLabel();
    m_enabledValue = makeLabel();
    m_pathValue    = makeLabel();

    QFont boldFont;
    boldFont.setBold(true);

    auto addRow = [&](const QString &label, QLabel *value) {
        QLabel *lblWidget = new QLabel(label);
        lblWidget->setFont(boldFont);
        propsLayout->addRow(lblWidget, value);
    };

    addRow("Service Name:", m_nameValue);
    addRow("Description:",  m_descValue);
    addRow("Active State:", m_activeValue);
    addRow("Sub State:",    m_subStateValue);
    addRow("Load State:",   m_loadValue);
    addRow("Enabled:",      m_enabledValue);
    addRow("Unit Path:",    m_pathValue);

    m_tabWidget->addTab(propsWidget, "Properties");

    // ─── Unit file tab ───
    m_unitFileEdit = new QTextEdit();
    m_unitFileEdit->setReadOnly(true);
    m_unitFileEdit->setObjectName("unitFileViewer");
    QFont monoFont("Monospace", 10);
    monoFont.setStyleHint(QFont::Monospace);
    m_unitFileEdit->setFont(monoFont);

    m_tabWidget->addTab(m_unitFileEdit, "Unit File");

    // ─── Service Log tab ───
    m_serviceLogEdit = new QTextEdit();
    m_serviceLogEdit->setReadOnly(true);
    m_serviceLogEdit->setObjectName("serviceLogViewer");
    m_serviceLogEdit->setFont(monoFont);

    m_tabWidget->addTab(m_serviceLogEdit, "Service Logs");

    // ─── Resource usage tab ───
    QWidget *resourceWidget = new QWidget();
    QFormLayout *resourceLayout = new QFormLayout(resourceWidget);
    resourceLayout->setContentsMargins(16, 16, 16, 16);
    resourceLayout->setSpacing(8);

    auto addResourceRow = [&](const QString &label, QLabel **valueLabel) {
        *valueLabel = makeLabel();
        QLabel *lblWidget = new QLabel(label);
        lblWidget->setFont(boldFont);
        resourceLayout->addRow(lblWidget, *valueLabel);
    };

    addResourceRow("Running Since:", &m_runningSinceValue);
    addResourceRow("Uptime:", &m_uptimeValue);
    addResourceRow("CPU:", &m_cpuUsageValue);
    addResourceRow("Memory:", &m_memoryUsageValue);
    addResourceRow("Disk Read:", &m_diskReadValue);
    addResourceRow("Disk Write:", &m_diskWriteValue);
    addResourceRow("Processes:", &m_processCountValue);
    addResourceRow("Threads:", &m_threadCountValue);

    m_tabWidget->addTab(resourceWidget, "Resource Usage");

    setWidget(m_tabWidget);
}

void ServiceDetailPanel::showServiceDetails(const SystemdUnit &unit) {
    m_currentUnit = unit;
    resetResourceUsageState();

    m_nameValue->setText(unit.name);
    m_descValue->setText(unit.description);
    m_activeValue->setText(unit.active_state.toUpper());
    m_subStateValue->setText(unit.sub_state);
    m_loadValue->setText(unit.load_state);
    m_enabledValue->setText(unit.enabled_state.toUpper());
    QString actualPath = unit.unit_file_path;
    if (actualPath.isEmpty() && !unit.unit_path.path().isEmpty()) {
        m_resourceDbus->switchBus(unit.is_system);
        actualPath = m_resourceDbus->getUnitFragmentPath(unit.unit_path);
    }
    m_pathValue->setText(actualPath.isEmpty() ? "-" : actualPath);

    // Color-code active state label
    if (unit.active_state == "active")
        m_activeValue->setStyleSheet("color: #4CAF50; font-weight: bold;");
    else if (unit.active_state == "failed")
        m_activeValue->setStyleSheet("color: #F44336; font-weight: bold;");
    else if (unit.active_state == "inactive")
        m_activeValue->setStyleSheet("color: #9E9E9E; font-weight: bold;");
    else
        m_activeValue->setStyleSheet("color: #FFA726; font-weight: bold;");

    // Color-code enabled label
    if (unit.enabled_state == "enabled")
        m_enabledValue->setStyleSheet("color: #4CAF50; font-weight: bold;");
    else if (unit.enabled_state == "disabled")
        m_enabledValue->setStyleSheet("color: #F44336; font-weight: bold;");
    else if (unit.enabled_state == "masked")
        m_enabledValue->setStyleSheet("color: #795548; font-weight: bold;");
    else
        m_enabledValue->setStyleSheet("color: #9E9E9E;");

    refreshServiceLogs();
    m_logRefreshTimer->start();
    refreshResourceUsage();
    m_resourceRefreshTimer->start();
    show();
}

void ServiceDetailPanel::setUnitFileContent(const QString &content) {
    m_unitFileEdit->setPlainText(content);
}

void ServiceDetailPanel::clear() {
    m_logRefreshTimer->stop();
    m_resourceRefreshTimer->stop();
    m_currentUnit = {};
    m_nameValue->setText("-");
    m_descValue->setText("-");
    m_activeValue->setText("-");
    m_activeValue->setStyleSheet("");
    m_subStateValue->setText("-");
    m_loadValue->setText("-");
    m_enabledValue->setText("-");
    m_enabledValue->setStyleSheet("");
    m_pathValue->setText("-");
    m_unitFileEdit->clear();
    m_serviceLogEdit->clear();
    resetResourceUsageState();
}

void ServiceDetailPanel::refreshServiceLogs()
{
    m_serviceLogEdit->setPlainText(loadServiceLogs());
    QTextCursor cursor = m_serviceLogEdit->textCursor();
    cursor.movePosition(QTextCursor::End);
    m_serviceLogEdit->setTextCursor(cursor);
}

QString ServiceDetailPanel::loadServiceLogs() const
{
    if (m_currentUnit.name.isEmpty())
        return QStringLiteral("Select a service to view recent logs.");

#ifndef SERVICEDECK_HAS_SD_JOURNAL
    return QStringLiteral(
        "Service log support requires the systemd development headers.\n"
        "Install the package that provides <systemd/sd-journal.h> and rebuild ServiceDeck.");
#else
    sd_journal *journal = nullptr;
    const int openFlags = SD_JOURNAL_LOCAL_ONLY | (m_currentUnit.is_system ? SD_JOURNAL_SYSTEM : SD_JOURNAL_CURRENT_USER);
    int result = sd_journal_open(&journal, openFlags);
    if (result < 0)
        return QStringLiteral("Unable to open the journal for %1 (error %2).")
            .arg(m_currentUnit.name)
            .arg(result);

    struct JournalCloser {
        ~JournalCloser() {
            if (handle != nullptr)
                sd_journal_close(handle);
        }
        sd_journal *handle = nullptr;
    } closer{journal};

    const QByteArray matchField = (m_currentUnit.is_system
        ? QByteArrayLiteral("_SYSTEMD_UNIT=")
        : QByteArrayLiteral("_SYSTEMD_USER_UNIT=")) + m_currentUnit.name.toUtf8();
    result = sd_journal_add_match(journal, matchField.constData(), 0);
    if (result < 0)
        return QStringLiteral("Unable to filter journal entries for %1 (error %2).")
            .arg(m_currentUnit.name)
            .arg(result);

    result = sd_journal_seek_tail(journal);
    if (result < 0)
        return QStringLiteral("Unable to seek journal entries for %1 (error %2).")
            .arg(m_currentUnit.name)
            .arg(result);

    QStringList entries;
    entries.reserve(200);

    for (int count = 0; count < 200; ++count) {
        result = sd_journal_previous(journal);
        if (result < 0) {
            return QStringLiteral("Unable to read journal entries for %1 (error %2).")
                .arg(m_currentUnit.name)
                .arg(result);
        }
        if (result == 0)
            break;

        uint64_t usec = 0;
        sd_journal_get_realtime_usec(journal, &usec);
        const QDateTime timestamp = QDateTime::fromMSecsSinceEpoch(static_cast<qint64>(usec / 1000)).toLocalTime();
        const QString message = journalFieldValue(journal, "MESSAGE");
        if (message.isEmpty())
            continue;

        const QString priority = journalPriorityLabel(journalFieldValue(journal, "PRIORITY"));
        const QString identifier = journalFieldValue(journal, "SYSLOG_IDENTIFIER");
        const QString source = identifier.isEmpty() ? m_currentUnit.name : identifier;

        entries.prepend(QStringLiteral("[%1] [%2] %3: %4")
                            .arg(timestamp.toString(Qt::ISODate))
                            .arg(priority)
                            .arg(source)
                            .arg(message));
    }

    if (entries.isEmpty())
        return QStringLiteral("No recent journal entries found for %1.").arg(m_currentUnit.name);

    return entries.join(QLatin1Char('\n'));
#endif
}

void ServiceDetailPanel::refreshResourceUsage()
{
    if (m_currentUnit.name.isEmpty()) {
        resetResourceUsageState();
        return;
    }

    m_resourceDbus->switchBus(m_currentUnit.is_system);
    const ServiceResourceUsage usage = m_resourceDbus->fetchServiceResourceUsage(m_currentUnit);

    if (usage.is_active && usage.has_active_enter_timestamp) {
        const QDateTime startTime = QDateTime::fromMSecsSinceEpoch(static_cast<qint64>(usage.active_enter_timestamp_usec / 1000)).toLocalTime();
        const qint64 uptimeSeconds = startTime.secsTo(QDateTime::currentDateTime());
        m_runningSinceValue->setText(formatRunningSince(usage.active_enter_timestamp_usec));
        m_uptimeValue->setText(formatDuration(uptimeSeconds));
    } else {
        m_runningSinceValue->setText(unavailableValue());
        m_uptimeValue->setText(unavailableValue());
    }

    if (usage.has_memory_current)
        m_memoryUsageValue->setText(formatDataSize(usage.memory_current));
    else
        m_memoryUsageValue->setText(unavailableValue());

    if (usage.has_process_count)
        m_processCountValue->setText(QString::number(usage.process_count));
    else
        m_processCountValue->setText(unavailableValue());

    if (usage.has_thread_count)
        m_threadCountValue->setText(QString::number(usage.thread_count));
    else
        m_threadCountValue->setText(unavailableValue());

    const qint64 elapsedMs = m_resourceElapsedTimer.isValid() ? m_resourceElapsedTimer.restart() : 0;
    if (!m_resourceElapsedTimer.isValid())
        m_resourceElapsedTimer.start();

    const bool hasElapsedInterval = elapsedMs > 0;
    const double elapsedSeconds = static_cast<double>(elapsedMs) / 1000.0;

    if (usage.has_cpu_usage && m_hasPreviousCpuSample && hasElapsedInterval) {
        const quint64 cpuDelta = usage.cpu_usage_nsec >= m_previousCpuUsageNs
            ? usage.cpu_usage_nsec - m_previousCpuUsageNs
            : 0;
        const double aggregateCpuPercent = (static_cast<double>(cpuDelta) / (elapsedSeconds * 1000000000.0)) * 100.0;
        const double normalizedCpuPercent = aggregateCpuPercent / static_cast<double>(logicalCpuCount());
        const double clampedCpuPercent = std::clamp(normalizedCpuPercent, 0.0, 100.0);
        m_cpuUsageValue->setText(QString::number(clampedCpuPercent, 'f', 1) + '%');
    } else {
        m_cpuUsageValue->setText(unavailableValue());
    }

    if (usage.has_io_read_bytes && m_hasPreviousReadSample && hasElapsedInterval) {
        const quint64 readDelta = usage.io_read_bytes >= m_previousReadBytes
            ? usage.io_read_bytes - m_previousReadBytes
            : 0;
        const quint64 readRate = static_cast<quint64>(readDelta / elapsedSeconds);
        m_diskReadValue->setText(formatDataSize(readRate) + QStringLiteral("/s"));
    } else {
        m_diskReadValue->setText(unavailableValue());
    }

    if (usage.has_io_write_bytes && m_hasPreviousWriteSample && hasElapsedInterval) {
        const quint64 writeDelta = usage.io_write_bytes >= m_previousWriteBytes
            ? usage.io_write_bytes - m_previousWriteBytes
            : 0;
        const quint64 writeRate = static_cast<quint64>(writeDelta / elapsedSeconds);
        m_diskWriteValue->setText(formatDataSize(writeRate) + QStringLiteral("/s"));
    } else {
        m_diskWriteValue->setText(unavailableValue());
    }

    if (usage.has_cpu_usage) {
        m_previousCpuUsageNs = usage.cpu_usage_nsec;
        m_hasPreviousCpuSample = true;
    } else {
        m_hasPreviousCpuSample = false;
    }

    if (usage.has_io_read_bytes) {
        m_previousReadBytes = usage.io_read_bytes;
        m_hasPreviousReadSample = true;
    } else {
        m_hasPreviousReadSample = false;
    }

    if (usage.has_io_write_bytes) {
        m_previousWriteBytes = usage.io_write_bytes;
        m_hasPreviousWriteSample = true;
    } else {
        m_hasPreviousWriteSample = false;
    }
}

void ServiceDetailPanel::resetResourceUsageState()
{
    m_runningSinceValue->setText("-");
    m_uptimeValue->setText("-");
    m_cpuUsageValue->setText("-");
    m_memoryUsageValue->setText("-");
    m_diskReadValue->setText("-");
    m_diskWriteValue->setText("-");
    m_processCountValue->setText("-");
    m_threadCountValue->setText("-");
    m_previousCpuUsageNs = 0;
    m_previousReadBytes = 0;
    m_previousWriteBytes = 0;
    m_hasPreviousCpuSample = false;
    m_hasPreviousReadSample = false;
    m_hasPreviousWriteSample = false;
    m_resourceElapsedTimer.invalidate();
}
