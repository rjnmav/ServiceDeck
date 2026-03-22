#include "app_preferences.h"

AppPreferences::AppPreferences(QObject *parent)
    : QObject(parent), m_settings("ServiceDeck", "ServiceDeck")
{
}

int AppPreferences::logRefreshInterval() const {
    return m_settings.value("intervals/logRefresh", 5000).toInt();
}

void AppPreferences::setLogRefreshInterval(int ms) {
    if (logRefreshInterval() != ms) {
        m_settings.setValue("intervals/logRefresh", ms);
        emit preferencesChanged();
    }
}

int AppPreferences::resourceRefreshInterval() const {
    return m_settings.value("intervals/resourceRefresh", 2000).toInt();
}

void AppPreferences::setResourceRefreshInterval(int ms) {
    if (resourceRefreshInterval() != ms) {
        m_settings.setValue("intervals/resourceRefresh", ms);
        emit preferencesChanged();
    }
}

QString AppPreferences::theme() const {
    return m_settings.value("ui/theme", "light").toString();
}

void AppPreferences::setTheme(const QString &theme) {
    if (this->theme() != theme) {
        m_settings.setValue("ui/theme", theme);
        emit preferencesChanged();
    }
}
