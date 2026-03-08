#include "servicedetailpanel.h"
#include <QFormLayout>
#include <QVBoxLayout>
#include <QWidget>
#include <QFont>

ServiceDetailPanel::ServiceDetailPanel(QWidget *parent)
    : QDockWidget("Service Details", parent)
{
    setObjectName("detailPanel");
    setMinimumHeight(200);
    setFeatures(QDockWidget::DockWidgetMovable | QDockWidget::DockWidgetClosable | QDockWidget::DockWidgetVerticalTitleBar);
    setupUi();
}

void ServiceDetailPanel::setupUi() {
    m_tabWidget = new QTabWidget(this);
    m_tabWidget->setObjectName("detailTabs");

    // ─── Properties tab ───
    QWidget *propsWidget = new QWidget();
    QFormLayout *propsLayout = new QFormLayout(propsWidget);
    propsLayout->setContentsMargins(16, 16, 16, 16);
    propsLayout->setSpacing(8);

    auto makeLabel = [](const QString &text = "-") {
        QLabel *lbl = new QLabel(text);
        lbl->setTextInteractionFlags(Qt::TextSelectableByMouse);
        return lbl;
    };

    m_nameValue    = makeLabel();
    m_descValue    = makeLabel();
    m_activeValue  = makeLabel();
    m_subStateValue = makeLabel();
    m_loadValue    = makeLabel();
    m_enabledValue = makeLabel();
    m_pathValue    = makeLabel();

    QFont boldFont;
    boldFont.setBold(true);

    auto addRow = [&](const QString &label, QLabel *value) {
        QLabel *lblWidget = new QLabel(label);
        lblWidget->setFont(boldFont);
        propsLayout->addRow(lblWidget, value);
    };

    addRow("Service Name:", m_nameValue);
    addRow("Description:",  m_descValue);
    addRow("Active State:", m_activeValue);
    addRow("Sub State:",    m_subStateValue);
    addRow("Load State:",   m_loadValue);
    addRow("Enabled:",      m_enabledValue);
    addRow("Unit Path:",    m_pathValue);

    m_tabWidget->addTab(propsWidget, "Properties");

    // ─── Unit file tab ───
    m_unitFileEdit = new QTextEdit();
    m_unitFileEdit->setReadOnly(true);
    m_unitFileEdit->setObjectName("unitFileViewer");
    QFont monoFont("Monospace", 10);
    monoFont.setStyleHint(QFont::Monospace);
    m_unitFileEdit->setFont(monoFont);

    m_tabWidget->addTab(m_unitFileEdit, "Unit File");

    setWidget(m_tabWidget);
}

void ServiceDetailPanel::showServiceDetails(const SystemdUnit &unit) {
    m_nameValue->setText(unit.name);
    m_descValue->setText(unit.description);
    m_activeValue->setText(unit.active_state);
    m_subStateValue->setText(unit.sub_state);
    m_loadValue->setText(unit.load_state);
    m_enabledValue->setText(unit.enabled_state);
    m_pathValue->setText(unit.unit_path.path());

    // Color-code active state label
    if (unit.active_state == "active")
        m_activeValue->setStyleSheet("color: #4CAF50; font-weight: bold;");
    else if (unit.active_state == "failed")
        m_activeValue->setStyleSheet("color: #F44336; font-weight: bold;");
    else if (unit.active_state == "inactive")
        m_activeValue->setStyleSheet("color: #9E9E9E; font-weight: bold;");
    else
        m_activeValue->setStyleSheet("color: #FFA726; font-weight: bold;");

    // Color-code enabled label
    if (unit.enabled_state == "enabled")
        m_enabledValue->setStyleSheet("color: #4CAF50; font-weight: bold;");
    else if (unit.enabled_state == "disabled")
        m_enabledValue->setStyleSheet("color: #F44336; font-weight: bold;");
    else if (unit.enabled_state == "masked")
        m_enabledValue->setStyleSheet("color: #795548; font-weight: bold;");
    else
        m_enabledValue->setStyleSheet("color: #9E9E9E;");

    show();
}

void ServiceDetailPanel::setUnitFileContent(const QString &content) {
    m_unitFileEdit->setPlainText(content);
}

void ServiceDetailPanel::clear() {
    m_nameValue->setText("-");
    m_descValue->setText("-");
    m_activeValue->setText("-");
    m_activeValue->setStyleSheet("");
    m_subStateValue->setText("-");
    m_loadValue->setText("-");
    m_enabledValue->setText("-");
    m_enabledValue->setStyleSheet("");
    m_pathValue->setText("-");
    m_unitFileEdit->clear();
}
