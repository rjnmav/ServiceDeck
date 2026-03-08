#ifndef MAINPRESENTER_H
#define MAINPRESENTER_H

#include <QObject>
#include "unit_model.h"

class SystemdDBus;
class UnitFileHelper;

class MainPresenter : public QObject
{
    Q_OBJECT

public:
    explicit MainPresenter(QObject *parent = nullptr);

    bool isSystemMode() const;

public slots:
    void requestServiceList();
    void requestSwitchBus(bool useSystem);

    void requestStartService(const QString &name);
    void requestStopService(const QString &name);
    void requestRestartService(const QString &name);
    void requestEnableService(const QString &name);
    void requestDisableService(const QString &name);
    void requestMaskService(const QString &name);
    void requestUnmaskService(const QString &name);
    void requestReloadDaemon();

    void requestCreateService(const QString &fileName, const QString &content, bool isSystem);
    void requestUnitFileContent(const QDBusObjectPath &unitPath);

signals:
    void serviceListReady(const QList<SystemdUnit> &units);
    void operationCompleted(bool success, const QString &message);
    void unitFileContentReady(const QString &content);

private:
    SystemdDBus *m_dbusService;
    UnitFileHelper *m_unitFileHelper;
    bool m_systemMode = false;
};

#endif // MAINPRESENTER_H