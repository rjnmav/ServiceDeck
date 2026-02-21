#include "mainwindow.h"
#include "mainpresenter.h"
#include "unit_model.h"
#include <QApplication>

int main(int argc, char *argv[])
{
    QApplication a(argc, argv);

    // Register types from the model
    qDBusRegisterMetaType<SystemdUnit>();
    qDBusRegisterMetaType<QList<SystemdUnit>>();

    MainPresenter presenter;
    MainWindow w(&presenter);
    w.show();

    return a.exec();
}