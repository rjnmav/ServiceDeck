#include "service_table_model.h"
#include <QColor>
#include <QFont>

ServiceTableModel::ServiceTableModel(QObject *parent)
    : QAbstractTableModel(parent) {}

int ServiceTableModel::rowCount(const QModelIndex &parent) const {
    Q_UNUSED(parent);
    return m_services.size();
}

int ServiceTableModel::columnCount(const QModelIndex &parent) const {
    Q_UNUSED(parent);
    return ColCount;
}

QVariant ServiceTableModel::data(const QModelIndex &index, int role) const {
    if (!index.isValid() || index.row() >= m_services.size())
        return QVariant();

    const SystemdUnit &unit = m_services.at(index.row());

    if (role == Qt::DisplayRole) {
        switch (index.column()) {
        case ColName:        return unit.name;
        case ColDescription: return unit.description;
        case ColActiveState: return unit.active_state.toUpper();
        case ColSubState:    return unit.sub_state.toUpper();
        case ColEnabled:     return unit.enabled_state.toUpper();
        default:             return QVariant();
        }
    }

    if (role == Qt::ForegroundRole && index.column() == ColActiveState) {
        if (unit.active_state == "active")
            return QColor(0x4C, 0xAF, 0x50); // Green
        if (unit.active_state == "failed")
            return QColor(0xF4, 0x43, 0x36); // Red
        if (unit.active_state == "inactive")
            return QColor(0xFF, 0xA7, 0x26); // Yellow
        return QColor(0xFF, 0xA7, 0x26);      // Orange (activating/deactivating)
    }

    if (role == Qt::ForegroundRole && index.column() == ColEnabled) {
        if (unit.enabled_state == "enabled")
            return QColor(0x4C, 0xAF, 0x50);
        if (unit.enabled_state == "disabled")
            return QColor(0xF4, 0x43, 0x36);
        if (unit.enabled_state == "masked")
            return QColor(0x79, 0x55, 0x48); // Brown
        return QColor(0x9E, 0x9E, 0x9E);
    }

    if (role == Qt::FontRole && (index.column() == ColActiveState || index.column() == ColEnabled)) {
        QFont font;
        font.setBold(true);
        return font;
    }

    if (role == Qt::TextAlignmentRole) {
        if (index.column() == ColActiveState || index.column() == ColSubState || index.column() == ColEnabled)
            return Qt::AlignCenter;
    }

    return QVariant();
}

QVariant ServiceTableModel::headerData(int section, Qt::Orientation orientation, int role) const {
    if (orientation != Qt::Horizontal || role != Qt::DisplayRole)
        return QVariant();

    switch (section) {
    case ColName:        return "Service Name";
    case ColDescription: return "Description";
    case ColActiveState: return "Active";
    case ColSubState:    return "Sub State";
    case ColEnabled:     return "Enabled";
    default:             return QVariant();
    }
}

void ServiceTableModel::setServices(const QList<SystemdUnit> &units) {
    beginResetModel();
    m_services = units;
    endResetModel();
}

SystemdUnit ServiceTableModel::serviceAt(int row) const {
    if (row >= 0 && row < m_services.size())
        return m_services.at(row);
    return SystemdUnit();
}

QList<SystemdUnit> ServiceTableModel::allServices() const {
    return m_services;
}
