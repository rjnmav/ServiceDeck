#ifndef ICON_HELPER_H
#define ICON_HELPER_H

#include <QIcon>
#include <QColor>

class IconHelper
{
public:
    static QIcon tintedIcon(const QString &themeName, const QColor &color);
};

#endif // ICON_HELPER_H
