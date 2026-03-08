#include "mainpresenter.h"
#include "systemd_dbus.h"
#include "unit_file_helper.h"

MainPresenter::MainPresenter(QObject *parent) : QObject(parent) {
    m_dbusService = new SystemdDBus(this);
    m_unitFileHelper = new UnitFileHelper(this);
}

bool MainPresenter::isSystemMode() const {
    return m_systemMode;
}

void MainPresenter::requestServiceList() {
    QList<SystemdUnit> units = m_dbusService->fetchAllServices();
    emit serviceListReady(units);
}

void MainPresenter::requestSwitchBus(bool useSystem) {
    m_systemMode = useSystem;
    m_dbusService->switchBus(useSystem);
    requestServiceList();
}

void MainPresenter::requestStartService(const QString &name) {
    auto result = m_dbusService->startService(name);
    emit operationCompleted(result.success, result.message);
    if (result.success) requestServiceList();
}

void MainPresenter::requestStopService(const QString &name) {
    auto result = m_dbusService->stopService(name);
    emit operationCompleted(result.success, result.message);
    if (result.success) requestServiceList();
}

void MainPresenter::requestRestartService(const QString &name) {
    auto result = m_dbusService->restartService(name);
    emit operationCompleted(result.success, result.message);
    if (result.success) requestServiceList();
}

void MainPresenter::requestEnableService(const QString &name) {
    auto result = m_dbusService->enableService(name);
    emit operationCompleted(result.success, result.message);
    if (result.success) requestServiceList();
}

void MainPresenter::requestDisableService(const QString &name) {
    auto result = m_dbusService->disableService(name);
    emit operationCompleted(result.success, result.message);
    if (result.success) requestServiceList();
}

void MainPresenter::requestMaskService(const QString &name) {
    auto result = m_dbusService->maskService(name);
    emit operationCompleted(result.success, result.message);
    if (result.success) requestServiceList();
}

void MainPresenter::requestUnmaskService(const QString &name) {
    auto result = m_dbusService->unmaskService(name);
    emit operationCompleted(result.success, result.message);
    if (result.success) requestServiceList();
}

void MainPresenter::requestReloadDaemon() {
    auto result = m_dbusService->reloadDaemon();
    emit operationCompleted(result.success, result.message);
}

void MainPresenter::requestCreateService(const QString &fileName, const QString &content, bool isSystem) {
    if (isSystem) {
        QString error;
        bool ok = m_unitFileHelper->createSystemUnitFile(fileName, content, error);
        emit operationCompleted(ok, ok ? "System service created: " + fileName : error);
    } else {
        bool ok = m_unitFileHelper->createUserUnitFile(fileName, content);
        emit operationCompleted(ok, ok ? "User service created: " + fileName : "Failed to create user service");
    }
    if (m_systemMode == isSystem) {
        requestReloadDaemon();
        requestServiceList();
    }
}

void MainPresenter::requestUnitFileContent(const QDBusObjectPath &unitPath) {
    const QString fragmentPath = m_dbusService->getUnitFragmentPath(unitPath);
    if (fragmentPath.isEmpty()) {
        const QString msg = QStringLiteral(
            "No unit file on disk (FragmentPath empty).\n\n"
            "D-Bus unit object: %1").arg(unitPath.path());
        emit unitFileContentReady(msg);
        return;
    }

    QString content = m_unitFileHelper->readUnitFile(fragmentPath);
    emit unitFileContentReady(content);
}