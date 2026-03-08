#ifndef SERVICE_FILTER_MODEL_H
#define SERVICE_FILTER_MODEL_H

#include <QSortFilterProxyModel>

class ServiceFilterModel : public QSortFilterProxyModel
{
    Q_OBJECT

public:
    explicit ServiceFilterModel(QObject *parent = nullptr);

    void setNameFilter(const QString &text);
    void setActiveStateFilter(const QString &state);

protected:
    bool filterAcceptsRow(int sourceRow, const QModelIndex &sourceParent) const override;

private:
    QString m_nameFilter;
    QString m_activeStateFilter; // "", "active", "inactive", "failed"
};

#endif // SERVICE_FILTER_MODEL_H
