#ifndef UNIT_FILE_HELPER_H
#define UNIT_FILE_HELPER_H

#include <QObject>
#include <QString>

class PkexecHelper;

class UnitFileHelper : public QObject
{
    Q_OBJECT

public:
    explicit UnitFileHelper(QObject *parent = nullptr);

    QString readUnitFile(const QString &unitPath);
    bool createUserUnitFile(const QString &fileName, const QString &content);
    bool createSystemUnitFile(const QString &fileName, const QString &content, QString &error);

    static QString defaultServiceTemplate();

private:
    PkexecHelper *m_pkexec;
};

#endif // UNIT_FILE_HELPER_H
