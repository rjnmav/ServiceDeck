#ifndef SERVICETOOLBAR_H
#define SERVICETOOLBAR_H

#include <QWidget>
#include <QToolBar>
#include <QLineEdit>
#include <QComboBox>
#include <QCheckBox>
#include <QAction>
#include <QStyledItemDelegate>

class ItemSpacingDelegate : public QStyledItemDelegate {
public:
    explicit ItemSpacingDelegate(QObject *parent = nullptr) : QStyledItemDelegate(parent) {}

    QSize sizeHint(const QStyleOptionViewItem &option, const QModelIndex &index) const override {
        QSize size = QStyledItemDelegate::sizeHint(option, index);
        size.setHeight(size.height() + 15); // Add spacing
        return size;
    }
};

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
    void refreshIcons();

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
