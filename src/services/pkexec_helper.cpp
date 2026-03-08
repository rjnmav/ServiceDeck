#include "pkexec_helper.h"
#include <QProcess>

PkexecHelper::PkexecHelper(QObject *parent) : QObject(parent) {}

PkexecResult PkexecHelper::writeSystemUnitFile(const QString &fileName, const QString &content) {
    QString path = "/etc/systemd/system/" + fileName;
    QStringList args = {"tee", path};

    QProcess process;
    process.setProgram("pkexec");
    process.setArguments(args);
    process.start();

    if (!process.waitForStarted(5000))
        return {false, "", "Failed to start pkexec"};

    process.write(content.toUtf8());
    process.closeWriteChannel();

    if (!process.waitForFinished(30000))
        return {false, "", "pkexec timed out"};

    QString stdoutStr = QString::fromUtf8(process.readAllStandardOutput()).trimmed();
    QString stderrStr = QString::fromUtf8(process.readAllStandardError()).trimmed();

    if (process.exitCode() != 0)
        return {false, stdoutStr, stderrStr.isEmpty() ? "pkexec failed with exit code " + QString::number(process.exitCode()) : stderrStr};

    return {true, stdoutStr, ""};
}
