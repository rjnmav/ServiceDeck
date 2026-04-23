#include "service_filter_model.h"
#include "service_table_model.h"

ServiceFilterModel::ServiceFilterModel(QObject *parent)
    : QSortFilterProxyModel(parent) {
    setDynamicSortFilter(true);
    setSortCaseSensitivity(Qt::CaseInsensitive);
    setFilterCaseSensitivity(Qt::CaseInsensitive);
}

void ServiceFilterModel::setNameFilter(const QString &text) {
    beginFilterChange();
    m_nameFilter = text;
    endFilterChange();
    // Deprecated: use  begin/endFilterChange() instead.
    // invalidateFilter();
}

void ServiceFilterModel::setActiveStateFilter(const QString &state) {
    beginFilterChange();
    m_activeStateFilter = state.toUpper();
    endFilterChange();
    // Deprecated: use  begin/endFilterChange() instead.
    // invalidateFilter();
}

bool ServiceFilterModel::filterAcceptsRow(int sourceRow, const QModelIndex &sourceParent) const {
    QModelIndex nameIdx = sourceModel()->index(sourceRow, ServiceTableModel::ColName, sourceParent);
    QModelIndex activeIdx = sourceModel()->index(sourceRow, ServiceTableModel::ColActiveState, sourceParent);

    QString name = sourceModel()->data(nameIdx).toString();
    QString activeState = sourceModel()->data(activeIdx).toString();

    // Name filter
    if (!m_nameFilter.isEmpty() && !name.contains(m_nameFilter, Qt::CaseInsensitive))
        return false;

    // Active state filter
    if (!m_activeStateFilter.isEmpty() && activeState != m_activeStateFilter)
        return false;

    return true;
}
