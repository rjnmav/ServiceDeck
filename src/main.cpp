#include "mainwindow.h"
#include "mainpresenter.h"
#include "unit_model.h"
#include <QApplication>
#include <QFile>

static void loadStyleSheet(QApplication &app) {
    QFile file(":/styles/light_theme.qss");
    if (file.open(QIODevice::ReadOnly | QIODevice::Text)) {
        app.setStyleSheet(QString::fromUtf8(file.readAll()));
        file.close();
    }
}

int main(int argc, char *argv[])
{
    QApplication a(argc, argv);
    a.setApplicationName("ServiceDeck");
    a.setOrganizationName("ServiceDeck");

    // Register D-Bus types
    qDBusRegisterMetaType<SystemdUnit>();
    qDBusRegisterMetaType<QList<SystemdUnit>>();

    // Apply dark theme
    loadStyleSheet(a);

    MainPresenter presenter;
    MainWindow w(&presenter);
    w.show();

    return a.exec();
}