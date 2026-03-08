#include "createservicedialog.h"
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QGroupBox>
#include <QLabel>
#include <QFont>
#include <QMessageBox>

static const QString DEFAULT_SERVICE_TEMPLATE =
    "[Unit]\n"
    "Description=My Custom Service\n"
    "After=network.target\n"
    "\n"
    "[Service]\n"
    "Type=simple\n"
    "ExecStart=/usr/bin/myapp\n"
    "Restart=on-failure\n"
    "RestartSec=5\n"
    "\n"
    "[Install]\n"
    "WantedBy=default.target\n";

CreateServiceDialog::CreateServiceDialog(QWidget *parent)
    : QDialog(parent)
{
    setWindowTitle("Create New Service");
    setMinimumSize(550, 500);
    setObjectName("createServiceDialog");
    setupUi();
}

void CreateServiceDialog::setupUi() {
    QVBoxLayout *mainLayout = new QVBoxLayout(this);
    mainLayout->setContentsMargins(20, 20, 20, 20);
    mainLayout->setSpacing(16);

    // ─── Title ───
    QLabel *titleLabel = new QLabel("Create a New Systemd Service");
    QFont titleFont;
    titleFont.setPointSize(14);
    titleFont.setBold(true);
    titleLabel->setFont(titleFont);
    titleLabel->setObjectName("dialogTitle");
    mainLayout->addWidget(titleLabel);

    // ─── Scope selector ───
    QGroupBox *scopeGroup = new QGroupBox("Service Scope");
    scopeGroup->setObjectName("scopeGroup");
    QHBoxLayout *scopeLayout = new QHBoxLayout(scopeGroup);

    m_userRadio = new QRadioButton("User Service");
    m_systemRadio = new QRadioButton("System Service");
    m_userRadio->setChecked(true);

    m_userRadio->setToolTip("Installs to ~/.config/systemd/user/");
    m_systemRadio->setToolTip("Installs to /etc/systemd/system/ (requires authentication)");

    scopeLayout->addWidget(m_userRadio);
    scopeLayout->addWidget(m_systemRadio);
    mainLayout->addWidget(scopeGroup);

    // ─── Service name ───
    QLabel *nameLabel = new QLabel("Service File Name:");
    nameLabel->setFont(QFont(nameLabel->font().family(), -1, QFont::Bold));
    mainLayout->addWidget(nameLabel);

    m_nameEdit = new QLineEdit();
    m_nameEdit->setPlaceholderText("my-service.service");
    m_nameEdit->setObjectName("serviceNameEdit");
    mainLayout->addWidget(m_nameEdit);

    // ─── Unit file content ───
    QLabel *contentLabel = new QLabel("Unit File Content:");
    contentLabel->setFont(QFont(contentLabel->font().family(), -1, QFont::Bold));
    mainLayout->addWidget(contentLabel);

    m_contentEdit = new QTextEdit();
    m_contentEdit->setObjectName("unitContentEdit");
    QFont monoFont("Monospace", 10);
    monoFont.setStyleHint(QFont::Monospace);
    m_contentEdit->setFont(monoFont);
    m_contentEdit->setPlainText(DEFAULT_SERVICE_TEMPLATE);
    mainLayout->addWidget(m_contentEdit, 1);

    // ─── Buttons ───
    QHBoxLayout *btnLayout = new QHBoxLayout();
    btnLayout->addStretch();

    m_cancelBtn = new QPushButton("Cancel");
    m_cancelBtn->setObjectName("cancelBtn");
    m_createBtn = new QPushButton("Create");
    m_createBtn->setObjectName("createBtn");
    m_createBtn->setDefault(true);

    btnLayout->addWidget(m_cancelBtn);
    btnLayout->addWidget(m_createBtn);
    mainLayout->addLayout(btnLayout);

    // ─── Connections ───
    connect(m_cancelBtn, &QPushButton::clicked, this, &QDialog::reject);
    connect(m_createBtn, &QPushButton::clicked, this, [this]() {
        if (m_nameEdit->text().trimmed().isEmpty()) {
            QMessageBox::warning(this, "Validation Error", "Please enter a service file name.");
            return;
        }
        QString name = m_nameEdit->text().trimmed();
        if (!name.endsWith(".service"))
            name += ".service";
        m_nameEdit->setText(name);
        accept();
    });
}

QString CreateServiceDialog::fileName() const {
    return m_nameEdit->text().trimmed();
}

QString CreateServiceDialog::content() const {
    return m_contentEdit->toPlainText();
}

bool CreateServiceDialog::isSystemScope() const {
    return m_systemRadio->isChecked();
}
