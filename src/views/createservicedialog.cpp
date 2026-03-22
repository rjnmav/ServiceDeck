#include "createservicedialog.h"
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QFormLayout>
#include <QGroupBox>
#include <QLabel>
#include <QFont>
#include <QMessageBox>
#include <QRegularExpression>
#include <QDebug>

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
    setMinimumSize(850, 550);
    setObjectName("createServiceDialog");
    setupUi();
    
    // Initial sync from default template to form
    syncEditorToForm();
}

void CreateServiceDialog::setupUi() {
    QVBoxLayout *mainLayout = new QVBoxLayout(this);
    mainLayout->setContentsMargins(20, 20, 20, 20);
    mainLayout->setSpacing(16);

    // ─── Header ───
    QVBoxLayout *headerLayout = new QVBoxLayout();
    QLabel *titleLabel = new QLabel("Create a New Systemd Service");
    QFont titleFont;
    titleFont.setPointSize(14);
    titleFont.setBold(true);
    titleLabel->setFont(titleFont);
    titleLabel->setObjectName("dialogTitle");
    
    QLabel *subtitleLabel = new QLabel("Configure service properties below or edit the raw unit file directly.");
    subtitleLabel->setObjectName("dialogSubtitle");
    subtitleLabel->setStyleSheet("color: #718096;"); // Using a generic dark/light safe color
    
    headerLayout->addWidget(titleLabel);
    headerLayout->addWidget(subtitleLabel);
    mainLayout->addLayout(headerLayout);

    // ─── Split Layout ───
    QHBoxLayout *splitLayout = new QHBoxLayout();
    splitLayout->setSpacing(20);

    // --- Left Pane (Form) ---
    QVBoxLayout *leftPaneLayout = new QVBoxLayout();
    
    // Scope selector
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
    leftPaneLayout->addWidget(scopeGroup);

    // Path preview label
    m_pathLabel = new QLabel();
    m_pathLabel->setWordWrap(true);
    m_pathLabel->setStyleSheet("color: #a9b1d6; font-size: 11px; font-style: italic;");
    m_pathLabel->setObjectName("pathLabel");
    leftPaneLayout->addWidget(m_pathLabel);

    // Form settings
    QFormLayout *formLayout = new QFormLayout();
    formLayout->setSpacing(12);

    m_nameEdit = new QLineEdit();
    m_nameEdit->setPlaceholderText("my-service.service");
    m_nameEdit->setObjectName("serviceNameEdit");
    formLayout->addRow("File Name:", m_nameEdit);

    m_descEdit = new QLineEdit();
    m_descEdit->setPlaceholderText("Description of the service");
    formLayout->addRow("Description:", m_descEdit);

    m_execEdit = new QLineEdit();
    m_execEdit->setPlaceholderText("/usr/bin/my-command");
    formLayout->addRow("ExecStart:", m_execEdit);

    m_typeCombo = new QComboBox();
    m_typeCombo->addItems({"simple", "exec", "forking", "oneshot", "dbus", "notify", "idle"});
    formLayout->addRow("Type:", m_typeCombo);

    m_restartCombo = new QComboBox();
    m_restartCombo->addItems({"no", "always", "on-success", "on-failure", "on-abnormal", "on-abort", "on-watchdog"});
    m_restartCombo->setCurrentText("on-failure");
    formLayout->addRow("Restart:", m_restartCombo);

    leftPaneLayout->addLayout(formLayout);
    leftPaneLayout->addStretch();

    splitLayout->addLayout(leftPaneLayout, 1);

    // --- Right Pane (Editor) ---
    QVBoxLayout *rightPaneLayout = new QVBoxLayout();
    QLabel *contentLabel = new QLabel("Unit File Preview & Editor:");
    contentLabel->setFont(QFont(contentLabel->font().family(), -1, QFont::Bold));
    rightPaneLayout->addWidget(contentLabel);

    m_contentEdit = new QTextEdit();
    m_contentEdit->setObjectName("unitContentEdit");
    QFont monoFont("Monospace", 10);
    monoFont.setStyleHint(QFont::Monospace);
    m_contentEdit->setFont(monoFont);
    m_contentEdit->setPlainText(DEFAULT_SERVICE_TEMPLATE);
    m_contentEdit->setLineWrapMode(QTextEdit::NoWrap);
    rightPaneLayout->addWidget(m_contentEdit, 1);
    
    splitLayout->addLayout(rightPaneLayout, 1);
    
    mainLayout->addLayout(splitLayout, 1);

    // ─── Buttons ───
    QHBoxLayout *btnLayout = new QHBoxLayout();
    btnLayout->addStretch();

    m_cancelBtn = new QPushButton("Cancel");
    m_cancelBtn->setObjectName("cancelBtn");
    m_createBtn = new QPushButton("Create");
    m_createBtn->setObjectName("primary");
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

    connect(m_descEdit, &QLineEdit::textEdited, this, &CreateServiceDialog::syncFormToEditor);
    connect(m_execEdit, &QLineEdit::textEdited, this, &CreateServiceDialog::syncFormToEditor);
    connect(m_typeCombo, &QComboBox::currentTextChanged, this, &CreateServiceDialog::syncFormToEditor);
    connect(m_restartCombo, &QComboBox::currentTextChanged, this, &CreateServiceDialog::syncFormToEditor);

    connect(m_contentEdit, &QTextEdit::textChanged, this, &CreateServiceDialog::syncEditorToForm);

    connect(m_userRadio, &QRadioButton::toggled, this, &CreateServiceDialog::updatePathInfo);
    connect(m_systemRadio, &QRadioButton::toggled, this, &CreateServiceDialog::updatePathInfo);
    connect(m_nameEdit, &QLineEdit::textChanged, this, &CreateServiceDialog::updatePathInfo);

    updatePathInfo();
}

