#ifndef SERVICETOOLBAR_H
#define SERVICETOOLBAR_H

#include <QWidget>
#include <QToolBar>
#include <QLineEdit>
#include <QComboBox>
#include <QCheckBox>
#include <QAction>

class ServiceToolbar : public QToolBar
{
    Q_OBJECT

public:
    explicit ServiceToolbar(QWidget *parent = nullptr);

    QAction *startAction() const   { return m_startAction; }
    QAction *stopAction() const    { return m_stopAction; }
    QAction *restartAction() const { return m_restartAction; }
    QAction *enableAction() const  { return m_enableAction; }
    QAction *disableAction() const { return m_disableAction; }
    QAction *maskAction() const    { return m_maskAction; }
    QAction *unmaskAction() const  { return m_unmaskAction; }
    QAction *reloadAction() const  { return m_reloadAction; }
    QAction *refreshAction() const { return m_refreshAction; }
    QAction *createAction() const  { return m_createAction; }

    void setActionsEnabled(bool enabled);

signals:
    void searchTextChanged(const QString &text);
    void activeStateFilterChanged(const QString &state);
    void systemModeToggled(bool isSystem);

private:
    void setupActions();
    void setupSearchAndFilters();

    QAction *m_startAction = nullptr;
    QAction *m_stopAction = nullptr;
    QAction *m_restartAction = nullptr;
    QAction *m_enableAction = nullptr;
    QAction *m_disableAction = nullptr;
    QAction *m_maskAction = nullptr;
    QAction *m_unmaskAction = nullptr;
    QAction *m_reloadAction = nullptr;
    QAction *m_refreshAction = nullptr;
    QAction *m_createAction = nullptr;

    QLineEdit *m_searchEdit = nullptr;
    QComboBox *m_filterCombo = nullptr;
    QCheckBox *m_systemToggle = nullptr;
};

#endif // SERVICETOOLBAR_H
