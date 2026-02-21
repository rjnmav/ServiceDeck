#include "mainpresenter.h"
#include "systemd_dbus.h"

MainPresenter::MainPresenter(QObject *parent) : QObject(parent) {
    dbusService = new SystemdDBus(this);
}

void MainPresenter::requestServiceList() {
    QList<SystemdUnit> units = dbusService->fetchAllServices();
    emit serviceListReady(units);
}