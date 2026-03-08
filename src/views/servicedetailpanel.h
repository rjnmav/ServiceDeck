#ifndef SERVICEDETAILPANEL_H
#define SERVICEDETAILPANEL_H

#include <QDockWidget>
#include <QLabel>
#include <QTextEdit>
#include <QTabWidget>
#include "unit_model.h"

class ServiceDetailPanel : public QDockWidget
{
    Q_OBJECT

public:
    explicit ServiceDetailPanel(QWidget *parent = nullptr);

    void showServiceDetails(const SystemdUnit &unit);
    void setUnitFileContent(const QString &content);
    void clear();

private:
    void setupUi();

    QTabWidget *m_tabWidget = nullptr;

    // Properties tab
    QLabel *m_nameValue = nullptr;
    QLabel *m_descValue = nullptr;
    QLabel *m_activeValue = nullptr;
    QLabel *m_subStateValue = nullptr;
    QLabel *m_loadValue = nullptr;
    QLabel *m_enabledValue = nullptr;
    QLabel *m_pathValue = nullptr;

    // Unit file tab
    QTextEdit *m_unitFileEdit = nullptr;
};

#endif // SERVICEDETAILPANEL_H
