#ifndef APP_PREFERENCES_H
#define APP_PREFERENCES_H

#include <QObject>
#include <QSettings>

class AppPreferences : public QObject
{
    Q_OBJECT

public:
    static AppPreferences& instance() {
        static AppPreferences instance;
        return instance;
    }

    int logRefreshInterval() const;
    void setLogRefreshInterval(int ms);

    int resourceRefreshInterval() const;
    void setResourceRefreshInterval(int ms);

    QString theme() const;
    void setTheme(const QString &theme);

signals:
    void preferencesChanged();

private:
    AppPreferences(QObject *parent = nullptr);
    ~AppPreferences() = default;
    
    QSettings m_settings;
};

#endif // APP_PREFERENCES_H
