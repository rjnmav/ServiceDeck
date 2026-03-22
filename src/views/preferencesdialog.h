#ifndef PREFERENCESDIALOG_H
#define PREFERENCESDIALOG_H

#include <QDialog>
#include <QSpinBox>
#include <QComboBox>
#include <QPushButton>

class PreferencesDialog : public QDialog
{
    Q_OBJECT

public:
    explicit PreferencesDialog(QWidget *parent = nullptr);

private slots:
    void onApply();
    void onOk();

private:
    void setupUi();
    void loadCurrentPreferences();

    QSpinBox *m_logRefreshSpinBox = nullptr;
    QSpinBox *m_resourceRefreshSpinBox = nullptr;
    QComboBox *m_themeComboBox = nullptr;

    QPushButton *m_applyBtn = nullptr;
    QPushButton *m_okBtn = nullptr;
    QPushButton *m_cancelBtn = nullptr;
};

#endif // PREFERENCESDIALOG_H
