#include "mainwindow.h"
#include "mainpresenter.h"
#include "unit_model.h"
#include "app_preferences.h"
#include <QApplication>
#include <QFile>
#include <QLockFile>
#include <QDir>
#include <QMessageBox>
#include <QIcon>
#include <QDebug>

static void loadStyleSheet(QApplication &app, const QString &theme) {
    QString qssPath = QString(":/styles/%1_theme.qss").arg(theme);
    QFile file(qssPath);
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

    // Set application window icon globally
    QIcon appIcon(":/assets/service_deck.svg");
    if (appIcon.isNull()) {
        appIcon = QIcon::fromTheme("system-run");
    }
    
    if (!appIcon.isNull()) {
        a.setWindowIcon(appIcon);
    }

    QLockFile lockFile(QDir::tempPath() + "/servicedeck.lock");
    if (!lockFile.tryLock(100)) {
        QMessageBox::warning(nullptr, "ServiceDeck", "Another instance of ServiceDeck is already running.");
        return 0;
    }

    // Register D-Bus types
    qDBusRegisterMetaType<SystemdUnit>();
    qDBusRegisterMetaType<QList<SystemdUnit>>();

    // Apply theme
    AppPreferences &prefs = AppPreferences::instance();
    loadStyleSheet(a, prefs.theme());

    QObject::connect(&prefs, &AppPreferences::preferencesChanged, [&a, &prefs]() {
        loadStyleSheet(a, prefs.theme());
    });

    MainPresenter presenter;
    MainWindow w(&presenter);
    
    w.show();

    return a.exec();
}
