#include "unit_file_helper.h"
#include "pkexec_helper.h"
#include <QDir>
#include <QFile>
#include <QStandardPaths>
#include <QTextStream>

UnitFileHelper::UnitFileHelper(QObject *parent)
    : QObject(parent), m_pkexec(new PkexecHelper(this)) {}

QString UnitFileHelper::readUnitFile(const QString &unitPath) {
    QFile file(unitPath);
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text))
        return "Unable to read unit file: " + unitPath;
    QTextStream in(&file);
    return in.readAll();
}

bool UnitFileHelper::createUserUnitFile(const QString &fileName, const QString &content) {
    QString dirPath = QDir::homePath() + "/.config/systemd/user";
    QDir dir(dirPath);
    if (!dir.exists())
        dir.mkpath(dirPath);

    QFile file(dirPath + "/" + fileName);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Text))
        return false;

    QTextStream out(&file);
    out << content;
    return true;
}

bool UnitFileHelper::createSystemUnitFile(const QString &fileName, const QString &content, QString &error) {
    PkexecResult result = m_pkexec->writeSystemUnitFile(fileName, content);
    if (!result.success)
        error = result.error;
    return result.success;
}

QString UnitFileHelper::defaultServiceTemplate() {
    return QStringLiteral(
        "[Unit]\n"
        "Description=My Custom Service\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "ExecStart=/usr/bin/myapp\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    );
}
