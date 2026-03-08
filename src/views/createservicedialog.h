#ifndef CREATESERVICEDIALOG_H
#define CREATESERVICEDIALOG_H

#include <QDialog>
#include <QLineEdit>
#include <QTextEdit>
#include <QRadioButton>
#include <QPushButton>

class CreateServiceDialog : public QDialog
{
    Q_OBJECT

public:
    explicit CreateServiceDialog(QWidget *parent = nullptr);

    QString fileName() const;
    QString content() const;
    bool isSystemScope() const;

private:
    void setupUi();

    QLineEdit *m_nameEdit = nullptr;
    QTextEdit *m_contentEdit = nullptr;
    QRadioButton *m_userRadio = nullptr;
    QRadioButton *m_systemRadio = nullptr;
    QPushButton *m_createBtn = nullptr;
    QPushButton *m_cancelBtn = nullptr;
};

#endif // CREATESERVICEDIALOG_H