void CreateServiceDialog::updatePathInfo() {
    QString fileName = m_nameEdit->text().trimmed();
    if (fileName.isEmpty()) {
        fileName = "my-service.service";
    } else if (!fileName.endsWith(".service")) {
        fileName += ".service";
    }

    if (m_userRadio->isChecked()) {
        m_pathLabel->setText(QString("<b>User Mode:</b> Service will be installed to <code>~/.config/systemd/user/%1</code>. This service runs under your user account and doesn't require root privileges.").arg(fileName));
    } else {
        m_pathLabel->setText(QString("<b>System Mode:</b> Service will be installed to <code>/etc/systemd/system/%1</code>. This service runs globally for all users and requires root (pkexec) to install.").arg(fileName));
    }
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

QString CreateServiceDialog::extractUnitKey(const QString& section, const QString& key) const {
    QString content = m_contentEdit->toPlainText();
    
    QString escapedSection = QRegularExpression::escape("[" + section + "]");
    QRegularExpression sectionRe(escapedSection + "(.*?)(?:\n\\[|$)", QRegularExpression::DotMatchesEverythingOption);
    QRegularExpressionMatch sectionMatch = sectionRe.match(content);
    
    if (sectionMatch.hasMatch()) {
        QString sectionContent = sectionMatch.captured(1);
        QRegularExpression keyRe("^\\s*" + QRegularExpression::escape(key) + "\\s*=\\s*(.*)$", QRegularExpression::MultilineOption);
        QRegularExpressionMatch keyMatch = keyRe.match(sectionContent);
        if (keyMatch.hasMatch()) {
            return keyMatch.captured(1).trimmed();
        }
    }
    return QString();
}

void CreateServiceDialog::updateUnitKey(const QString& section, const QString& key, const QString& value) {
    QString content = m_contentEdit->toPlainText();
    QString escapedSection = QRegularExpression::escape("[" + section + "]");
    
    QRegularExpression sectionRe("(" + escapedSection + "(?:\n.*?)?)(?:\n\\[|$)", QRegularExpression::DotMatchesEverythingOption);
    QRegularExpressionMatch sectionMatch = sectionRe.match(content);
    
    if (sectionMatch.hasMatch()) {
        QString sectionContent = sectionMatch.captured(1);
        
        QRegularExpression keyRe("^(\\s*" + QRegularExpression::escape(key) + "\\s*=).*$", QRegularExpression::MultilineOption);
        QRegularExpressionMatch keyMatch = keyRe.match(sectionContent);
        
        if (value.isEmpty() && keyMatch.hasMatch()) {
            sectionContent.replace(keyMatch.capturedStart(), keyMatch.capturedLength(), keyMatch.captured(1));
        } else if (keyMatch.hasMatch()) {
            sectionContent.replace(keyMatch.capturedStart(), keyMatch.capturedLength(), keyMatch.captured(1) + value);
        } else if (!value.isEmpty()) {
            if (!sectionContent.endsWith("\n")) {
                sectionContent += "\n";
            }
            sectionContent += key + "=" + value + "\n";
        }
        
        QString newContent = content;
        newContent.replace(sectionMatch.capturedStart(1), sectionMatch.capturedLength(1), sectionContent);
        
        int cursorPos = m_contentEdit->textCursor().position();
        m_contentEdit->setPlainText(newContent);
        
        QTextCursor cursor = m_contentEdit->textCursor();
        cursor.setPosition(qMin(cursorPos, newContent.length()));
        m_contentEdit->setTextCursor(cursor);
    } else if (!value.isEmpty()) {
        if (!content.isEmpty() && !content.endsWith("\n\n") && !content.endsWith("\n")) {
            content += "\n";
        }
        if (!content.endsWith("\n\n") && !content.isEmpty()) {
            content += "\n";
        }
        content += "[" + section + "]\n";
        content += key + "=" + value + "\n";
        
        int cursorPos = m_contentEdit->textCursor().position();
        m_contentEdit->setPlainText(content);
        
        QTextCursor cursor = m_contentEdit->textCursor();
        cursor.setPosition(qMin(cursorPos, content.length()));
        m_contentEdit->setTextCursor(cursor);
    }
}

void CreateServiceDialog::syncFormToEditor() {
    m_contentEdit->blockSignals(true);
    
    updateUnitKey("Unit", "Description", m_descEdit->text());
    updateUnitKey("Service", "ExecStart", m_execEdit->text());
    updateUnitKey("Service", "Type", m_typeCombo->currentText());
    updateUnitKey("Service", "Restart", m_restartCombo->currentText());
    
    m_contentEdit->blockSignals(false);
}

void CreateServiceDialog::syncEditorToForm() {
    m_descEdit->blockSignals(true);
    m_execEdit->blockSignals(true);
    m_typeCombo->blockSignals(true);
    m_restartCombo->blockSignals(true);
    
    m_descEdit->setText(extractUnitKey("Unit", "Description"));
    m_execEdit->setText(extractUnitKey("Service", "ExecStart"));
    
    QString typeVal = extractUnitKey("Service", "Type");
    if (!typeVal.isEmpty()) {
        m_typeCombo->setCurrentText(typeVal);
    }
    
    QString restartVal = extractUnitKey("Service", "Restart");
    if (!restartVal.isEmpty()) {
        m_restartCombo->setCurrentText(restartVal);
    }
    
    m_descEdit->blockSignals(false);
    m_execEdit->blockSignals(false);
    m_typeCombo->blockSignals(false);
    m_restartCombo->blockSignals(false);
}