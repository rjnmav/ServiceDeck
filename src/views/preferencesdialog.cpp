#include "preferencesdialog.h"
#include "../models/app_preferences.h"
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QFormLayout>
#include <QLabel>

PreferencesDialog::PreferencesDialog(QWidget *parent)
    : QDialog(parent)
{
    setWindowTitle("Preferences");
    setMinimumWidth(350);
    setupUi();
    loadCurrentPreferences();
}

void PreferencesDialog::setupUi()
{
    QVBoxLayout *mainLayout = new QVBoxLayout(this);
    mainLayout->setContentsMargins(16, 16, 16, 16);
    mainLayout->setSpacing(12);

    QFormLayout *formLayout = new QFormLayout();
    
    m_logRefreshSpinBox = new QSpinBox(this);
    m_logRefreshSpinBox->setRange(1, 60);
    m_logRefreshSpinBox->setSuffix(" seconds");
    formLayout->addRow("Log Refresh Interval:", m_logRefreshSpinBox);

    m_resourceRefreshSpinBox = new QSpinBox(this);
    m_resourceRefreshSpinBox->setRange(1, 60);
    m_resourceRefreshSpinBox->setSuffix(" seconds");
    formLayout->addRow("Resource Refresh Interval:", m_resourceRefreshSpinBox);

    m_themeComboBox = new QComboBox(this);
    m_themeComboBox->addItems({"dark", "light"});
    formLayout->addRow("UI Theme:", m_themeComboBox);

    mainLayout->addLayout(formLayout);

    mainLayout->addStretch();

    QHBoxLayout *btnLayout = new QHBoxLayout();
    m_applyBtn = new QPushButton("Apply", this);
    m_okBtn = new QPushButton("OK", this);
    m_cancelBtn = new QPushButton("Cancel", this);
    
    m_okBtn->setDefault(true);

    btnLayout->addStretch();
    btnLayout->addWidget(m_applyBtn);
    btnLayout->addWidget(m_okBtn);
    btnLayout->addWidget(m_cancelBtn);

    mainLayout->addLayout(btnLayout);

    connect(m_applyBtn, &QPushButton::clicked, this, &PreferencesDialog::onApply);
    connect(m_okBtn, &QPushButton::clicked, this, &PreferencesDialog::onOk);
    connect(m_cancelBtn, &QPushButton::clicked, this, &QDialog::reject);
}

void PreferencesDialog::loadCurrentPreferences()
{
    AppPreferences &prefs = AppPreferences::instance();
    m_logRefreshSpinBox->setValue(prefs.logRefreshInterval() / 1000);
    m_resourceRefreshSpinBox->setValue(prefs.resourceRefreshInterval() / 1000);
    
    int themeIndex = m_themeComboBox->findText(prefs.theme());
    if (themeIndex >= 0) {
        m_themeComboBox->setCurrentIndex(themeIndex);
    }
}

void PreferencesDialog::onApply()
{
    AppPreferences &prefs = AppPreferences::instance();
    prefs.setLogRefreshInterval(m_logRefreshSpinBox->value() * 1000);
    prefs.setResourceRefreshInterval(m_resourceRefreshSpinBox->value() * 1000);
    prefs.setTheme(m_themeComboBox->currentText());
}

void PreferencesDialog::onOk()
{
    onApply();
    accept();
}
