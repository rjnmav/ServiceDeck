#ifndef CREATESERVICEDIALOG_H
#define CREATESERVICEDIALOG_H

#include <QDialog>
#include <QLineEdit>
#include <QTextEdit>
#include <QRadioButton>
#include <QPushButton>
#include <QComboBox>
#include <QLabel>

class CreateServiceDialog : public QDialog
{
    Q_OBJECT

public:
    explicit CreateServiceDialog(QWidget *parent = nullptr);

    QString fileName() const;
    QString content() const;
    bool isSystemScope() const;

private slots:
    void syncFormToEditor();
    void syncEditorToForm();

private:
    void setupUi();
    QString extractUnitKey(const QString& section, const QString& key) const;
    void updateUnitKey(const QString& section, const QString& key, const QString& value);

    QLineEdit *m_nameEdit = nullptr;
    QLineEdit *m_descEdit = nullptr;
    QLineEdit *m_execEdit = nullptr;
    QComboBox *m_typeCombo = nullptr;
    QComboBox *m_restartCombo = nullptr;

    QTextEdit *m_contentEdit = nullptr;
    QRadioButton *m_userRadio = nullptr;
    QRadioButton *m_systemRadio = nullptr;
    QLabel *m_pathLabel = nullptr;
    QPushButton *m_createBtn = nullptr;
    QPushButton *m_cancelBtn = nullptr;

private slots:
    void updatePathInfo();
};

#endif // CREATESERVICEDIALOG_H
