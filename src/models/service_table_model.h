#ifndef SERVICE_TABLE_MODEL_H
#define SERVICE_TABLE_MODEL_H

#include <QAbstractTableModel>
#include "unit_model.h"

class ServiceTableModel : public QAbstractTableModel
{
    Q_OBJECT

public:
    enum Column {
        ColName = 0,
        ColDescription,
        ColActiveState,
        ColSubState,
        ColEnabled,
        ColCount
    };

    explicit ServiceTableModel(QObject *parent = nullptr);

    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    int columnCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &index, int role = Qt::DisplayRole) const override;
    QVariant headerData(int section, Qt::Orientation orientation, int role = Qt::DisplayRole) const override;

    void setServices(const QList<SystemdUnit> &units);
    SystemdUnit serviceAt(int row) const;
    QList<SystemdUnit> allServices() const;

private:
    QList<SystemdUnit> m_services;
};

#endif // SERVICE_TABLE_MODEL_H
