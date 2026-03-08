#ifndef PKEXEC_HELPER_H
#define PKEXEC_HELPER_H

#include <QObject>
#include <QString>

struct PkexecResult {
    bool success;
    QString output;
    QString error;
};

class PkexecHelper : public QObject
{
    Q_OBJECT

public:
    explicit PkexecHelper(QObject *parent = nullptr);

    PkexecResult writeSystemUnitFile(const QString &fileName, const QString &content);
};

#endif // PKEXEC_HELPER_H
