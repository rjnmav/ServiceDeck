#include "icon_helper.h"
#include <QPainter>
#include <QPixmap>

QIcon IconHelper::tintedIcon(const QString &themeName, const QColor &color)
{
    QIcon baseIcon = QIcon::fromTheme(themeName);
    if (baseIcon.isNull()) {
        return QIcon();
    }

    QIcon tintedIcon;
    // Common sizes for toolbar
    QList<int> sizes = {16, 20, 24, 32, 48};
    
    for (int size : sizes) {
        QPixmap pixmap = baseIcon.pixmap(size, size);
        if (pixmap.isNull()) continue;

        QPainter painter(&pixmap);
        painter.setCompositionMode(QPainter::CompositionMode_SourceIn);
        painter.fillRect(pixmap.rect(), color);
        painter.end();
        
        tintedIcon.addPixmap(pixmap);
    }

    return tintedIcon;
}
