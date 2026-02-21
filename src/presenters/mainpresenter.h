#ifndef MAINPRESENTER_H
#define MAINPRESENTER_H

#include "unit_model.h"

class SystemdDBus;

class MainPresenter : public QObject
{
    Q_OBJECT
public:
    explicit MainPresenter(QObject *parent = nullptr);

public slots:
    void requestServiceList();

    signals:
        void serviceListReady(const QList<SystemdUnit> &units);

private:
    SystemdDBus *dbusService;
};

#endif