add_library(ViewsLib STATIC
    mainwindow.cpp mainwindow.h
    servicetoolbar.cpp servicetoolbar.h
    servicedetailpanel.cpp servicedetailpanel.h
    createservicedialog.cpp createservicedialog.h
    preferencesdialog.cpp preferencesdialog.h
)
target_include_directories(ViewsLib PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(ViewsLib PRIVATE PresentersLib ServicesLib ModelsLib Qt5::Widgets)

if (SERVICEDECK_HAS_SD_JOURNAL)
    target_compile_definitions(ViewsLib PRIVATE SERVICEDECK_HAS_SD_JOURNAL=1)
    target_link_libraries(ViewsLib PRIVATE PkgConfig::SYSTEMD)
endif()
