#include "mainwindow.h"
#include <QApplication>
#include "servicemanager.h"

int main(int argc, char *argv[])
{
    QApplication a(argc, argv);

    // CRITICAL: Register the custom D-Bus types before the app starts
    qDBusRegisterMetaType<SystemdUnit>();
    qDBusRegisterMetaType<QList<SystemdUnit>>();

    MainWindow w;
    w.show();

    return a.exec();
}